#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import signal
import json
import sys
import threading
import hashlib
import subprocess 
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .utils import util
from .http_server import SupervisorHTTPServer  
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
            'ota_status': 'download',
            'progress': 0,
            'start_time': start_time,
            'message': 'Starting OTA update...'
        }
        self._save_ota_history()
        self.logger.info(f"OTA start recorded: ID={ota_id}, version={version}")
        
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

    def perform_ota_update(self, url, version, md5, ota_id=None):
        import requests
        import uuid
        from datetime import datetime
        
        if ota_id is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_id = str(uuid.uuid4())[:8]
            ota_id = f"ota_{timestamp}_{unique_id}"
        
        try:
            self._record_ota_start(ota_id, version, url, md5)
            
            self._update_ota_state(
                ota_id=ota_id,
                ota_status='download',
                progress=0,
                start_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                message='Starting OTA update...'
            )
            
            self.logger.info(f"Starting OTA update to version {version}")
            self.logger.info(f"Download URL: {url}")
            
            download_path = "/data/software.swu"
            
            if os.path.exists(download_path):
                self.logger.info(f"Found existing file: {download_path}")
                self._update_ota_state(message='Checking existing file...')
                
                file_size = os.path.getsize(download_path)
                if file_size > 0:
                    self.logger.info(f"Existing file size: {file_size} bytes")
                    
                    self.logger.info("Verifying MD5 of existing file...")
                    self._update_ota_state(message='Verifying existing file MD5...')
                    calculated_md5 = self._calculate_file_md5(download_path, show_progress=True)
                    
                    if calculated_md5.lower() == md5.lower():
                        self.logger.info("✓ MD5 verification passed! Using existing file.")
                        self._update_ota_state(
                            ota_status='install',
                            progress=100,
                            message='Using existing file, starting installation...'
                        )
                        return self._perform_upgrade(download_path, version, ota_id)
                    else:
                        self.logger.warning(f"✗ MD5 mismatch! Expected: {md5}, Got: {calculated_md5}")
                        self.logger.info("Deleting corrupted file and re-downloading...")
                        self._update_ota_state(message='Existing file corrupted, re-downloading...')
                        os.remove(download_path)
                else:
                    self.logger.warning("Existing file is empty, deleting...")
                    os.remove(download_path)
            
            self.logger.info("Downloading firmware with CURL...")
            self._update_ota_state(message='Downloading firmware...')

            try:
                head_result = subprocess.run(
                    ['curl', '-sI', '-k', url],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                total_size = 0
                for line in head_result.stdout.split('\n'):
                    if 'content-length:' in line.lower():
                        total_size = int(line.split(':')[1].strip())
                        break
                
                total_mb = total_size / 1024 / 1024 if total_size > 0 else 0
                self.logger.info(f"File size: {total_mb:.2f} MB")
                
            except Exception as e:
                self.logger.warning(f"Failed to get file size: {e}")
                total_size = 0

            curl_cmd = [
                'curl',
                '-k',
                '-L',
                '--retry', '3',
                '--connect-timeout', '60',
                '--max-time', '1800',
                '-o', download_path,
                url
            ]

            self.logger.info(f"Download command: {' '.join(curl_cmd)}")

            try:
                download_complete = threading.Event()
                download_error = [None]
                
                def download_task():
                    try:
                        result = subprocess.run(curl_cmd, capture_output=True, text=True, check=True)
                        download_complete.set()
                    except subprocess.CalledProcessError as e:
                        download_error[0] = e
                        download_complete.set()
                
                download_thread = threading.Thread(target=download_task)
                download_thread.start()
                
                last_size = 0
                stall_count = 0
                last_log_mb = 0
                cache_clear_counter = 0
                
                while not download_complete.is_set():
                    time.sleep(2)
                    
                    if os.path.exists(download_path):
                        current_size = os.path.getsize(download_path)
                        
                        if current_size == last_size and current_size > 0:
                            stall_count += 1
                            if stall_count > 60:
                                self.logger.warning("Download stalled for 2 minutes, aborting...")
                                break
                        else:
                            stall_count = 0
                        
                        last_size = current_size
                        
                        cache_clear_counter += 1
                        if cache_clear_counter >= 20:
                            try:
                                subprocess.run(['sync'], timeout=5, check=False)
                                with open('/proc/sys/vm/drop_caches', 'w') as f:
                                    f.write('1\n')
                                self.logger.debug("Page cache cleared")
                                cache_clear_counter = 0
                            except PermissionError:
                                if cache_clear_counter == 20:
                                    self.logger.warning("No permission to clear cache, memory may grow during download")
                                cache_clear_counter = 0
                            except Exception as e:
                                self.logger.debug(f"Cache clear failed: {e}")
                                cache_clear_counter = 0
                        
                        if total_size > 0 and current_size > 0:
                            progress = (current_size / total_size) * 100
                            current_mb = current_size / 1024 / 1024
                            
                            self._update_ota_state(
                                progress=round(progress, 1),
                                message=f'Downloading: {progress:.1f}% ({current_mb:.1f}/{total_mb:.1f} MB)'
                            )
                            
                            if int(current_mb / 10) > int(last_log_mb / 10):
                                self.logger.info(f"Download progress: {progress:.1f}% ({current_mb:.1f}/{total_mb:.1f} MB)")
                                last_log_mb = current_mb
                        elif current_size > 0:
                            current_mb = current_size / 1024 / 1024
                            self._update_ota_state(
                                progress=50,
                                message=f'Downloading: {current_mb:.1f} MB'
                            )
                            
                            if int(current_mb / 10) > int(last_log_mb / 10):
                                self.logger.info(f"Downloaded: {current_mb:.1f} MB")
                                last_log_mb = current_mb
                
                download_thread.join(timeout=10)
                
                if download_error[0]:
                    error_msg = f"curl failed: {download_error[0].stderr if download_error[0].stderr else str(download_error[0])}"
                    self.logger.error(error_msg)
                    
                    self._record_ota_failed(ota_id, error_msg)
                    self._update_ota_state(
                        ota_status='failed',
                        progress=100,
                        finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                        message='Download failed'
                    )
                    
                    if os.path.exists(download_path):
                        os.remove(download_path)
                    return False
                
                try:
                    subprocess.run(['sync'], timeout=5, check=False)
                    with open('/proc/sys/vm/drop_caches', 'w') as f:
                        f.write('1\n')
                    self.logger.info("Final cache clear after download")
                except Exception as e:
                    self.logger.debug(f"Final cache clear skipped: {e}")
                
                if not os.path.exists(download_path):
                    error_msg = "Download failed: file is missing"
                    self.logger.error(error_msg)
                    
                    self._record_ota_failed(ota_id, error_msg)
                    self._update_ota_state(
                        ota_status='failed',
                        progress=100,
                        finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                        message='Download failed'
                    )
                    return False
                
                final_size = os.path.getsize(download_path)
                if final_size == 0:
                    error_msg = "Download failed: file is empty"
                    self.logger.error(error_msg)
                    
                    self._record_ota_failed(ota_id, error_msg)
                    self._update_ota_state(
                        ota_status='failed',
                        progress=100,
                        finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                        message='Download failed'
                    )
                    
                    os.remove(download_path)
                    return False
                
                final_mb = final_size / 1024 / 1024
                self.logger.info(f"Firmware download completed: {final_mb:.2f} MB")
                self._update_ota_state(
                    progress=100,
                    message='Download completed, verifying MD5...'
                )

            except Exception as e:
                error_msg = f"Download error: {str(e)}"
                self.logger.error(error_msg)
                
                self._record_ota_failed(ota_id, error_msg)
                self._update_ota_state(
                    ota_status='failed',
                    progress=100,
                    finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                    message=error_msg
                )
                
                if os.path.exists(download_path):
                    os.remove(download_path)
                return False

            self.logger.info("Verifying MD5 checksum...")
            calculated_md5 = self._calculate_file_md5(download_path, show_progress=True)
            
            if calculated_md5.lower() != md5.lower():
                error_msg = f'MD5 mismatch! Expected: {md5}, Got: {calculated_md5}'
                self.logger.error(error_msg)
                
                self._record_ota_failed(ota_id, error_msg)
                self._update_ota_state(
                    ota_status='failed',
                    progress=100,
                    finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                    message='MD5 verification failed'
                )
                
                os.remove(download_path)
                return False
            
            self.logger.info("✓ MD5 verification passed")
            
            self._record_ota_installing(ota_id)
            self._update_ota_state(
                ota_status='install',
                progress=100,
                message='Starting installation...'
            )
            
            return self._perform_upgrade(download_path, version, ota_id)
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Download failed: {str(e)}"
            self.logger.error(error_msg)
            
            self._record_ota_failed(ota_id, error_msg)
            self._update_ota_state(
                ota_status='failed',
                progress=100,
                finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                message=error_msg
            )
            return False
            
        except Exception as e:
            error_msg = f"OTA update failed: {str(e)}"
            self.logger.error(error_msg)
            
            self._record_ota_failed(ota_id, error_msg)
            self._update_ota_state(
                ota_status='failed',
                progress=100,
                finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                message=error_msg
            )
            
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _perform_upgrade(self, download_path, version, ota_id):
        self.logger.info("Starting firmware upgrade...")
        
        self.logger.info(f"Updating OTA history to 'install' state before upgrade...")
        self._record_ota_installing(ota_id)
        
        try:
            with open(self.OTA_HISTORY_FILE, 'r') as f:
                history = json.load(f)
                saved_status = history.get('last_ota', {}).get('ota_status', '')
                if saved_status == 'install':
                    self.logger.info(f"✓ OTA history file confirmed: status='install'")
                else:
                    self.logger.error(f"✗ OTA history file status mismatch: {saved_status}")
        except Exception as e:
            self.logger.error(f"Failed to verify OTA history file: {e}")
        
        self._update_ota_state(
            ota_status='install',
            message='Installing firmware, please wait...'
        )
        
        try:
            import subprocess
            subprocess.run(['sync'], timeout=5)
            self.logger.info("Disk sync completed")
        except Exception as e:
            self.logger.warning(f"Disk sync failed: {e}")
        
        try:
            self.logger.info("Executing swupdate command...")
            
            cmd = [
                "swupdate",
                "-k", "/etc/swupdate-public.pem",
                "-H", "S420:1.0",
                "-G"
            ]
            
            self.logger.info(f"Command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

        except subprocess.TimeoutExpired:
            error_msg = "swupdate timeout (>10 minutes)"
            self.logger.error(error_msg)
            
            self._record_ota_failed(ota_id, error_msg)
            self._update_ota_state(
                ota_status='failed',
                progress=100,
                finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                message=error_msg
            )
            return False
            
        except Exception as e:
            error_msg = f"swupdate error: {str(e)}"
            self.logger.error(error_msg)
            
            self._record_ota_failed(ota_id, error_msg)
            self._update_ota_state(
                ota_status='failed',
                progress=100,
                finish_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                message=error_msg
            )
            return False

    def _calculate_file_md5(self, filepath, show_progress=False):
        file_size = os.path.getsize(filepath)
        file_mb = file_size / 1024 / 1024
        
        if show_progress:
            self.logger.info(f"Calculating MD5 for {file_mb:.2f} MB file...")
        
        try:
            if show_progress:
                import threading
                
                md5_complete = threading.Event()
                md5_result = [None]
                md5_error = [None]
                
                def calculate_md5():
                    try:
                        result = subprocess.run(
                            ['md5sum', filepath],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=600
                        )
                        md5_hash = result.stdout.split()[0]
                        md5_result[0] = md5_hash
                    except Exception as e:
                        md5_error[0] = e
                    finally:
                        md5_complete.set()
                
                md5_thread = threading.Thread(target=calculate_md5)
                md5_thread.start()
                
                start_time = time.time()
                last_log_time = start_time
                
                while not md5_complete.is_set():
                    time.sleep(10)
                    
                    elapsed = time.time() - start_time
                    
                    if time.time() - last_log_time >= 10:
                        self.logger.info(f"MD5 verification in progress... ({elapsed:.0f}s elapsed)")
                        last_log_time = time.time()
                    
                    try:
                        with open('/proc/sys/vm/drop_caches', 'w') as f:
                            f.write('1\n')
                    except:
                        pass
                
                md5_thread.join(timeout=5)
                
                if md5_error[0]:
                    raise md5_error[0]
                
                if md5_result[0]:
                    self.logger.info(f"MD5 calculation completed: {md5_result[0]}")
                    return md5_result[0]
                else:
                    raise Exception("MD5 calculation failed: no result")
            
            else:
                result = subprocess.run(
                    ['md5sum', filepath],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=600
                )
                md5_hash = result.stdout.split()[0]
                return md5_hash
        
        except subprocess.TimeoutExpired:
            self.logger.error("MD5 calculation timeout")
            raise Exception("MD5 calculation timeout")
        
        except Exception as e:
            self.logger.error(f"Error calculating MD5: {e}")
            raise

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
