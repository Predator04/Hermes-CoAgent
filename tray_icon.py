"""Hermes CoAgent - System Tray Icon
Launched as a subprocess by hermes_coagent.py.
Communicates with the main CoAgent process via HTTP.
"""
import sys, os, json, urllib.request, threading
from base64 import b64decode

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9123
SERVER = f"http://127.0.0.1:{PORT}"

def _api(path, method="POST", body=None):
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(SERVER + path,
            data=data, headers={"Content-Type": "application/json"} if body else {},
            method=method)
        urllib.request.urlopen(req, timeout=3)
    except:
        pass

def main():
    try:
        import pystray
        from PIL import Image, ImageDraw

        icon_size = 64
        img = Image.new("RGBA", (icon_size, icon_size), (17, 17, 34, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, icon_size - 4, icon_size - 4], fill=(102, 126, 234, 255))
        draw.text((18, 14), "C", fill="white", font=None)

        def on_open(icon, item):
            import webbrowser; webbrowser.open(SERVER + "/")

        def on_voice_toggle(icon, item):
            _api("/voice/toggle", body={"enable": True})

        def on_som_refresh(icon, item):
            _api("/som/cache/clear")

        def on_restart(icon, item):
            icon.stop()
            os.execl(sys.executable, sys.executable, *sys.argv)

        def on_quit(icon, item):
            _api("/emergency/stop")
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Toggle Voice", on_voice_toggle),
            pystray.MenuItem("Refresh SOM Cache", on_som_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart CoAgent", on_restart),
            pystray.MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon("HermesCoAgent", img, "Hermes CoAgent v5.1", menu)
        print("TRAY_ICON_READY", flush=True)
        icon.run()
    except ImportError:
        print("TRAY_IMPORT_ERROR: pystray not installed")
        sys.exit(1)
    except Exception as e:
        print(f"TRAY_ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
