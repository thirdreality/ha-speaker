# maintainer: guoping.liu@3reality.com

"""
HTTP Server for LinuxBox Finder that mirrors the functionality of the BLE GATT server.
This server runs when WiFi is connected and provides the same APIs as the BLE service.
"""

import json
import hashlib
import time
import base64
import urllib.parse
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import signal
import sys
import logging
import mimetypes
import threading
import glob
from concurrent.futures import ThreadPoolExecutor

from .utils import util

class SupervisorHTTPServer:
    """HTTP Server that integrates with Supervisor for shared state"""
    
    # Centralized management of API secret keys and security configuration
    API_SECRET_KEY = "ThirdReality"  # Ideally should be loaded from environment variable or config file
    MAX_RETRIES = 3  # Maximum number of retries for server errors
    RETRY_DELAY = 5  # Retry delay (seconds)
    
    def __init__(self, supervisor, port=8086):
        self.logger = logging.getLogger("Supervisor")
        self.supervisor = supervisor
        self.port = port
        self.server = None
        self.running = threading.Event()
        self.thread_pool = ThreadPoolExecutor(max_workers=5)  # Create thread pool for file downloads
        self.start_time = time.time()  # Record start time for health check
    
    def start(self):
        """Start HTTP server"""
        if self.server:
            self.logger.warning("HTTP Server already running")
            return
        
        try:
            # Create a handler class with supervisor reference
            handler = self._create_handler()
            
            # Create and start server
            self.server = HTTPServer(("0.0.0.0", self.port), handler)
            self.running.set()
            
            # Run server in a separate thread
            self._run_server()
            
            self.logger.info(f"HTTP Server starting on port {self.port}")
            
            # If supervisor has stored IP address, log the URL
            if hasattr(self.supervisor, 'wifi_info') and self.supervisor.wifi_info.get('ip_address'):
                ip = self.supervisor.wifi_info.get('ip_address')
                self.logger.info(f"HTTP Server accessible at: http://{ip}:{self.port}/")
        
        except Exception as e:
            self.logger.error(f"Failed to start HTTP Server: {e}")
    
    def stop(self):
        """Stop HTTP server"""
        if self.server:
            self.running.clear()
            self.server.shutdown()
            self.server = None
            self.thread_pool.shutdown(wait=False)  # Shutdown thread pool
            self.logger.info("HTTP Server stopped")
    
    @util.threaded
    def _run_server(self):
        """Run HTTP server in a separate thread with retry mechanism"""
        retry_count = 0
        
        while self.running.is_set():
            try:
                self.server.serve_forever()
            except Exception as e:
                if self.running.is_set():  # Only log error if still supposed to run
                    retry_count += 1
                    if retry_count > self.MAX_RETRIES:
                        self.logger.error(f"HTTP Server failed after {self.MAX_RETRIES} retries: {e}")
                        self.running.clear()  # Stop server
                        # Notify supervisor HTTP server failure
                        if hasattr(self.supervisor, 'on_http_server_failure'):
                            self.supervisor.on_http_server_failure(e)
                        break
                    
                    self.logger.warning(f"HTTP Server error (retry {retry_count}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY)  # Use configured delay
    
    def _create_handler(self):
        """Create an HTTP request handler class with supervisor access"""
        supervisor = self.supervisor
        logger = self.logger
        
        class LinuxBoxHTTPHandler(BaseHTTPRequestHandler):
            """HTTP request handler"""
            
            # Store reference to supervisor
            _supervisor = supervisor
            _logger = logger
            
            # Override log method to use our logger
            def log_message(self, format, *args):
                self._logger.info(f"{self.client_address[0]} - {format % args}")
            
            def _set_headers(self, content_type="application/json", status_code=200):
                self.send_response(status_code)
                self.send_header('Content-type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')  # Enable CORS
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
            
            def do_OPTIONS(self):
                """Handle CORS preflight request"""
                self._set_headers()
            
            def do_GET(self):
                """Handle GET request"""
                try:
                    # Parse URL and query parameters
                    parsed_url = urllib.parse.urlparse(self.path)
                    path = parsed_url.path
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    
                    self._logger.info(f"GET request: {path}")
                    
                    # Handle different API endpoints
                    if path == "/api/wifi/status":
                        self._handle_wifi_status()
                    elif path == "/api/system/info":
                        self._handle_system_info()
                    elif path == "/api/ota/status":
                        self._handle_ota_status()
                    elif path == "/api/ota/history":
                        self._handle_ota_history()
                    else:
                        # Return 404 Not Found
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"Not Found")
                        
                except Exception as e:
                    self._logger.error(f"Error handling GET request: {str(e)}")
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Internal Server Error"}).encode())
            
            def do_POST(self):
                """Handle POST request"""
                parsed_path = urlparse(self.path)
                path = parsed_path.path
                
                # Get content length
                content_length = int(self.headers['Content-Length']) if 'Content-Length' in self.headers else 0
                
                # Read request body
                post_data = self.rfile.read(content_length).decode('utf-8')

                self._logger.info(f"POST data: {post_data}")
                
                # Check Content-Type
                content_type = self.headers.get('Content-Type', '')
                self._logger.info(f"Content-Type: {content_type}")
                                
                # System command feature (write operation)
                if path == "/api/system/command":
                    self._handle_sys_command(post_data)
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not found"}).encode())
            
            def _handle_wifi_status(self):
                """Handle GET /api/wifi/status - Read from /data/conf/device.json"""
                from .sysinfo import get_device_info
                
                # Default result
                result = {
                    "connected": False,
                    "ssid": "",
                    "ip_address": "",
                    "mac_address": "",
                    "message": ""
                }
                
                # Read from device.json using sysinfo module
                device_info = get_device_info()
                if device_info:
                    result["ssid"] = device_info.get("ssid", "")
                    result["ip_address"] = device_info.get("ip", "")
                    result["mac_address"] = device_info.get("macAddress", "")
                    result["message"] = ""  # Default empty message
                    
                    # connected is true if network.status is "connected", otherwise false
                    network_status = device_info.get("status", "")
                    result["connected"] = (network_status == "connected")
                else:
                    result["message"] = "Device configuration file not found or invalid"
                
                self._set_headers()
                self.wfile.write(json.dumps(result).encode())
            
            def _handle_system_info(self):
                """Handle GET /api/system/info - Read from /data/conf/device.json"""
                from .sysinfo import get_device_info
                
                # Default result
                result = {
                    "Device Model": "ThirdReality HA Speaker",
                    "Device Name": "",
                    "WIFI Connected": False,
                    "SSID": "",
                    "Ip Address": "",
                    "Mac Address": "",
                    "Version": ""
                }
                
                # Read from device.json using sysinfo module
                device_info = get_device_info()
                if device_info:
                    # Map fields according to requirements
                    result["Device Model"] = "ThirdReality HA Speaker"  # Fixed value
                    result["Device Name"] = device_info.get("name", "")
                    result["Version"] = device_info.get("firmwareVersion", "")
                    result["Mac Address"] = device_info.get("macAddress", "")
                    
                    result["SSID"] = device_info.get("ssid", "")
                    result["Ip Address"] = device_info.get("ip", "")
                    
                    # WIFI Connected is true if network.status is "connected", otherwise false
                    network_status = device_info.get("status", "")
                    result["WIFI Connected"] = (network_status == "connected")
                
                self._set_headers()
                self.wfile.write(json.dumps(result).encode())

            def _handle_ota_status(self):
                try:
                    ota_state = self._supervisor.get_ota_state()
                    
                    self._set_headers()
                    self.wfile.write(json.dumps(ota_state).encode())
                    
                except Exception as e:
                    self._logger.error(f"Error getting OTA status: {e}")
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "otaing": False,
                        "ota_status": "error",
                        "message": str(e)
                    }).encode())

            def _handle_ota_history(self):
                try:
                    history = self._supervisor.get_ota_history()
                    
                    self._set_headers()
                    self.wfile.write(json.dumps(history).encode())

                except Exception as e:
                    self._logger.error(f"Error getting OTA history: {e}")
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            def _handle_sys_command(self, post_data):
                """Handle system command request, use shared signature verification method"""
                try:
                    self._logger.info(f"Processing system command with data: {post_data}")
                    
                    # Use shared method to parse and verify params
                    params, signature, is_valid = self._parse_post_data(post_data)
                    
                    # Must have command param
                    if 'command' not in params:
                        self._send_error("Command is required")
                        return
                    
                    # Must have signature
                    if not signature:
                        self._send_error("Signature is required")
                        return
                    
                    # Verify signature validity
                    if not is_valid:
                        self._logger.warning("Security verification failed: Invalid signature")
                        self.send_response(401)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Unauthorized: Invalid signature"}).encode())
                        return
                    
                    # Signature verified, process command
                    command = params.get("command", "")
                    self._logger.info(f"Processing validated command: {command}")

                    action = params.get("action", "")

                    param_data_base64 = params.get("param", "")
                    param_dict = {}
                    if param_data_base64:
                        try:
                            param_data_url_decoded = urllib.parse.unquote(param_data_base64)
                            param_data_json = base64.b64decode(param_data_url_decoded).decode()
                            self._logger.info(f"param_data (decoded): {param_data_json}")
                            param_dict = json.loads(param_data_json)
                            action = param_dict.get('action')
                        except Exception as e:
                            self._logger.error(f"param decode failed: {e}")
                            self._set_headers()
                            self.wfile.write(json.dumps({"success": False, "error": "param decode error"}).encode())
                            return

                    # Process system command
                    if command == "reboot":
                        # Directly call supervisor reboot method
                        self._set_headers()
                        self.wfile.write(json.dumps({"success": True}).encode())
                        threading.Timer(3.0, self._supervisor.perform_reboot).start()
                    
                    elif command == "factory_reset":
                        # Directly call supervisor factory reset method
                        self._set_headers()
                        self.wfile.write(json.dumps({"success": True}).encode())
                        threading.Timer(3.0, self._supervisor.perform_factory_reset).start()

                    elif command == "ota":
                        if not param_dict:
                            self._set_headers(status_code=400)
                            self.wfile.write(json.dumps({
                                "success": False, 
                                "error": "Missing OTA parameters"
                            }).encode())
                            return
                        
                        required_fields = ['url', 'version', 'md5']
                        for field in required_fields:
                            if field not in param_dict:
                                self._set_headers(status_code=400)
                                self.wfile.write(json.dumps({
                                    "success": False, 
                                    "error": f"Missing required field: {field}"
                                }).encode())
                                return
                        
                        import uuid
                        from datetime import datetime
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        unique_id = str(uuid.uuid4())[:8]
                        ota_id = f"ota_{timestamp}_{unique_id}"
                        
                        self._set_headers()
                        self.wfile.write(json.dumps({
                            "success": True,
                            "ota_id": ota_id
                        }).encode())
                        
                        threading.Timer(1.0, lambda: self._supervisor.perform_ota_update(
                            url=param_dict['url'],
                            version=param_dict['version'],
                            md5=param_dict['md5'],
                            ota_id=ota_id
                        )).start()

                except Exception as e:
                    self._logger.error(f"Error processing system command: {str(e)}")
                    self._send_error(f"Error: {str(e)}")

            def _verify_signature(self, params, signature):
                """Verify request signature
                Args:
                    params: parameter dict
                    signature: signature provided by request
                Returns:
                    bool: whether signature is valid
                """
                try:
                    # Get API secret key
                    secret_key = self._supervisor.http_server.API_SECRET_KEY
                                
                    # Sort keys and reassemble param string
                    sorted_keys = sorted(params.keys())
                    param_string = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
                                
                    # Add security key and calculate MD5
                    security_string = f"{param_string}&{secret_key}"
                    calculated_md5 = hashlib.md5(security_string.encode()).hexdigest()
                                
                    self._logger.debug(f"Signature verification: expected={calculated_md5}, received={signature}")
                                
                    return calculated_md5 == signature
                except Exception as e:
                    self._logger.error(f"Error verifying signature: {e}")
                    return False
            
            def _parse_post_data(self, post_data):
                """Parse POST data and verify signature
                Args:
                    post_data: POST request data
                Returns:
                    tuple: (params, signature, is_valid)
                """
                params = {}
                signature = None
                    
                # Split params by &
                param_pairs = post_data.split('&')
                for pair in param_pairs:
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        if key == '_sig':
                            signature = value
                        else:
                            params[key] = value
                    
                # Verify signature
                if not signature:
                    return params, signature, False
                    
                is_valid = self._verify_signature(params, signature)
                return params, signature, is_valid
                    
            def _send_error(self, message):
                """Send error response"""
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": message}).encode())
                    
        return LinuxBoxHTTPHandler

def signal_handler(signum, frame):
    """Handle termination signal"""
    logging.getLogger("Supervisor").info(f"Received signal {signum}, exiting HTTP server gracefully...")
    http_server.stop()
    sys.exit(0)

if __name__ == "__main__":
    # Test server
    from supervisor import Supervisor
    supervisor = Supervisor()
    supervisor.init()
    
    # Define signal handler, for clean exit on termination signal
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    http_server = SupervisorHTTPServer(supervisor)
    http_server.start()
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        http_server.stop()
        # supervisor.cleanup()
        print("HTTP server stopped")
