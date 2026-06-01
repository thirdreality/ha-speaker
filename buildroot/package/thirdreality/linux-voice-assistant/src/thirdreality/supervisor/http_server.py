# maintainer: guoping.liu@3reality.com

"""Minimal HTTP server for tr-supervisor."""

import base64
import hashlib
import hmac
import json
import logging
import socket
import threading
import urllib.parse
from typing import Dict, Tuple


class SupervisorHTTPServer:
    API_SECRET_KEY = "ThirdReality"
    MAX_HEADER_SIZE = 16 * 1024
    MAX_BODY_SIZE = 64 * 1024

    def __init__(self, supervisor, port=8086):
        self.logger = logging.getLogger("Supervisor")
        self.supervisor = supervisor
        self.port = port
        self.running = threading.Event()
        self.server_thread = None
        self.server_socket = None

    def start(self):
        if self.server_socket:
            self.logger.warning("HTTP Server already running")
            return

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", self.port))
        server_socket.listen(8)
        server_socket.settimeout(1.0)

        self.server_socket = server_socket
        self.running.set()
        self.server_thread = threading.Thread(target=self._serve_loop, daemon=True)
        self.server_thread.start()
        self.logger.info("HTTP Server starting on port %s", self.port)

    def stop(self):
        self.running.clear()
        server_socket = self.server_socket
        self.server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass
        self.server_thread = None
        self.logger.info("HTTP Server stopped")

    def _serve_loop(self):
        while self.running.is_set():
            try:
                conn, addr = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.running.is_set():
                    self.logger.exception("HTTP Server accept failed")
                break

            worker = threading.Thread(
                target=self._handle_connection,
                args=(conn, addr),
                daemon=True,
            )
            worker.start()

    def _handle_connection(self, conn: socket.socket, addr: Tuple[str, int]):
        conn.settimeout(5.0)
        try:
            method, path, headers, body = self._read_request(conn)
            if not method:
                return

            self.logger.debug("%s %s from %s", method, path, addr[0])

            if method == "OPTIONS":
                self._send_response(conn, 200, {"ok": True})
                return

            if method == "GET":
                self._handle_get(conn, path)
                return

            if method == "POST":
                self._handle_post(conn, path, headers, body)
                return

            self._send_response(conn, 405, {"error": "Method not allowed"})
        except socket.timeout:
            self.logger.debug("HTTP connection from %s timed out", addr[0])
        except ValueError as e:
            self._send_response(conn, 400, {"error": str(e)})
        except Exception:
            self.logger.exception("Error handling HTTP request")
            self._send_response(conn, 500, {"error": "Internal Server Error"})
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _read_request(self, conn: socket.socket):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return None, None, {}, b""
            data += chunk
            if len(data) > self.MAX_HEADER_SIZE:
                raise ValueError("Request header too large")

        header_bytes, body = data.split(b"\r\n\r\n", 1)
        header_text = header_bytes.decode("iso-8859-1")
        lines = header_text.split("\r\n")
        request_line = lines[0]
        parts = request_line.split()
        if len(parts) != 3:
            raise ValueError("Malformed request line")

        method, path, _http_version = parts
        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        content_length = int(headers.get("content-length", "0") or "0")
        if content_length > self.MAX_BODY_SIZE:
            raise ValueError("Request body too large")

        while len(body) < content_length:
            chunk = conn.recv(min(4096, content_length - len(body)))
            if not chunk:
                break
            body += chunk

        return method.upper(), path, headers, body[:content_length]

    def _handle_get(self, conn: socket.socket, raw_path: str):
        path = urllib.parse.urlparse(raw_path).path

        if path == "/api/wifi/status":
            self._send_response(conn, 200, self._get_wifi_status())
            return
        if path == "/api/system/info":
            self._send_response(conn, 200, self._get_system_info())
            return
        if path == "/api/ota/status":
            self._send_response(conn, 200, self.supervisor.get_ota_state())
            return

        self._send_text(conn, 404, "Not Found")

    def _handle_post(self, conn: socket.socket, raw_path: str, headers: Dict[str, str], body: bytes):
        path = urllib.parse.urlparse(raw_path).path
        if path != "/api/system/command":
            self._send_response(conn, 404, {"error": "Not found"})
            return

        post_data = body.decode("utf-8")
        self.logger.debug("POST data: %s", post_data)
        params, signature, is_valid = self._parse_post_data(post_data, headers.get("content-type", ""))

        if "command" not in params:
            self._send_response(conn, 400, {"error": "Command is required"})
            return
        if not signature:
            self._send_response(conn, 400, {"error": "Signature is required"})
            return
        if not is_valid:
            self._send_response(conn, 401, {"error": "Unauthorized: Invalid signature"})
            return

        command = params.get("command", "")
        param_dict = self._decode_param_payload(params.get("param", ""))

        if command == "reboot":
            self._send_response(conn, 200, {"success": True})
            threading.Timer(3.0, self.supervisor.perform_reboot).start()
            return

        if command == "factory_reset":
            self._send_response(conn, 200, {"success": True})
            threading.Timer(3.0, self.supervisor.perform_factory_reset).start()
            return

        if command == "ota":
            required_fields = ("url", "version", "md5")
            for field in required_fields:
                if field not in param_dict:
                    self._send_response(conn, 400, {"error": f"Missing required field: {field}"})
                    return

            try:
                ota_id = self.supervisor.start_ota_update_async(
                    url=param_dict["url"],
                    version=param_dict["version"],
                    md5=param_dict["md5"],
                )
            except RuntimeError as e:
                self._send_response(conn, 409, {"success": False, "error": str(e)})
                return

            self._send_response(conn, 200, {"success": True, "ota_id": ota_id})
            return

        self._send_response(conn, 400, {"error": f"Unsupported command: {command}"})

    def _get_wifi_status(self):
        from .sysinfo import get_device_info

        device_info = get_device_info()
        return {
            "connected": device_info.get("status", "") in ("connected", "connected_no_internet"),
            "ssid": device_info.get("ssid", ""),
            "ip_address": device_info.get("ip", ""),
            "mac_address": device_info.get("macAddress", ""),
            "message": "",
        }

    def _get_system_info(self):
        from .sysinfo import get_device_info

        device_info = get_device_info()
        return {
            "Device Model": "ThirdReality HA Speaker",
            "Device Name": device_info.get("name", ""),
            "WIFI Connected": device_info.get("status", "") in ("connected", "connected_no_internet"),
            "SSID": device_info.get("ssid", ""),
            "Ip Address": device_info.get("ip", ""),
            "Mac Address": device_info.get("macAddress", ""),
            "Version": device_info.get("firmwareVersion", ""),
        }

    def _decode_param_payload(self, encoded: str):
        if not encoded:
            return {}
        try:
            decoded = urllib.parse.unquote(encoded)
            payload = base64.b64decode(decoded).decode("utf-8")
            self.logger.debug("param_data (decoded): %s", payload)
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            self.logger.exception("param decode failed")
        raise ValueError("param decode error")

    def _parse_post_data(self, post_data: str, content_type: str):
        params = {}
        signature = None

        if "application/json" in content_type:
            payload = json.loads(post_data or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            for key, value in payload.items():
                        if key == "_sig":
                            signature = str(value)
                        else:
                            params[key] = str(value)
        else:
            # Keep raw form values for signature compatibility with the legacy app.
            for pair in post_data.split("&"):
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                if key == "_sig":
                    signature = value
                else:
                    params[key] = value

        return params, signature, self._verify_signature(params, signature)

    def _verify_signature(self, params, signature):
        if not signature:
            return False
        sorted_keys = sorted(params.keys())
        param_string = "&".join(f"{key}={params[key]}" for key in sorted_keys)
        security_string = f"{param_string}&{self.API_SECRET_KEY}"
        calculated_md5 = hashlib.md5(security_string.encode()).hexdigest()
        return hmac.compare_digest(calculated_md5, signature)

    def _send_text(self, conn: socket.socket, status_code: int, body: str):
        body_bytes = body.encode("utf-8")
        reason = self._reason_phrase(status_code)
        headers = [
            f"HTTP/1.1 {status_code} {reason}",
            "Content-Type: text/plain; charset=utf-8",
            f"Content-Length: {len(body_bytes)}",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Methods: GET, POST, OPTIONS",
            "Access-Control-Allow-Headers: Content-Type",
            "Connection: close",
            "",
            "",
        ]
        conn.sendall("\r\n".join(headers).encode("utf-8") + body_bytes)

    def _send_response(self, conn: socket.socket, status_code: int, payload):
        body_bytes = json.dumps(payload).encode("utf-8")
        reason = self._reason_phrase(status_code)
        headers = [
            f"HTTP/1.1 {status_code} {reason}",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body_bytes)}",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Methods: GET, POST, OPTIONS",
            "Access-Control-Allow-Headers: Content-Type",
            "Connection: close",
            "",
            "",
        ]
        conn.sendall("\r\n".join(headers).encode("utf-8") + body_bytes)

    @staticmethod
    def _reason_phrase(status_code: int) -> str:
        reasons = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            500: "Internal Server Error",
        }
        return reasons.get(status_code, "OK")
