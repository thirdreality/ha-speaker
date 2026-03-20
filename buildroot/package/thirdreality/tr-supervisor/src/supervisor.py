#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import signal
import json
import sys
import threading
import uuid
from datetime import datetime

from .utils import util
from .http_server import SupervisorHTTPServer
from .ota import DEFAULT_DOWNLOAD_PATH, OTARelease, download_firmware, install_firmware
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
    OTA_HISTORY_FILE = "/data/conf/ota_history.json"

    def __init__(self):
        self.logger = logging.getLogger("Supervisor")

        self.state_lock = threading.Lock()
        self.running = threading.Event()
        self.running.set()
        self.stop_event = threading.Event()
        
        self.system_info = SystemInfo()

        self.http_server = None

        self.sysinfo_update = SystemInfoUpdater(self)
        
        # boot up time
        self.start_time = time.time()

        self.ota_state = {
            'ota_id': None,
            'ota_status': 'idle',  # idle/download/install/success/failed
            'progress': 0,
            'start_time': '',
            'finish_time': '',
            'message': 'No OTA in progress'
        }
        self.ota_state_lock = threading.Lock()
        
        self.ota_history = self._load_ota_history()
        
        self._check_last_ota_status()
        
    def _load_ota_history(self):
        try:
            if os.path.exists(self.OTA_HISTORY_FILE):
                with open(self.OTA_HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.logger.info(f"OTA history loaded from {self.OTA_HISTORY_FILE}")
                    return data
        except Exception as e:
            self.logger.error(f"Failed to load OTA history: {e}")
    
        return {
            "last_ota": None
        }

    def _save_ota_history(self):
        try:
            os.makedirs(os.path.dirname(self.OTA_HISTORY_FILE), exist_ok=True)
            
            with open(self.OTA_HISTORY_FILE, 'w') as f:
                json.dump(self.ota_history, f, indent=2, ensure_ascii=False)
            self.logger.info("OTA history saved")
        except Exception as e:
            self.logger.error(f"Failed to save OTA history: {e}")
    
    def _check_last_ota_status(self):
        last_ota = self.ota_history.get('last_ota')

        if not last_ota:
            self.logger.info("No previous OTA found")
            return

        if last_ota.get('ota_status') == 'download':
            self.logger.info("Clearing interrupted OTA download state")
            self.ota_history['last_ota'] = None
            self._save_ota_history()
            return

        current_id = last_ota.get('ota_id')
        if not current_id:
            self.logger.info("Previous OTA record has no ota_id")
            return
        
        target_version = last_ota.get('target_version', '')
        if not target_version:
            self.logger.info("Previous OTA record has no target_version")
            return
        
        try:
            from .sysinfo import get_device_info
            device_info = get_device_info()
            current_version = device_info.get('firmwareVersion', '')
            
            self.logger.info(f"Checking OTA status: Current version: {current_version}, Target version: {target_version}")
            
            finish_time = time.strftime('%Y-%m-%d %H:%M:%S')
            
            if current_version and current_version == target_version:
                self.logger.info(f"✓ OTA {current_id} succeeded!")
                last_ota['ota_status'] = 'success'
                last_ota['progress'] = 100
                last_ota['finish_time'] = finish_time
                last_ota['message'] = 'OTA completed successfully'
                
                with self.ota_state_lock:
                    self.ota_state['ota_id'] = current_id
                    self.ota_state['ota_status'] = 'success'
                    self.ota_state['progress'] = 100
                    self.ota_state['start_time'] = last_ota.get('start_time', '')
                    self.ota_state['finish_time'] = finish_time
                    self.ota_state['message'] = 'OTA completed successfully'
                
                self._save_ota_history()
            else:
                if last_ota.get('ota_status') == 'install':
                    self.logger.warning(f"✗ OTA {current_id} failed - version mismatch")
                    last_ota['ota_status'] = 'failed'
                    last_ota['progress'] = 100
                    last_ota['finish_time'] = finish_time
                    last_ota['message'] = f'OTA failed: version mismatch (expected: {target_version}, got: {current_version})'
                    
                    with self.ota_state_lock:
                        self.ota_state['ota_id'] = current_id
                        self.ota_state['ota_status'] = 'failed'
                        self.ota_state['progress'] = 100
                        self.ota_state['start_time'] = last_ota.get('start_time', '')
                        self.ota_state['finish_time'] = finish_time
                        self.ota_state['message'] = f'Version mismatch (expected: {target_version}, got: {current_version})'
                    
                    self._save_ota_history()
                else:
                    self.logger.info(f"OTA {current_id} still in progress or not completed")
            
        except Exception as e:
            self.logger.error(f"Error checking OTA status: {e}")
            if last_ota.get('ota_status') == 'install':
                last_ota['ota_status'] = 'failed'
                last_ota['finish_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
                last_ota['message'] = f'Error checking version: {str(e)}'
                
                with self.ota_state_lock:
                    self.ota_state['ota_id'] = current_id
                    self.ota_state['ota_status'] = 'failed'
                    self.ota_state['progress'] = 100
                    self.ota_state['start_time'] = last_ota.get('start_time', '')
                    self.ota_state['finish_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
                    self.ota_state['message'] = f'Error: {str(e)}'
                
                self._save_ota_history()

    def _record_ota_start(self, ota_id, version, url, md5):
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        self.ota_history['last_ota'] = {
            'ota_id': ota_id,
            'target_version': version,
            'url': url,
            'md5': md5,
            'ota_status': 'install',
            'progress': 100,
            'start_time': start_time,
            'message': 'Installing firmware...'
        }
        self._save_ota_history()
        self.logger.info(f"OTA install recorded: ID={ota_id}, version={version}")
        
    def _record_ota_installing(self, ota_id):
        last_ota = self.ota_history.get('last_ota')
        if last_ota and last_ota.get('ota_id') == ota_id:
            last_ota['ota_status'] = 'install'
            last_ota['progress'] = 100
            last_ota['message'] = 'Installing firmware...'
            self._save_ota_history()
            self.logger.info(f"OTA {ota_id} status updated: install")

    def _record_ota_failed(self, ota_id, error_msg):
        last_ota = self.ota_history.get('last_ota')
        if last_ota and last_ota.get('ota_id') == ota_id:
            last_ota['ota_status'] = 'failed'
            last_ota['finish_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
            last_ota['message'] = f'OTA failed: {error_msg}'
            self._save_ota_history()
            self.logger.info(f"OTA {ota_id} failure recorded: {error_msg}")
        
    def get_ota_history(self):
        return self.ota_history.copy()
    
    def _update_ota_state(self, **kwargs):
        with self.ota_state_lock:
            self.ota_state.update(kwargs)
            self.logger.debug(f"OTA state updated: {kwargs}")
    
    def get_ota_state(self):
        with self.ota_state_lock:
            return self.ota_state.copy()

    def get_ota_status_by_id(self, ota_id=None):
        if ota_id is None:
            with self.ota_state_lock:
                current_state = self.ota_state.copy()
                return {
                    'ota_id': current_state.get('ota_id'),
                    'ota_status': current_state.get('ota_status'),
                    'progress': current_state.get('progress', 0),
                    'start_time': current_state.get('start_time', ''),
                    'finish_time': current_state.get('finish_time', ''),
                    'message': current_state.get('message', '')
                }
        
        with self.ota_state_lock:
            if self.ota_state.get('ota_id') == ota_id:
                current_state = self.ota_state.copy()
                return {
                    'ota_id': current_state.get('ota_id'),
                    'ota_status': current_state.get('ota_status'),
                    'progress': current_state.get('progress', 0),
                    'start_time': current_state.get('start_time', ''),
                    'finish_time': current_state.get('finish_time', ''),
                    'message': current_state.get('message', '')
                }
        
        record = self.ota_history['records'].get(ota_id)
        if record:
            return {
                'ota_id': record.get('ota_id'),
                'ota_status': record.get('ota_status'),
                'progress': record.get('progress', 0),
                'start_time': record.get('start_time', ''),
                'finish_time': record.get('finish_time', ''),
                'message': record.get('message', '')
            }
        
        return {
            'ota_id': ota_id,
            'ota_status': 'error',
            'message': 'OTA ID not found'
        }

    def _start_http_server(self):
        """Start HTTP server"""
        if not self.http_server:
            try:
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
        util.perform_reboot()

    def perform_factory_reset(self):
        logging.info("Performing factory reset...")
        util.perform_factory_reset()

    def _mark_ota_failed(self, ota_id, error_msg):
        finish_time = time.strftime('%Y-%m-%d %H:%M:%S')
        self._record_ota_failed(ota_id, error_msg)
        self._update_ota_state(
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

    def perform_ota_update(self, url, version, md5, ota_id=None):
        if ota_id is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_id = str(uuid.uuid4())[:8]
            ota_id = f"ota_{timestamp}_{unique_id}"

        try:
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
            self._record_ota_start(ota_id, version, url, md5)
            self._record_ota_installing(ota_id)
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

    def _perform_upgrade(self, download_path, version, ota_id):
        self.logger.info(f"Starting firmware upgrade to version {version} from {download_path}")

        self._record_ota_installing(ota_id)
        self._update_ota_state(
            ota_status='install',
            progress=100,
            message='Installing firmware, please wait...'
        )

        try:
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
        self.running.clear()

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
            while self.running.is_set():
                time.sleep(1)
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
