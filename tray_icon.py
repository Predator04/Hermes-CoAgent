"""Hermes CoAgent - System Tray Icon v2
Full right-click menu with settings, minimize-to-tray, and server control.
Launched as pythonw subprocess by hermes_coagent.py.
v2.1: Added screenshot server (Session 1 capture relay) - no more cmd flash
"""
import sys, os, json, traceback, urllib.request, threading, webbrowser
from datetime import datetime
from pathlib import Path
from io import BytesIO
import base64

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9123
TRAY_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9124
SERVER = f"http://127.0.0.1:{PORT}"
SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "tray_icon.log"

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

def _api_get(path):
    try:
        req = urllib.request.Request(SERVER + path, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode())
    except:
        return None

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

# === Screenshot relay server (runs on Session 1, no cmd flash) ===
def _start_screenshot_server():
    """Start a tiny HTTP server on TRAY_PORT that serves screenshots.
    Runs on the same thread as the tray icon (Session 1).
    PIL.ImageGrab works here because we're on the interactive desktop."""
    import http.server
    import socketserver
    
    class ScreenHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/screen" or self.path.startswith("/screen?"):
                try:
                    from PIL import ImageGrab
                    img = ImageGrab.grab()
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    data = buf.getvalue()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","session":1}')
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"not found"}')
        
        def log_message(self, format, *args):
            _log(f"screenshot-server: {args[0]} {args[1]} {args[2]}")
    
    try:
        server = socketserver.TCPServer(("0.0.0.0", TRAY_PORT), ScreenHandler)
        server.timeout = 0.5
        _log(f"screenshot server started on :{TRAY_PORT}")
        # Run in a loop that the tray icon mainloop can coexist with
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
        
        def get_status():
            info = _api_get("/")
            if info and isinstance(info, dict):
                return f"v{info.get('version', '?')} - Port {PORT}"
            return f"Running on :{PORT}"
        
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
