"""Standalone screenshot relay for Hermes CoAgent.
Runs on Session 1's interactive desktop via scheduled task.
Provides /screen (JPEG) and /health endpoints on port 9124.
PIL.ImageGrab works here because we run on the real desktop.
"""
import http.server
import socketserver
import sys
import threading
import time
import io
import os
import secrets
from urllib.parse import urlparse

TRAY_PORT = 9124
def _arg_value(name):
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return ""


def _positional_int(index, default):
    positional = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    try:
        return int(positional[index])
    except (IndexError, TypeError, ValueError):
        return default


REQUIRED_TOKEN = (
    _arg_value("--token")
    or os.environ.get("COAGENT_TOKEN", "")
    or os.environ.get("HERMES_COAGENT_TOKEN", "")
)
_SCREENSHOT_CACHE_TTL = 0.2  # 200ms

_last_screenshot = None
_last_screenshot_time = 0
_last_screenshot_key = None
_lock = threading.Lock()

def _capture_screenshot(jpeg=True, quality=85):
    global _last_screenshot, _last_screenshot_time, _last_screenshot_key
    now = time.time()
    cache_key = int(now / _SCREENSHOT_CACHE_TTL)
    
    with _lock:
        if _last_screenshot is not None and _last_screenshot_key == cache_key:
            return _last_screenshot
    
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        if jpeg:
            img = img.convert("RGB")
            img.save(buf, "JPEG", quality=quality)
            fmt = "jpeg"
        else:
            img.save(buf, "PNG")
            fmt = "png"
        data = buf.getvalue()
        
        with _lock:
            _last_screenshot = data
            _last_screenshot_time = now
            _last_screenshot_key = cache_key
        
        return data
    except Exception as e:
        return str(e).encode()

def _is_local_origin(origin):
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        return parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    except Exception:
        return False


class RelayHandler(http.server.BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if _is_local_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Vary", "Origin")

    def _is_authorized(self):
        if not REQUIRED_TOKEN:
            return False
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        return secrets.compare_digest(auth_header[7:], REQUIRED_TOKEN)

    def _send(self, data, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
    
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/screen":
                if not self._is_authorized():
                    self._send(b'{"error":"unauthorized"}', status=401)
                    return
                data = _capture_screenshot(jpeg=True, quality=85)
                self._send(data, content_type="image/jpeg")
            elif parsed.path == "/health":
                self._send(b'{"status":"ok"}')
            elif parsed.path == "/":
                self._send(b'{"relay":"running","port":9124}')
            else:
                self._send(b'{"error":"not found"}', status=404)
        except Exception as e:
            self._send(str(e).encode(), status=500, content_type="text/plain")
    
    def log_message(self, format, *args):
        pass  # suppress http.server logs

def main():
    port = _positional_int(0, TRAY_PORT)
    
    # Try PIL import
    try:
        from PIL import ImageGrab
        _ = ImageGrab.grab()
        print(f"PIL works. Desktop size: {_.size}")
    except Exception as e:
        print(f"PIL failed: {e}")
        sys.exit(1)
    
    # Start server
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), RelayHandler)
    print(f"Screenshot relay on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    main()
