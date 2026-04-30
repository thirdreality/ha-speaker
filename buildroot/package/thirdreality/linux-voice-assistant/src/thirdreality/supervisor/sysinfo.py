# maintainer: guoping.liu@3reality.com

import json
import logging
import os
import threading

DEVICE_INFO_FILE = "/data/conf/device.json"
DEFAULT_MODEL_ID = "3RAB01090D"
DEFAULT_DEVICE_NAME = "3RSPK-DEFAULT"

LOGGER = logging.getLogger("Supervisor")
_DEVICE_INFO_CACHE = {}
_DEVICE_INFO_MTIME_NS = None
_DEVICE_INFO_LOCK = threading.Lock()

def get_device_info():
    global _DEVICE_INFO_CACHE
    global _DEVICE_INFO_MTIME_NS

    try:
        stat_result = os.stat(DEVICE_INFO_FILE)
    except OSError as e:
        LOGGER.warning(f"Device file not found: {DEVICE_INFO_FILE} ({e})")
        with _DEVICE_INFO_LOCK:
            _DEVICE_INFO_CACHE = {}
            _DEVICE_INFO_MTIME_NS = None
        return {}

    with _DEVICE_INFO_LOCK:
        if _DEVICE_INFO_MTIME_NS == stat_result.st_mtime_ns:
            return _DEVICE_INFO_CACHE.copy()

        device_info = {}
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
            LOGGER.error(f"Error reading {DEVICE_INFO_FILE}: {e}")
            return _DEVICE_INFO_CACHE.copy()

        _DEVICE_INFO_CACHE = device_info
        _DEVICE_INFO_MTIME_NS = stat_result.st_mtime_ns
        return device_info.copy()


def _normalize_mac(raw_mac):
    return ''.join(ch for ch in str(raw_mac).strip().upper() if ch.isalnum())[:12]


def get_primary_mac_address():
    device_info = get_device_info()
    return _normalize_mac(device_info.get("macAddress", ""))


def build_device_name(device_info=None):
    if device_info is None:
        device_info = get_device_info()

    configured_name = str(device_info.get("name", "")).strip()
    if configured_name:
        return configured_name

    normalized_mac = _normalize_mac(device_info.get("macAddress", ""))
    if normalized_mac:
        return f"3RSPK-{normalized_mac}"
    return DEFAULT_DEVICE_NAME


def get_preferred_device_name():
    return build_device_name(get_device_info())

class SystemInfo:
    def __init__(self):
        device_info = get_device_info()

        self.modelId = device_info.get("modelID", DEFAULT_MODEL_ID)
        self.name = build_device_name(device_info)

class SystemInfoUpdater:
    def __init__(self, supervisor=None):
        self.supervisor = supervisor
        self.logger = LOGGER
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

    def _generate_device_name_with_retry(self):
        configured_name = get_preferred_device_name()
        if configured_name and configured_name != DEFAULT_DEVICE_NAME:
            self.logger.info(f"Using device name from {DEVICE_INFO_FILE}: {configured_name}")
            return configured_name

        mac_str = get_primary_mac_address()
        if mac_str:
            device_name = f"3RSPK-{mac_str}"
            self.logger.info(f"Generated device name from {DEVICE_INFO_FILE}: {device_name}")
            return device_name

        self.logger.warning(f"Device info missing name/macAddress, using fallback: {DEFAULT_DEVICE_NAME}")
        return DEFAULT_DEVICE_NAME

    def system_info_update_task(self):
        """System information update task"""
        self.logger.info("System information update task started")
        return

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
