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
                    elif path.startswith("/api/service/info"):
                        # Support two ways to get service name:
                        # 1. By path: /api/service/info/<service_name>
                        # 2. By query param: /api/service/info?service=<service_name>
                        path_parts = path.split('/')
                        if len(path_parts) > 4 and path_parts[4]:  # By path
                            service_name = path_parts[4]
                            self._logger.info(f"Getting service info for {service_name} (via path)")
                            self._handle_service_info(service_name)
                        else:  # Try by query param
                            service_name = query_params.get('service', [None])[0]
                            if service_name:
                                self._logger.info(f"Getting service info for {service_name} (via query param)")
                                self._handle_service_info(service_name)
                            else:
                                # No service name provided, return info for all services
                                self._logger.info("No service name provided, returning info for all services")
                                self._handle_service_info(None)
                    elif path == "/api/setting/info":
                        self._handle_setting_info()
                    elif path == "/api/health" or path == "/health":
                        # Handle health check request
                        self._handle_health_check()
                    elif path.startswith('/api/task/info'):
                        query_components = parse_qs(urlparse(self.path).query)
                        task_type = query_components.get("task", [None])[0]

                        if not task_type:
                            self._set_headers(status_code=400)
                            self.wfile.write(json.dumps({"success": False, "error": "Missing 'task' query parameter."}).encode())
                            return

                        if task_type not in ["zigbee", "thread", "setting"]:
                            self._set_headers(status_code=400)
                            self.wfile.write(json.dumps({"success": False, "error": f"Invalid task type: {task_type}"}).encode())
                            return
                        
                        task_info = self._supervisor.task_manager.get_task_info(task_type)
                        self._set_headers()
                        self.wfile.write(json.dumps({"success": True, "task": task_type, "data": task_info}).encode())
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

            def _handle_service_info(self, service_name=None): 
                """Handle service info request, can specify a particular service"""
                # Define service config
                service_configs = {
                    "homeassistant_core": {
                        "name": "Home Assistant",
                        "services": [
                            "home-assistant.service",
                            "matter-server.service",
                            "otbr-agent.service",
                            "mosquitto.service",
                            "zigbee2mqtt.service"
                        ]
                    },
                    "openhab": {
                        "name": "openhab",
                        "services": [
                            "openhab.service"
                        ]
                    },
                }
                
                # If a service name is specified but does not exist, return 404
                if service_name and service_name not in service_configs:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Service '{service_name}' not found"}).encode())
                    return
                
                # Determine which services to process
                services_to_process = [service_name] if service_name else service_configs.keys()
                
                # Result dict
                result = {}
                
                # Process each service
                for service_key in services_to_process:
                    config = service_configs[service_key]
                    service_result = {
                        "name": config["name"]
                    }
                    
                    # Check service status
                    services_status = []
                    for service in config["services"]:
                        is_running = util.is_service_running(service)
                        is_enabled = util.is_service_enabled(service)
                        service_info = {
                            "name": service,
                            "running": is_running,
                            "enabled": is_enabled
                        }
                        services_status.append(service_info)
                    
                    service_result["service"] = services_status
                    result[service_key] = service_result
                
                self._set_headers()
                self.wfile.write(json.dumps(result).encode())

            def _handle_channel_info(self, query_params):
                """Handle channel info request, return Zigbee and Thread channel information"""
                try:
                    from supervisor.channel_manager import ChannelManager
                    
                    channel_manager = ChannelManager()
                    
                    # Check if specific channel type is requested
                    channel_type = query_params.get('type', [None])[0]
                    
                    if channel_type:
                        # Return specific channel type
                        if channel_type not in ['zigbee', 'thread']:
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": f"Invalid channel type: {channel_type}. Must be 'zigbee' or 'thread'"}).encode())
                            return
                        
                        result = channel_manager.get_channel_by_type(channel_type)
                    else:
                        # Return all channels
                        result = channel_manager.get_all_channels()
                    
                    self._set_headers()
                    self.wfile.write(json.dumps(result).encode())
                    
                except Exception as e:
                    self._logger.error(f"Error getting channel info: {e}")
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            
            def _handle_health_check(self):
                """Handle health check request, return server status info"""
                from .sysinfo import get_device_info
                # Calculate server uptime
                uptime_seconds = time.time() - self._supervisor.http_server.start_time
                uptime_str = self._format_uptime(uptime_seconds)
                
                # Get system resource info
                mem_info = self._get_memory_info()
                cpu_load = self._get_cpu_load()
                disk_usage = self._get_disk_usage()
                
                # Assemble health status response
                health_status = {
                    "status": "ok",
                    "version": get_device_info().get("firmwareVersion", ""),
                    "uptime": uptime_str,
                    "uptime_seconds": int(uptime_seconds),
                    "timestamp": int(time.time()),
                    "resources": {
                        "memory": mem_info,
                        "cpu": cpu_load,
                        "disk": disk_usage
                    }
                }
                
                # Return health status response
                self._set_headers()
                self.wfile.write(json.dumps(health_status).encode())
            
            def _format_uptime(self, seconds):
                """Format uptime string"""
                days, remainder = divmod(int(seconds), 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                if days > 0:
                    return f"{days}d {hours}h {minutes}m {seconds}s"
                elif hours > 0:
                    return f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    return f"{minutes}m {seconds}s"
                else:
                    return f"{seconds}s"
            
            def _get_memory_info(self):
                """Get memory usage info"""
                try:
                    with open('/proc/meminfo', 'r') as f:
                        mem_info = {}
                        for line in f:
                            if 'MemTotal' in line or 'MemFree' in line or 'MemAvailable' in line:
                                key, value = line.split(':', 1)
                                value = value.strip().split()[0]  # Remove unit, keep only number
                                mem_info[key.strip()] = int(value)
                        
                        # Calculate memory usage percent
                        if 'MemTotal' in mem_info and 'MemAvailable' in mem_info:
                            used = mem_info['MemTotal'] - mem_info['MemAvailable']
                            mem_info['UsedPercent'] = round(used / mem_info['MemTotal'] * 100, 1)
                        
                        return mem_info
                except Exception as e:
                    self._logger.error(f"Error getting memory info: {e}")
                    return {"error": str(e)}
            
            def _get_cpu_load(self):
                """Get CPU load"""
                try:
                    with open('/proc/loadavg', 'r') as f:
                        load = f.read().strip().split()
                        return {
                            "load_1min": float(load[0]),
                            "load_5min": float(load[1]),
                            "load_15min": float(load[2])
                        }
                except Exception as e:
                    self._logger.error(f"Error getting CPU load: {e}")
                    return {"error": str(e)}
            
            def _get_disk_usage(self):
                """Get disk usage info"""
                try:
                    # Use df command to get disk usage
                    process = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, check=False)
                    if process.returncode == 0:
                        lines = process.stdout.strip().split('\n')
                        if len(lines) >= 2:  # At least header and data line
                            parts = lines[1].split()
                            if len(parts) >= 5:
                                return {
                                    "filesystem": parts[0],
                                    "size": parts[1],
                                    "used": parts[2],
                                    "available": parts[3],
                                    "use_percent": parts[4]
                                }
                    
                    # If above method fails, try statvfs
                    import os
                    st = os.statvfs('/')
                    total = st.f_blocks * st.f_frsize
                    free = st.f_bfree * st.f_frsize
                    used = total - free
                    return {
                        "total_bytes": total,
                        "used_bytes": used,
                        "free_bytes": free,
                        "use_percent": round(used / total * 100, 1)
                    }
                except Exception as e:
                    self._logger.error(f"Error getting disk usage: {e}")
                    return {"error": str(e)}                
            
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

                    elif command == "stop_wifi_provision":
                        # Directly call supervisor stop Wi-Fi provisioning method
                        self._logger.info("HTTP Server: Received stop_wifi_provision command.")
                        success = self._supervisor.finish_wifi_provision() # This method already runs in a thread
                        self._set_headers()
                        # The success here indicates the command was received and initiated, 
                        # not necessarily that Wi-Fi provisioning has fully stopped yet.
                        self.wfile.write(json.dumps({"success": success, "message": "Wi-Fi provisioning stop initiated."}).encode())

                except Exception as e:
                    self._logger.error(f"Error processing system command: {str(e)}")
                    self._send_error(f"Error: {str(e)}")
                    # Add detailed exception trace

            def _handle_service_command(self, post_data):
                """Handle service control command, use centralized signature verification logic"""
                try:
                    self._logger.info(f"Processing service command with data: {post_data}")
                    # Parse POST params and signature
                    params, signature, is_valid = self._parse_post_data(post_data)
                    # Validate action param
                    if 'action' not in params:
                        self._send_error("action is required")
                        return
                    # Validate signature
                    if not signature:
                        self._send_error("Signature is required")
                        return
                    if not is_valid:
                        self._logger.warning("Security verification failed: Invalid signature")
                        self.send_response(401)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Unauthorized: Invalid signature"}).encode())
                        return
                    action = params['action']
                    service_name = params.get('service')

                    # If params has no service, try to parse from param_json
                    if not service_name and 'param' in params:
                        try:
                            param_data_base64 = params['param']
                            param_data_url_decoded = urllib.parse.unquote(param_data_base64)
                            param_data_json = base64.b64decode(param_data_url_decoded).decode()
                            self._logger.info(f"param_data (decoded): {param_data_json}")
                            param_dict = json.loads(param_data_json)
                            service_name = param_dict.get('service')
                            self._logger.info(f"service (from param_data): {service_name}")
                        except Exception as e:
                            self._logger.error(f"Failed to parse param_data for service: {e}")

                    self._logger.info(f"action: {action}")
                    self._logger.info(f"service: {service_name}")

                    if not service_name:
                        self._send_error("Service name is required")
                        return
                    result = {"success": False}
                    try:
                        if action == "enable":
                            self._logger.info(f"Enabling service: {service_name}")
                            process = subprocess.run(["systemctl", "enable", service_name], capture_output=True, text=True)
                            result = {"success": process.returncode == 0, "stdout": process.stdout, "stderr": process.stderr}
                        elif action == "disable":
                            self._logger.info(f"Disabling service: {service_name}")
                            process = subprocess.run(["systemctl", "disable", service_name], capture_output=True, text=True)
                            result = {"success": process.returncode == 0, "stdout": process.stdout, "stderr": process.stderr}
                        elif action == "start":
                            self._logger.info(f"Starting service: {service_name}")
                            process = subprocess.run(["systemctl", "start", service_name], capture_output=True, text=True)
                            result = {"success": process.returncode == 0, "stdout": process.stdout, "stderr": process.stderr}
                        elif action == "stop":
                            self._logger.info(f"Stopping service: {service_name}")
                            process = subprocess.run(["systemctl", "stop", service_name], capture_output=True, text=True)
                            result = {"success": process.returncode == 0, "stdout": process.stdout, "stderr": process.stderr}
                        else:
                            result = {"success": False, "error": f"Unknown action: {action}"}
                        self._set_headers()
                        self.wfile.write(json.dumps(result).encode())
                    except Exception as e:
                        self._logger.error(f"Error executing systemctl command: {e}")
                        self._set_headers()
                        self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
                except Exception as e:
                    self._logger.error(f"Error in _handle_service_command: {str(e)}")
                    self._set_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())


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
