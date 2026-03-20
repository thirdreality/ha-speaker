"""ThirdReality OTA update entity and version check client."""

import hashlib
import json
import logging
import os
import ssl
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    ListEntitiesRequest,
    ListEntitiesUpdateResponse,
    SubscribeHomeAssistantStatesRequest,
    UpdateCommandRequest,
    UpdateStateResponse,
)
from aioesphomeapi.model import EntityCategory
from google.protobuf import message

from linux_voice_assistant.entity import ESPHomeEntity

_LOGGER = logging.getLogger(__name__)

_DEVICE_CONF = Path("/data/conf/device.json")
_DOWNLOAD_PATH = Path("/data/software.swu")
_OTA_URL = "https://ota.cloud.3reality.com/reality/ota/client/checkVersion"
_CA_CERT = "/etc/ssl/certs/ca-certificates.crt"
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_CACHE_DROP_WINDOW = 1024 * 1024
_SWUPDATE_CMD = ["/usr/bin/swupdate", "-G", "-k", "/etc/swupdate-public.pem", "-H", "S420:1.0"]


@dataclass
class TROtaInfo:
    model_id: str
    current_version: str
    serial_number: str


@dataclass
class TROtaResult:
    current_version: str
    latest_version: str
    has_update: bool
    expected_md5: str = ""
    title: str = ""
    release_summary: str = ""
    release_url: str = ""


def load_device_info(path: Path = _DEVICE_CONF) -> Optional[TROtaInfo]:
    """Read current OTA-identifying information from device.json."""
    if not path.exists():
        _LOGGER.warning("[TR][update] missing device config: %s", path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as device_file:
            config = json.load(device_file)
    except Exception:
        _LOGGER.warning("[TR][update] failed to read %s", path, exc_info=True)
        return None

    if not isinstance(config, dict):
        _LOGGER.warning("[TR][update] invalid JSON object in %s", path)
        return None

    device = config.get("device")
    if not isinstance(device, dict):
        _LOGGER.warning("[TR][update] missing device object in %s", path)
        return None

    model_id = str(device.get("modelID", "")).strip()
    current_version = str(device.get("firmwareVersion", "")).strip()
    mac_address = str(device.get("macAddress", "")).strip()
    serial_number = mac_address.replace(":", "").upper()
    if not model_id or not serial_number:
        _LOGGER.warning("[TR][update] incomplete OTA identifiers in %s", path)
        return None

    return TROtaInfo(
        model_id=model_id,
        current_version=current_version,
        serial_number=serial_number,
    )


def check_version(device_info: TROtaInfo) -> TROtaResult:
    """Call ThirdReality OTA endpoint and return normalized version info."""
    payload = {
        "modelId": device_info.model_id,
        "version": device_info.current_version,
        "sno": device_info.serial_number,
    }
    cmd = [
        "curl",
        "--cacert",
        _CA_CERT,
        "-H",
        "Content-Type:application/json",
        "-m",
        "15",
        "-X",
        "POST",
        "-k",
        "--data",
        json.dumps(payload, separators=(",", ":")),
        _OTA_URL,
    ]
    _LOGGER.debug("[TR][update] checking OTA version for %s", device_info.model_id)

    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"curl failed (rc={proc.returncode}): {stderr}")

    response = json.loads(proc.stdout.decode("utf-8"))
    result = response.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("OTA response missing result object")

    data = result.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("OTA response missing data object")

    has_update = bool(data.get("hasNewVersion"))
    latest_version = str(
        data.get("displayVersion")
        or data.get("version")
        or device_info.current_version
    ).strip()
    expected_md5 = str(data.get("md5") or "").strip().lower()
    release_url = str(data.get("binUrl") or data.get("altBinUrl") or "").strip()
    release_summary = str(data.get("md5") or result.get("message") or "").strip()

    return TROtaResult(
        current_version=device_info.current_version,
        latest_version=latest_version if has_update else device_info.current_version,
        has_update=has_update,
        expected_md5=expected_md5,
        title="ThirdReality Firmware",
        release_summary=release_summary,
        release_url=release_url,
    )


def _download_target_path(download_path: Path, release_url: str, version: str) -> Path:
    del release_url
    del version
    return download_path


def _drop_file_cache(file_obj, offset: int, length: int) -> None:
    """Ask the kernel to drop file cache for a range we've already consumed."""
    if length <= 0:
        return
    posix_fadvise = getattr(os, "posix_fadvise", None)
    dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or dontneed is None:
        return
    try:
        posix_fadvise(file_obj.fileno(), offset, length, dontneed)
    except OSError:
        _LOGGER.debug("[TR][update] posix_fadvise(DONTNEED) failed", exc_info=True)


