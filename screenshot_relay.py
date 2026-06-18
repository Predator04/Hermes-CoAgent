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
from urllib.parse import urlparse

TRAY_PORT = 9124
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

class RelayHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, data, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except:
            pass
    
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/screen":
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else TRAY_PORT
    
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
