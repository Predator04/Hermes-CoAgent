"""Hermes CoAgent - System Tray Icon v3
Full right-click menu + screenshot relay + UIA relay + screenshot cache.
Launched as pythonw subprocess by hermes_coagent.py.
v3.0: JPEG support (?format=jpeg), screenshot cache (200ms), UIA relay (/uia/tree)
"""
import sys, os, json, traceback, urllib.request, threading, webbrowser, time
from datetime import datetime
from pathlib import Path
from io import BytesIO

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9123
TRAY_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9124
SERVER = f"http://127.0.0.1:{PORT}"
SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "tray_icon.log"

# Screenshot cache
_last_screenshot = None
_last_screenshot_time = 0
_last_screenshot_key = None
_SCREENSHOT_CACHE_TTL = 0.2  # 200ms cache

def _log(message):
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except Exception:
        pass

def _api(path, method="POST", body=None):
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(SERVER + path,
            data=data, headers={"Content-Type": "application/json"} if body else {},
            method=method)
        urllib.request.urlopen(req, timeout=2)
    except:
        pass

def _load_icon_font():
    from PIL import ImageFont

    font_size = 40
    for font_path in [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\consola.ttf",
    ]:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, font_size)
            except Exception:
                continue
    return ImageFont.load_default()

def _build_icon_image():
    from PIL import Image, ImageDraw

    font = _load_icon_font()
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, 62, 62], fill=(102, 126, 234, 255), outline=(132, 156, 255, 255))

    text = "C"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (64 - tw) // 2
    y = (64 - th) // 2 - 1
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img

def _capture_screenshot_impl(jpeg=False, quality=85):
    """Actually grab the screenshot. Returns bytes."""
    global _last_screenshot, _last_screenshot_time, _last_screenshot_key
    from PIL import ImageGrab
    now = time.time()
    cache_key = ("jpeg", quality) if jpeg else ("png", None)
    if (
        _last_screenshot
        and _last_screenshot_key == cache_key
        and (now - _last_screenshot_time) < _SCREENSHOT_CACHE_TTL
    ):
        return _last_screenshot
    img = ImageGrab.grab()
    buf = BytesIO()
    if jpeg:
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, format="PNG")
    data = buf.getvalue()
    _last_screenshot = data
    _last_screenshot_time = now
    _last_screenshot_key = cache_key
    return data

