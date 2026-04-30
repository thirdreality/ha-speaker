"""OTA download and installation helpers for tr-supervisor."""

import hashlib
import logging
import os
import ssl
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

LOGGER = logging.getLogger("Supervisor")

CA_CERT = "/etc/ssl/certs/ca-certificates.crt"
DEFAULT_DOWNLOAD_PATH = Path("/data/software.swu")
DOWNLOAD_CHUNK_SIZE = 64 * 1024
CACHE_DROP_WINDOW = 1024 * 1024
SWUPDATE_CMD = [
    "/usr/bin/swupdate",
    "-G",
    "-k",
    "/etc/swupdate-public.pem",
    "-H",
    "S420:1.0",
]


@dataclass(frozen=True)
class OTARelease:
    version: str
    url: str
    expected_md5: str


def _download_target_path(download_path: Path, release: OTARelease) -> Path:
    del release
    return download_path


def _drop_file_cache(file_obj, offset: int, length: int) -> None:
    if length <= 0:
        return
    posix_fadvise = getattr(os, "posix_fadvise", None)
    dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or dontneed is None:
        return
    try:
        posix_fadvise(file_obj.fileno(), offset, length, dontneed)
    except OSError:
        LOGGER.debug("posix_fadvise(DONTNEED) failed", exc_info=True)


def calculate_file_md5(path: Path) -> str:
    digest = hashlib.md5()
    processed = 0
    dropped = 0
    with open(path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            processed += len(chunk)
            if processed - dropped >= CACHE_DROP_WINDOW:
                _drop_file_cache(file_obj, dropped, processed - dropped)
                dropped = processed
    return digest.hexdigest().lower()


def download_firmware(
    release: OTARelease,
    *,
    download_path: Path = DEFAULT_DOWNLOAD_PATH,
    progress_callback: Optional[Callable[[float, bool], None]] = None,
) -> Path:
    if not release.url:
        raise ValueError("No release URL available for download")
    if not release.expected_md5:
        raise ValueError("No expected MD5 available for download validation")

    download_path.parent.mkdir(parents=True, exist_ok=True)
    destination = _download_target_path(download_path, release)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    if temp_path.exists():
        temp_path.unlink()

    if destination.exists():
        existing_md5 = calculate_file_md5(destination)
        if existing_md5 == release.expected_md5.lower():
            if progress_callback is not None:
                progress_callback(100.0, True)
            return destination
        destination.unlink()

    ssl_context = ssl.create_default_context(cafile=CA_CERT)
    md5 = hashlib.md5()
    bytes_written = 0
    total_bytes: Optional[int] = None

    try:
        with urlopen(release.url, context=ssl_context, timeout=30) as response, open(temp_path, "wb") as output_file:
            header_length = response.headers.get("Content-Length")
            if header_length and header_length.isdigit():
                total_bytes = int(header_length)

            if progress_callback is not None:
                progress_callback(0.0, total_bytes is not None)

            dropped = 0
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output_file.write(chunk)
                md5.update(chunk)
                bytes_written += len(chunk)

                if bytes_written - dropped >= CACHE_DROP_WINDOW:
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
        if actual_md5 != release.expected_md5.lower():
            raise ValueError(
                f"MD5 mismatch: expected {release.expected_md5}, got {actual_md5}"
            )

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


def install_firmware(path: Path = DEFAULT_DOWNLOAD_PATH) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Firmware package not found: {path}")

    LOGGER.info("starting swupdate install: %s", " ".join(SWUPDATE_CMD))
    proc = subprocess.run(
        SWUPDATE_CMD,
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
