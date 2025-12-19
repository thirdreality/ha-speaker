# maintainer: guoping.liu@3reality.com

import os
import logging
import threading
import subprocess
import time
import re
import json

DEVICE_INFO_FILE = "/data/conf/device.json"

def get_device_info():
    device_info = {}
    if not os.path.exists(DEVICE_INFO_FILE):
        logging.warning(f"Device file not found: {DEVICE_INFO_FILE}")
        return device_info

    try:
        with open(DEVICE_INFO_FILE, 'r') as f:
            data = json.load(f)
            if 'device' in data:
                device = data['device']
                device_info['deviceModel'] = device.get('deviceModel', '')
                device_info['modelID'] = device.get('modelID', '')
                device_info['firmwareVersion'] = device.get('firmwareVersion', '')
                device_info['macAddress'] = device.get('macAddress', '')
                device_info['name'] = device.get('name', '')
            if 'network' in data:
                network = data['network']
                device_info['status'] = network.get('status', '')
                device_info['ssid'] = network.get('ssid', '')
                device_info['ip'] = network.get('ip', '')
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"Error reading {DEVICE_INFO_FILE}: {e}")
        
    return device_info

class SystemInfo:
    def __init__(self):
        device_info = get_device_info()

        self.modelId = device_info.get("MODLE", "3RAB01090D")
        self.name = "3RSPK-UNKNOWN"

class ProcedureInfo:
    def __init__(self):
        self.tag = ""
        self.finished = False
        self.success = True
        self.percent= 0

class SystemInfoUpdater:
    def __init__(self, supervisor=None):
        self.supervisor = supervisor
        self.logger = logging.getLogger("Supervisor")
        self.sys_info_thread = None
        
        # Initialize device name immediately
        self._initialize_device_name()
    
    def _initialize_device_name(self):
        """Initialize device name with retry mechanism"""
        if not hasattr(self.supervisor, 'system_info'):
            self.logger.error("Supervisor does not have system_info attribute")
            return
            
        device_name = self._generate_device_name_with_retry()
        self.supervisor.system_info.name = device_name
        self.logger.info(f"Device name initialized: {device_name}")
    
    def _generate_device_name_with_retry(self, max_retries=3, retry_delay=0.5):
        """Generate device name with retry mechanism for MAC address retrieval"""
        # from .utils.wifi_utils import get_wlan0_mac_for_localname
        import time
        
        for attempt in range(max_retries):
            try:
                # mac_str = get_wlan0_mac_for_localname()
                mac_str = "TESTTESTTEST"
                if mac_str:
                    # Use same algorithm as btgatt-server.c and LinuxBoxAdvertisement
                    device_name = f"3RHUB-{mac_str[-8:]}"  # Use only last 8 characters of MAC address
                    self.logger.info(f"Generated device name from MAC (attempt {attempt + 1}): {device_name}")
                    return device_name
                else:
                    self.logger.warning(f"Failed to get MAC address (attempt {attempt + 1}/{max_retries})")
                    
            except Exception as e:
                self.logger.warning(f"Error getting MAC address (attempt {attempt + 1}/{max_retries}): {e}")
            
            # Wait before retry (except for last attempt)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        
        # Fallback: try to read /etc/machine-id if all MAC retrieval attempts failed
        try:
            with open('/etc/machine-id', 'r') as f:
                machine_id = f.read().strip()
                if machine_id and len(machine_id) >= 8:
                    # Use last 8 characters and convert to uppercase
                    machine_suffix = machine_id[-8:].upper()
                    fallback_name = f"3RHUB-{machine_suffix}"
                    self.logger.info(f"Using machine-id based fallback name: {fallback_name}")
                    return fallback_name
        except Exception as e:
            self.logger.warning(f"Failed to read /etc/machine-id: {e}")
        
        # Final fallback if machine-id is also unavailable
        final_fallback = "3RHUB-EMB"
        self.logger.warning(f"All attempts failed, using final fallback: {final_fallback}")
        return final_fallback
    
    def _check_auto_wifi_provision_needed(self):
        """Check if auto WiFi provision is needed after system startup is complete"""
        try:
            if not self.supervisor:
                return
                
            self.logger.info("System startup complete, checking if auto WiFi provision is needed...")
            
            # Trigger auto WiFi provision check
            
        except Exception as e:
            self.logger.error(f"Error checking auto WiFi provision: {e}")
    
    def system_info_update_task(self):
        """System information update task"""
        self.logger.info("System information update task started")
        try:
            if self.supervisor:
                # 触发自动 WiFi 配网检查
                self._check_auto_wifi_provision_needed()
        except Exception as e:
            self.logger.error(f"Error in system info update task: {e}")

    def start(self):
        """Start thread to execute system information update task"""
        if self.sys_info_thread and self.sys_info_thread.is_alive():
            self.logger.info("System information update already running")
            return
            
        self.sys_info_thread = threading.Thread(target=self.system_info_update_task, daemon=True)
        self.sys_info_thread.start()
        self.logger.info("System information update started")
        
    def stop(self):
        """Use supervisor.running to close, here for show"""
        self.logger.info("System Information stopped")