# === Screenshot relay server (runs on Session 1, no cmd flash) ===
def _start_screenshot_server():
    """Start a tiny HTTP server on TRAY_PORT that serves screenshots and UIA data.
    Runs on the same thread as the tray icon (Session 1).
    PIL.ImageGrab works here because we're on the interactive desktop."""
    import http.server
    import socketserver

    class ScreenHandler(http.server.BaseHTTPRequestHandler):
        def _send_body(self, data, status=200, content_type="application/json", extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            global _last_screenshot, _last_screenshot_time, _last_screenshot_key, _SCREENSHOT_CACHE_TTL
            try:
                if self.path.startswith("/screen"):
                    # Check for JPEG format
                    use_jpeg = "format=jpeg" in self.path or "format=jpg" in self.path
                    if use_jpeg:
                        data = _capture_screenshot_impl(jpeg=True, quality=85)
                        self._send_body(data, content_type="image/jpeg", extra_headers={"X-Format": "jpeg"})
                    else:
                        data = _capture_screenshot_impl(jpeg=False)
                        self._send_body(data, content_type="image/png", extra_headers={"X-Format": "png"})
                elif self.path == "/uia/tree":
                    self._handle_uia()
                elif self.path == "/health":
                    self._send_body(b'{"status":"ok","session":1}')
                elif self.path == "/cache/info":
                    info = json.dumps({
                        "cached": _last_screenshot is not None,
                        "age_ms": int((time.time() - _last_screenshot_time) * 1000) if _last_screenshot else -1,
                        "ttl_ms": int(_SCREENSHOT_CACHE_TTL * 1000)
                    }).encode()
                    self._send_body(info)
                elif self.path == "/cache/clear":
                    _last_screenshot = None
                    _last_screenshot_key = None
                    self._send_body(b'{"status":"cleared"}')
                else:
                    self._send_body(b'{"error":"not found"}', status=404)
            except Exception as e:
                try:
                    self._send_body(str(e).encode(), status=500, content_type="text/plain")
                except Exception:
                    pass

        def _handle_uia(self):
            """Capture UIA tree from Session 1."""
            try:
                import pythoncom
                try:
                    pythoncom.CoInitialize()
                except:
                    pass
                from pywinauto import Desktop as PyWinDesktop
                desktop = PyWinDesktop(backend="uia")
                windows = desktop.windows()
                result = []
                for w in windows[:50]:  # limit to 50 windows
                    try:
                        info = {
                            "title": w.window_text() if hasattr(w, 'window_text') else str(w),
                            "control_type": w.element_info.control_type if hasattr(w, 'element_info') else "",
                            "automation_id": w.element_info.automation_id if hasattr(w, 'element_info') else "",
                            "class_name": w.element_info.class_name if hasattr(w, 'element_info') else "",
                            "visible": w.is_visible() if hasattr(w, 'is_visible') else True,
                            "enabled": w.is_enabled() if hasattr(w, 'is_enabled') else True,
                        }
                        try:
                            r = w.rectangle()
                            info["rect"] = {"left": r.left, "top": r.top, "width": r.width(), "height": r.height()}
                        except:
                            pass
                        # Get children
                        try:
                            children = []
                            for c in w.descendants(depth=1)[:20]:
                                try:
                                    ci = {
                                        "control_type": c.element_info.control_type if hasattr(c, 'element_info') else "",
                                        "name": c.element_info.name if hasattr(c, 'element_info') else "",
                                        "automation_id": c.element_info.automation_id if hasattr(c, 'element_info') else "",
                                    }
                                    try:
                                        r2 = c.rectangle()
                                        ci["rect"] = {"left": r2.left, "top": r2.top, "width": r2.width(), "height": r2.height()}
                                    except:
                                        pass
                                    children.append(ci)
                                except:
                                    pass
                            info["children"] = children
                        except:
                            info["children"] = []
                        result.append(info)
                    except:
                        pass
                data = json.dumps({"windows": result, "count": len(result), "session": 1}).encode()
                self._send_body(data)
            except Exception as e:
                err = json.dumps({"error": str(e), "session": 1}).encode()
                self._send_body(err, status=500)

        def log_message(self, format, *args):
            _log(f"screenshot-server: {args[0]} {args[1]} {args[2]}")

    try:
        server = socketserver.TCPServer(("0.0.0.0", TRAY_PORT), ScreenHandler)
        server.timeout = 0.5
        _log(f"screenshot server started on :{TRAY_PORT}")
        while True:
            server.handle_request()
    except Exception as e:
        _log(f"screenshot server error: {e}")


def main():
    try:
        img = _build_icon_image()

        import pystray
        from pystray import MenuItem as Item, Menu

        def on_open(icon, item):
            webbrowser.open(SERVER + "/")

        def on_dashboard(icon, item):
            webbrowser.open(SERVER + "/dashboard2")

        def on_screen(icon, item):
            webbrowser.open(f"http://127.0.0.1:{TRAY_PORT}/screen")

        def on_voice(icon, item):
            _api("/voice/toggle", body={"enable": True})
            threading.Timer(2.0, lambda: _api("/voice/toggle", body={"enable": False})).start()

        def on_som_refresh(icon, item):
            _api("/som/cache/clear")

        def on_restart(icon, item):
            _api("/emergency/restart")

        def on_emergency_stop(icon, item):
            _api("/emergency/stop")

        def on_quit(icon, item):
            _api("/emergency/stop")
            icon.stop()
            os._exit(0)

        def on_open_folder(icon, item):
            os.startfile(str(SCRIPT_DIR))

        def on_mcp_test(icon, item):
            webbrowser.open(SERVER + "/mcp/test")

        menu = Menu(
            Item("Open Dashboard", on_open, default=True),
            Item("Screen View", on_screen),
            Item("Dashboard v2", on_dashboard),
            Menu.SEPARATOR,
            Item("Toggle Voice (2s)", on_voice),
            Item("Refresh SOM Cache", on_som_refresh),
            Menu.SEPARATOR,
            Item("Settings", Menu(
                Item("Open CoAgent Folder", on_open_folder),
                Item("MCP Test Page", on_mcp_test),
            )),
            Item("Control", Menu(
                Item("Emergency Stop", on_emergency_stop),
                Item("Restart Server", on_restart),
            )),
            Menu.SEPARATOR,
            Item(f"Running on :{PORT}", None, enabled=False),
            Menu.SEPARATOR,
            Item("Quit CoAgent", on_quit),
        )

        icon = pystray.Icon("HermesCoAgent", img, "Hermes CoAgent v5.1", menu)
        _log(f"starting tray icon on {SERVER}")

        # Start screenshot server in a daemon thread
        ss_thread = threading.Thread(target=_start_screenshot_server, daemon=True)
        ss_thread.start()
        _log(f"screenshot relay thread started on :{TRAY_PORT}")

        icon.run()
    except ImportError as e:
        _log(f"import error: {e}")
        sys.exit(0)
    except Exception as e:
        _log(f"startup error: {e}")
        _log(traceback.format_exc().rstrip())
        sys.exit(0)

if __name__ == "__main__":
    main()