def _calculate_file_md5(path: Path) -> str:
    """Calculate a file MD5 incrementally."""
    digest = hashlib.md5()
    processed = 0
    dropped = 0
    with open(path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(_DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            processed += len(chunk)
            if processed - dropped >= _CACHE_DROP_WINDOW:
                _drop_file_cache(file_obj, dropped, processed - dropped)
                dropped = processed
    return digest.hexdigest().lower()


def download_firmware(
    result: TROtaResult,
    *,
    download_path: Path = _DOWNLOAD_PATH,
    progress_callback: Optional[Callable[[float, bool], None]] = None,
) -> Path:
    """Download firmware to disk with incremental MD5 validation."""
    if not result.release_url:
        raise ValueError("No release URL available for download")
    if not result.expected_md5:
        raise ValueError("No expected MD5 available for download validation")

    download_path.parent.mkdir(parents=True, exist_ok=True)
    destination = _download_target_path(download_path, result.release_url, result.latest_version)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    if temp_path.exists():
        temp_path.unlink()

    if destination.exists():
        existing_md5 = _calculate_file_md5(destination)
        if existing_md5 == result.expected_md5.lower():
            if progress_callback is not None:
                progress_callback(100.0, True)
            return destination
        destination.unlink()

    ssl_context = ssl.create_default_context(cafile=_CA_CERT)
    md5 = hashlib.md5()
    bytes_written = 0
    total_bytes: Optional[int] = None

    try:
        with urlopen(result.release_url, context=ssl_context, timeout=30) as response, open(temp_path, "wb") as output_file:
            header_length = response.headers.get("Content-Length")
            if header_length and header_length.isdigit():
                total_bytes = int(header_length)

            if progress_callback is not None:
                progress_callback(0.0, total_bytes is not None)

            dropped = 0
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output_file.write(chunk)
                md5.update(chunk)
                bytes_written += len(chunk)

                if bytes_written - dropped >= _CACHE_DROP_WINDOW:
                    output_file.flush()
                    os.fsync(output_file.fileno())
                    _drop_file_cache(output_file, dropped, bytes_written - dropped)
                    dropped = bytes_written

                if progress_callback is not None and total_bytes:
                    progress = min(100.0, (bytes_written / total_bytes) * 100.0)
                    progress_callback(progress, True)

            output_file.flush()
            os.fsync(output_file.fileno())
            if bytes_written > dropped:
                _drop_file_cache(output_file, dropped, bytes_written - dropped)

        actual_md5 = md5.hexdigest().lower()
        if actual_md5 != result.expected_md5.lower():
            raise ValueError(f"MD5 mismatch: expected {result.expected_md5}, got {actual_md5}")

        os.replace(temp_path, destination)

        if progress_callback is not None:
            progress_callback(100.0, total_bytes is not None)

        return destination
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def install_firmware(path: Path = _DOWNLOAD_PATH) -> None:
    """Run swupdate to install the already-downloaded firmware."""
    if not path.exists():
        raise FileNotFoundError(f"Firmware package not found: {path}")

    _LOGGER.info("[TR][update] starting swupdate install: %s", " ".join(_SWUPDATE_CMD))
    proc = subprocess.run(
        _SWUPDATE_CMD,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        timeout=3600,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"swupdate failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


class TRUpdateEntity(ESPHomeEntity):
    """ESPHome update entity backed by ThirdReality OTA version checks."""

    def __init__(
        self,
        server,
        key: int,
        name: str,
        object_id: str,
        *,
        current_version: str,
    ) -> None:
        super().__init__(server)
        self.key = key
        self.name = name
        self.object_id = object_id
        self.current_version = current_version
        self.latest_version = current_version
        self.expected_md5 = ""
        self.title = "ThirdReality Firmware"
        self.release_summary = ""
        self.release_url = ""
        self.in_progress = False
        self.has_progress = False
        self.progress = 0.0
        self.downloaded_path = ""
        self._log = logging.getLogger(f"{self.__class__.__name__}[{self.key}]")

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, ListEntitiesRequest):
            yield ListEntitiesUpdateResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                entity_category=EntityCategory.CONFIG,
                device_class="firmware",
                icon="mdi:update",
            )
        elif isinstance(msg, SubscribeHomeAssistantStatesRequest):
            yield self._get_state_message()
        elif isinstance(msg, UpdateCommandRequest) and msg.key == self.key:
            yield self._get_state_message()

    def apply_result(self, result: TROtaResult) -> None:
        self.current_version = result.current_version
        self.latest_version = result.latest_version
        self.expected_md5 = result.expected_md5
        self.title = result.title
        self.release_summary = result.release_summary
        self.release_url = result.release_url

    def set_download_progress(self, progress: float, *, has_progress: bool) -> None:
        self.in_progress = True
        self.has_progress = has_progress
        self.progress = progress

    def mark_download_complete(self, downloaded_path: Path) -> None:
        self.in_progress = False
        self.has_progress = True
        self.progress = 100.0
        self.downloaded_path = str(downloaded_path)
        self.release_summary = f"Downloaded and verified: {downloaded_path.name}"

    def mark_download_failed(self, reason: str) -> None:
        self.in_progress = False
        self.has_progress = False
        self.progress = 0.0
        self.release_summary = reason

    def _get_state_message(self) -> UpdateStateResponse:
        return UpdateStateResponse(
            key=self.key,
            missing_state=False,
            in_progress=self.in_progress,
            has_progress=self.has_progress,
            progress=self.progress,
            current_version=self.current_version,
            latest_version=self.latest_version,
            title=self.title,
            release_summary=self.release_summary,
            release_url=self.release_url,
        )
