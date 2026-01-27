import argparse
import json
import logging
import shutil
import ssl
import tempfile
from urllib import request
from pathlib import Path
import subprocess
import threading
import os
import signal
import time
import ctypes
import hashlib
import re

_LOGGER = logging.getLogger(__name__)

DEFAULT_DEST = Path("/data/software.swu")
OTA_METADATA = Path("/data/conf/ota_update.json")
OTA_STATUS = Path("/data/conf/ota_status.json")
PID_FILE = Path("/tmp/ota_curl.pid")


def _write_status_global(ota_status: str, progress: float = 0.0, message: str = "") -> None:
    # Only allow these four global status values; other transient/internal
    # statuses (e.g. 'verify') should not be written via this global helper.
    allowed = {"download", "install", "success", "failed"}
    if ota_status not in allowed:
        _LOGGER.debug("_write_status_global: ignoring non-global status '%s'", ota_status)
        return

    try:
        OTA_STATUS.parent.mkdir(parents=True, exist_ok=True)
        with open(OTA_STATUS, "w", encoding="utf-8") as sf:
            json.dump({"ota_status": ota_status, "progress": float(progress), "message": message}, sf, ensure_ascii=False)
    except Exception as e:
        _LOGGER.debug("Write ota status failed: %s", e)


def _get_expected_sha256() -> str | None:
    try:
        with open(OTA_METADATA, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None

    for key in ("sha256", "sha256sum", "checksum", "hash"):
        val = meta.get(key)
        if isinstance(val, str):
            v = val.strip().lower()
            if re.fullmatch(r"[a-f0-9]{64}", v):
                return v

    text = str(meta.get("release_summary") or "")
    url = str(meta.get("url") or "")
    filename = url.rsplit("/", 1)[-1] if url else ""
    if text:
        if filename:
            for line in text.splitlines():
                if filename in line:
                    m = re.search(r"([a-fA-F0-9]{64})", line)
                    if m:
                        return m.group(1).lower()
        m = re.search(r"([a-fA-F0-9]{64})", text)
        if m:
            return m.group(1).lower()
    return None


def _verify_sha256(path: Path, expected: str) -> bool:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        actual = h.hexdigest().lower()
        _LOGGER.info("SHA256 computed: %s", actual)
        if actual == expected:
            return True
        _LOGGER.error("SHA256 mismatch: expected=%s actual=%s", expected, actual)
        return False
    except Exception as e:
        _LOGGER.error("SHA256 verification failed: %s", e)
        return False


def download_file(url: str, dest_path: Path, chunk_size: int = 8192) -> bool:
    """Download URL to dest_path.tmp, then move to dest_path. Returns True on success."""
    dest_tmp = dest_path.with_suffix(dest_path.suffix + ".tmp")

    # If a final firmware file already exists, verify it first. If verification
    # succeeds, skip download and treat as already downloaded. If verification
    # fails, remove the existing file and continue with download.
    try:
        if dest_path.exists():
            _LOGGER.info("Existing firmware %s found before download, running verification", dest_path)
            try:
                ok = check_swu(dest_path)
            except Exception as e:
                _LOGGER.error("check_swu raised exception: %s", e)
                ok = False
            if ok:
                _LOGGER.info("Existing firmware verified, skipping download")
                try:
                    # Treat verified existing file as ready for install (global status 'install')
                    _write_status_global("install", 100.0, "Existing firmware verified")
                except Exception:
                    pass
                return True
            else:
                _LOGGER.info("Existing firmware failed verification, removing and proceeding to download")
                try:
                    dest_path.unlink()
                except Exception as e:
                    _LOGGER.warning("Failed to remove invalid existing firmware %s: %s", dest_path, e)
                try:
                    _write_status_global("download", 0.0, "Removed invalid firmware, starting download")
                except Exception:
                    pass
    except Exception:
        pass

    # Use system curl for robust downloading (same behavior as supervisor)
    # If a partial tmp file exists, curl -C - will resume automatically.
    if dest_tmp.exists():
        partial_size = dest_tmp.stat().st_size
        _LOGGER.info("Found partial download %s (size=%d), will attempt resume", dest_tmp, partial_size)

    curl_cmd = [
        "curl",
        "-k",
        "-L",
        "--retry", "3",
        "--connect-timeout", "60",
        "--max-time", "1800",
        "-C", "-",  # enable resume if server supports Range
        "-o", str(dest_tmp),
        url,
    ]

    _LOGGER.info("Starting curl download: %s", " ".join(curl_cmd))
    try:
        _write_status_global("download", 0.0, "Starting download")
    except Exception:
        pass

    def _write_status(ota_status: str, progress: float = 0.0, message: str = ""):
        try:
            OTA_STATUS.parent.mkdir(parents=True, exist_ok=True)
            with open(OTA_STATUS, "w", encoding="utf-8") as sf:
                json.dump({
                    "ota_status": ota_status,
                    "progress": float(progress),
                    "message": message,
                }, sf, ensure_ascii=False)
        except Exception as e:
            _LOGGER.debug("Write ota status failed: %s", e)

    try:
        # Ensure parent exists
        try:
            dest_tmp.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # attempt to get total size via HEAD (curl -sI)
        total_size = 0
        try:
            # follow redirects when probing headers so we get accurate Content-Length
            head = subprocess.run(["curl", "-sI", "-k", "-L", url], capture_output=True, text=True, timeout=30)
            for line in head.stdout.splitlines():
                if line.lower().startswith("content-length:"):
                    try:
                        size = int(line.split(":", 1)[1].strip())
                    except Exception:
                        continue
                    # curl -I -L returns headers for each redirect; keep the last non-zero length.
                    if size > 0:
                        total_size = size
        except Exception:
            total_size = 0

        # already wrote initial download status above before launching curl

        download_complete = threading.Event()
        download_error: list[Exception | None] = [None]

        def _is_pid_running(pid: int) -> bool:
            try:
                os.kill(pid, 0)
            except Exception:
                return False
            return True

        # If a previous curl was left running, attempt to stop it before starting.
        try:
            if PID_FILE.exists():
                try:
                    old_pid = int(PID_FILE.read_text().strip())
                    if _is_pid_running(old_pid):
                        _LOGGER.info("Found existing curl pid %d, attempting to terminate", old_pid)
                        try:
                            os.killpg(old_pid, signal.SIGTERM)
                        except Exception:
                            try:
                                os.kill(old_pid, signal.SIGTERM)
                            except Exception:
                                pass
                        # wait briefly for process to exit
                        for _ in range(10):
                            if not _is_pid_running(old_pid):
                                break
                            time.sleep(0.5)
                        if _is_pid_running(old_pid):
                            _LOGGER.info("Killing lingering curl pid %d", old_pid)
                            try:
                                os.killpg(old_pid, signal.SIGKILL)
                            except Exception:
                                try:
                                    os.kill(old_pid, signal.SIGKILL)
                                except Exception:
                                    pass
                except Exception:
                    pass
                try:
                    PID_FILE.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        def _preexec_set_pdeathsig():
            # Create a new session and request the kernel to send SIGTERM to
            # this process if the parent dies (PR_SET_PDEATHSIG). This helps
            # ensure curl is terminated if the Python process exits (OOM/restart).
            try:
                os.setsid()
            except Exception:
                pass
            try:
                PR_SET_PDEATHSIG = 1
                libc = ctypes.CDLL("libc.so.6")
                libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
            except Exception:
                pass

        def _run_curl():
            proc = None
            try:
                # Start curl in its own process group so we can terminate the whole group.
                proc = subprocess.Popen(curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=_preexec_set_pdeathsig)
                try:
                    # Do not attempt to create parent directory for PID file (/tmp is expected to exist).
                    PID_FILE.write_text(str(proc.pid))
                except Exception:
                    pass

                out, err = proc.communicate()
                if proc.returncode != 0:
                    download_error[0] = subprocess.CalledProcessError(proc.returncode, curl_cmd, output=out, stderr=err)
            except Exception as e:
                download_error[0] = e
            finally:
                try:
                    if PID_FILE.exists():
                        PID_FILE.unlink()
                except Exception:
                    pass
                download_complete.set()

        # Before starting the download process, attempt to flush IO and drop pagecache
        try:
            try:
                subprocess.run(['sync'], timeout=5, check=False)
            except Exception:
                pass
            try:
                with open('/proc/sys/vm/drop_caches', 'w') as f:
                    f.write('1\n')
            except Exception:
                try:
                    subprocess.run(['sh', '-c', 'echo 1 > /proc/sys/vm/drop_caches'], timeout=5, check=False)
                except Exception:
                    pass
            _LOGGER.info("Cache clear before download")
        except Exception as e:
            _LOGGER.debug("Pre-download cache clear skipped: %s", e)

        thread = threading.Thread(target=_run_curl)
        thread.start()

        last_size = 0
        last_log_mb = 0
        while not download_complete.is_set():
            thread.join(timeout=1)
            try:
                if dest_tmp.exists():
                    current_size = dest_tmp.stat().st_size
                    if current_size != last_size:
                        mb = current_size // (1024 * 1024)
                        if mb > last_log_mb:
                            last_log_mb = mb
                            _LOGGER.info("Download progress: %d MB", mb)
                        last_size = current_size
                        # update percentage if total_size known
                        if total_size > 0:
                            frac = float(current_size) / float(total_size)
                            _write_status("download", float(frac), f"Downloading: {current_size}/{total_size} bytes")
                            # also include explicit byte counts
                            try:
                                OTA_STATUS.parent.mkdir(parents=True, exist_ok=True)
                                with open(OTA_STATUS, "w", encoding="utf-8") as sf:
                                    json.dump({
                                        "ota_status": "download",
                                        "progress": float(frac),
                                        "message": f"Downloading: {current_size}/{total_size} bytes",
                                        "downloaded_bytes": int(current_size),
                                        "total_bytes": int(total_size),
                                    }, sf, ensure_ascii=False)
                            except Exception:
                                pass
                        else:
                            # No total size available; write downloaded bytes and leave progress=0.0
                            try:
                                OTA_STATUS.parent.mkdir(parents=True, exist_ok=True)
                                with open(OTA_STATUS, "w", encoding="utf-8") as sf:
                                    json.dump({
                                        "ota_status": "download",
                                        "progress": 0.0,
                                        "message": f"Downloading: {current_size} bytes",
                                        "downloaded_bytes": int(current_size),
                                        "total_bytes": None,
                                    }, sf, ensure_ascii=False)
                            except Exception:
                                pass
            except Exception:
                pass

        thread.join()

        if download_error[0] is not None:
            _LOGGER.error("curl download failed: %s", download_error[0])
            try:
                _write_status("failed", 0.0, f"curl download failed: {download_error[0]}")
            except Exception:
                pass
            try:
                if dest_tmp.exists():
                    dest_tmp.unlink()
            except Exception:
                pass
            return False

        if not dest_tmp.exists():
            _LOGGER.error("Download failed: file missing after curl")
            return False

        final_size = dest_tmp.stat().st_size
        _LOGGER.info("Curl download finished: %d bytes", final_size)
        _write_status("download", 100.0, "Download completed")

        # Post-download verification is handled in check_swu via sha256

        # Move into place
        try:
            shutil.move(str(dest_tmp), str(dest_path))
        except Exception as e:
            _LOGGER.error("Move downloaded file failed: %s", e)
            try:
                dest_tmp.unlink()
            except Exception:
                pass
            return False

        _LOGGER.info("Saved firmware to %s", dest_path)
        # After saving firmware, flush IO and drop pagecache to reduce OOM risk
        try:
            try:
                subprocess.run(['sync'], timeout=5, check=False)
            except Exception:
                pass
            try:
                with open('/proc/sys/vm/drop_caches', 'w') as f:
                    f.write('1\n')
            except Exception:
                try:
                    subprocess.run(['sh', '-c', 'echo 1 > /proc/sys/vm/drop_caches'], timeout=5, check=False)
                except Exception:
                    pass
            _LOGGER.info("Cache clear after download")
        except Exception as e:
            _LOGGER.debug("Post-download cache clear skipped: %s", e)
        # After saving firmware, report global status 'install' with progress=100
        try:
            _write_status_global("install", 100.0, "Saved firmware")
        except Exception:
            # fallback to local write
            try:
                _write_status("install", 100.0, "Saved firmware")
            except Exception:
                pass
        return True

    except Exception as e:
        _LOGGER.error("Download failed: %s", e)
        try:
            _write_status("failed", 0.0, f"download exception: {e}")
        except Exception:
            pass
        try:
            if dest_tmp.exists():
                dest_tmp.unlink()
        except Exception:
            pass
        return False


def install_swu(path: Path) -> bool:
    """Try to install SWU using known commands. Returns True if installation command succeeded (exit code 0).
    This function attempts multiple common command paths.
    """
    # Use the final OTA invocation as provided: swupdate -G -k /etc/swupdate-public.pem -H S420:1.0
    cmds = [
        ["/usr/bin/swupdate", "-G", "-k", "/etc/swupdate-public.pem", "-H", "S420:1.0"],
    ]

    # Execute the single configured install command (no shell fallback)
    cmd = cmds[0]
    try:
        _LOGGER.info("Trying install command: %s", cmd)
        try:
            # update status file indicating install started
            OTA_STATUS.parent.mkdir(parents=True, exist_ok=True)
            with open(OTA_STATUS, "w", encoding="utf-8") as sf:
                json.dump({"ota_status": "install", "progress": 0.0, "message": "Installing firmware"}, sf, ensure_ascii=False)
        except Exception:
            pass
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        _LOGGER.info("Install stdout: %s", proc.stdout[:1000])
        _LOGGER.info("Install stderr: %s", proc.stderr[:1000])
        if proc.returncode == 0:
            _LOGGER.info("swupdate succeeded with: %s", cmd)
            try:
                _write_status_global("success", 100.0, "Installation succeeded")
            except Exception:
                pass
            return True
        else:
            _LOGGER.warning("swupdate returned %s for %s", proc.returncode, cmd)
            try:
                _write_status_global("failed", 100.0, f"swupdate rc={proc.returncode}")
            except Exception:
                pass
    except FileNotFoundError:
        _LOGGER.debug("Install command not found: %s", cmd)
    except subprocess.TimeoutExpired:
        _LOGGER.error("Install command timed out: %s", cmd)
        try:
            _write_status_global("failed", 100.0, "swupdate timeout")
        except Exception:
            pass
    except Exception as e:
        _LOGGER.error("Install command failed (%s): %s", cmd, e)
        try:
            _write_status_global("failed", 100.0, str(e))
        except Exception:
            pass

    _LOGGER.error("No swupdate command succeeded")
    _write_status_global("failed", 100.0, "No swupdate command succeeded")
    return False


def check_swu(path: Path) -> bool:
    """Verify SWU integrity using sha256 from OTA metadata.
    Returns True if sha256 matches, otherwise False."""
    target = DEFAULT_DEST

    _LOGGER.debug("Verifying firmware %s (sha256)", str(target))
    expected = _get_expected_sha256()
    if not expected:
        _LOGGER.error("Missing sha256 in OTA metadata; cannot verify firmware")
        _write_status_global("failed", 0.0, "sha256 missing in OTA metadata")
        return False

    if not target.exists():
        _LOGGER.error("Firmware file not found for sha256 check: %s", target)
        _write_status_global("failed", 0.0, "firmware file missing for sha256 check")
        return False

    if _verify_sha256(target, expected):
        _LOGGER.info("sha256 verification succeeded")
        return True

    _write_status_global("failed", 0.0, "sha256 verification failed")
    return False


def run_from_metadata(metadata_path: Path = OTA_METADATA) -> int:
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        _LOGGER.error("Read ota metadata failed: %s", e)
        return 2

    url = meta.get("url")
    _LOGGER.info("OTA run_from_metadata: url=%s metadata_path=%s", url, metadata_path)
    if not url:
        _LOGGER.error("No url in ota metadata")
        return 3

    dest = DEFAULT_DEST
    ok = download_file(url, dest)
    if not ok:
        return 4

    # Run sha256 check before actual install.
    try:
        if not check_swu(dest):
            return 6
    except Exception as e:
        _LOGGER.error("swupdate check raised exception: %s", e)
        _write_status_global("failed", 0.0, f"swupdate check exception: {e}")
        return 6

    ok = install_swu(dest)
    return 0 if ok else 5


def main() -> int:
    parser = argparse.ArgumentParser(description="OTA downloader/installer helper")
    parser.add_argument("--url", help="firmware URL")
    # note: sha256 verification is performed in check_swu based on ota_update.json
    parser.add_argument("--dest", help="destination path", default=str(DEFAULT_DEST))
    parser.add_argument("--from-metadata", action="store_true", help="read /data/conf/ota_update.json and run")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    if args.from_metadata:
        return run_from_metadata()

    if not args.url:
        parser.print_help()
        return 1

    dest = Path(args.dest)
    ok = download_file(args.url, dest)
    if not ok:
        return 4
    ok = install_swu(dest)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
