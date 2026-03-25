#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import signal
import sys
import threading
import uuid
from datetime import datetime

from .sysinfo import SystemInfoUpdater, SystemInfo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # logging.FileHandler("/var/log/supervisor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Supervisor")

class Supervisor:
    OTA_DOWNLOAD_PATH = "/data/software.swu"

    def __init__(self):
        self.logger = logging.getLogger("Supervisor")

        self.shutdown_event = threading.Event()
        self.system_info = SystemInfo()
        self.http_server = None
        self.ota_operation_lock = threading.Lock()
        self.sysinfo_update = SystemInfoUpdater(self)

        self.ota_state = {
            'ota_id': None,
            'ota_status': 'idle',  # idle/download/install/success/failed
            'progress': 0,
            'start_time': '',
            'finish_time': '',
            'message': 'No OTA in progress'
        }
        self.ota_state_lock = threading.Lock()
        self._cleanup_stale_ota_artifacts()

    def _cleanup_stale_ota_artifacts(self):
        stale_paths = [
            self.OTA_DOWNLOAD_PATH,
            f"{self.OTA_DOWNLOAD_PATH}.part",
            "/data/conf/ota_history.json",
            "/data/conf/ota_history.json.tmp",
        ]

        for path in stale_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    self.logger.info("Removed stale OTA artifact: %s", path)
            except Exception as e:
                self.logger.warning("Failed to remove stale OTA artifact %s: %s", path, e)
    
    def _update_ota_state(self, **kwargs):
        with self.ota_state_lock:
            self.ota_state.update(kwargs)
            self.logger.debug(f"OTA state updated: {kwargs}")
    
    def get_ota_state(self):
        with self.ota_state_lock:
            return self.ota_state.copy()

    def _start_http_server(self):
        """Start HTTP server"""
        if not self.http_server:
            try:
                from .http_server import SupervisorHTTPServer
                self.http_server = SupervisorHTTPServer(self, port=8086)
                self.http_server.start()
                logger.info("HTTP server started")
                return True
            except Exception as e:
                logger.error(f"Failed to start HTTP server: {e}")
                return False
        return True

    def _stop_http_server(self):
        if not self.http_server:
            return True
        try:
            self.http_server.stop()
            self.http_server = None
            logger.info("HTTP server stopped")
            return True
        except Exception as e:
            logger.error(f"Failed to stop HTTP server: {e}")
            return False

    def perform_reboot(self):
        logging.info("Performing reboot...")
        from .utils import util
        util.perform_reboot()

    def perform_factory_reset(self):
        logging.info("Performing factory reset...")
        from .utils import util
        util.perform_factory_reset()

    def _mark_ota_failed(self, ota_id, error_msg):
        finish_time = time.strftime('%Y-%m-%d %H:%M:%S')
        self._update_ota_state(
            ota_id=ota_id,
            ota_status='failed',
            progress=100,
            finish_time=finish_time,
            message=error_msg
        )
        return False

    def _handle_download_progress(self, progress, has_progress):
        message = 'Downloading firmware...'
        if has_progress:
            message = f'Downloading firmware... {progress:.1f}%'
        self._update_ota_state(
            ota_status='download',
            progress=int(progress),
            message=message
        )

    def start_ota_update_async(self, *, url, version, md5):
        if not self.ota_operation_lock.acquire(blocking=False):
            raise RuntimeError("OTA update already in progress")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        ota_id = f"ota_{timestamp}_{unique_id}"
        worker = threading.Thread(
            target=self.perform_ota_update,
            kwargs={
                "url": url,
                "version": version,
                "md5": md5,
                "ota_id": ota_id,
                "lock_acquired": True,
            },
            daemon=True,
        )
        worker.start()
        return ota_id

    def perform_ota_update(self, url, version, md5, ota_id=None, lock_acquired=False):
        if ota_id is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_id = str(uuid.uuid4())[:8]
            ota_id = f"ota_{timestamp}_{unique_id}"

        owns_lock = lock_acquired
        if not owns_lock and not self.ota_operation_lock.acquire(blocking=False):
            error_msg = "OTA update already in progress"
            self.logger.warning(error_msg)
            return self._mark_ota_failed(ota_id, error_msg)
        owns_lock = True

        try:
            from .ota import (
                DEFAULT_DOWNLOAD_PATH,
                OTARelease,
                download_firmware,
            )
            self._update_ota_state(
                ota_id=ota_id,
                ota_status='download',
                progress=0,
                start_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                finish_time='',
                message='Starting OTA update...'
            )

            release = OTARelease(version=version, url=url, expected_md5=md5)
            self.logger.info(f"Starting OTA update to version {version}")
            self.logger.info(f"Download URL: {url}")

            downloaded_path = download_firmware(
                release,
                download_path=DEFAULT_DOWNLOAD_PATH,
                progress_callback=self._handle_download_progress,
            )

            self.logger.info(f"Firmware download prepared: {downloaded_path}")
            self._update_ota_state(
                ota_status='install',
                progress=100,
                message='Starting installation...'
            )

            return self._perform_upgrade(downloaded_path, version, ota_id)
        except Exception as e:
            error_msg = f"OTA update failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return self._mark_ota_failed(ota_id, error_msg)
        finally:
            if owns_lock:
                self.ota_operation_lock.release()

    def _perform_upgrade(self, download_path, version, ota_id):
        self.logger.info(f"Starting firmware upgrade to version {version} from {download_path}")

        self._update_ota_state(
            ota_status='install',
            progress=100,
            message='Installing firmware, please wait...'
        )

        try:
            from .ota import install_firmware
            install_firmware(download_path)
            self.logger.info(
                "swupdate completed successfully for ota_id=%s; waiting for reboot/version check",
                ota_id,
            )
            self._update_ota_state(
                ota_status='install',
                progress=100,
                message='Installation started, waiting for reboot...'
            )
            return True
        except Exception as e:
            error_msg = f"swupdate error: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return self._mark_ota_failed(ota_id, error_msg)

    def _signal_handler(self, sig, frame):
        logging.info("Signal received, stopping...")
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        self.shutdown_event.set()

        # Stop HTTP server
        self._stop_http_server()

    def run(self):
        """Main run function"""
        logger.info("Starting supervisor...")

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._start_http_server()

        self.sysinfo_update.start()

        logger.info("Supervisor started, waiting for signals...")
        try:
            self.shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self.cleanup()
            logger.info("Supervisor stopped")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Supervisor Service")
    parser.add_argument('--version', '-v', action='store_true', help='Show version and exit')
    parser.add_argument('command', nargs='?', default='daemon', choices=['daemon'], help="Command to run: daemon")
    parser.add_argument('arg', nargs='?', default=None, help="Argument for command (unused)")
    args = parser.parse_args()

    # Handle --version early and exit
    if getattr(args, 'version', False):
        print(f"Supervisor 1.0.0 (1.0.0)")
        sys.exit(0)

    if args.command == 'daemon':
        supervisor = Supervisor()
        try:
            supervisor.run()
        except KeyboardInterrupt:
            supervisor.cleanup()
            logger.info("Supervisor terminated by user")
        except Exception as e:
            logger.error(f"Unhandled exception: {e}")
            supervisor.cleanup()
    # CLI commands via local socket have been removed; only 'daemon' mode is supported

if __name__ == "__main__":
    main()
