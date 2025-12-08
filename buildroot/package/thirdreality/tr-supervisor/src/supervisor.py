#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import signal
import json
import sys
import threading
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .utils import util
from .http_server import SupervisorHTTPServer  
from .sysinfo import SystemInfoUpdater, SystemInfo
from .zero_manager import ZeroconfManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/var/log/supervisor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Supervisor")

class Supervisor:
    _worker_mode="homeassistant-core"

    def __init__(self):

        self.state_lock = threading.Lock()
        self.running = threading.Event()
        self.running.set()
        self.stop_event = threading.Event()
        
        self.system_info = SystemInfo()

        self.http_server = None

        self.sysinfo_update = SystemInfoUpdater(self)
        
        # boot up time
        self.start_time = time.time()

        # Zeroconf manager
        self.zeroconf_manager = ZeroconfManager(
            service_type="_linuxbox._tcp.local.",
            service_name_template="HUB-{mac}._linuxbox._tcp.local.",
            service_port=8086,
            properties={"version": "1.0.0", "build": "1.0.0"}
        )
        
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

    @util.threaded
    def perform_wifi_provision(self, progress_callback=None, complete_callback=None):
        """Execute WiFi provisioning"""
        logging.info("Initiating wifi provision...")
        try:
            # Start GATT provisioning mode
            if not self.gatt_manager.start_provisioning_mode():
                raise Exception("Failed to start GATT provisioning mode")
                
            if progress_callback:
                progress_callback(50, "WiFi provision GATT server started...")
                
            # Here you can add other provisioning logic
            
            if complete_callback:
                complete_callback(True, "WiFi provision mode activated")
        except Exception as e:
            logging.error(f"WiFi provision failed: {e}")
            if complete_callback:
                complete_callback(False, str(e))

    @util.threaded
    def finish_wifi_provision(self):
        """Finish WiFi provisioning"""
        logging.info("Finishing wifi provision...")
        self.gatt_manager.stop_provisioning_mode()

    def _signal_handler(self, sig, frame):
        logging.info("Signal received, stopping...")
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        self.running.clear()

        # Stop Zeroconf service
        if hasattr(self, 'zeroconf_manager') and self.zeroconf_manager:
            try:
                self.zeroconf_manager.stop()
                logger.info("Zeroconf service stopped during cleanup")
            except Exception as e:
                logger.warning(f"Failed to stop Zeroconf during cleanup: {e}")

        # Stop HTTP server
        self._stop_http_server()

    def run(self):
        """Main run function"""
        logger.info("Starting supervisor...")

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._start_http_server()

        self.sysinfo_update.start()

        # 主循环：保持程序运行直到收到退出信号
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
