"""Hermes CoAgent - System Tray Icon
Launched as pythonw subprocess by hermes_coagent.py.
Simple pystray icon. Needs: pip install pystray pillow
"""
import sys, os, json, urllib.request, threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9123
SERVER = f"http://127.0.0.1:{PORT}"

def _api(path, method="POST", body=None):
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(SERVER + path,
            data=data, headers={"Content-Type": "application/json"} if body else {},
            method=method)
        urllib.request.urlopen(req, timeout=2)
    except:
        pass

def main():
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (17, 17, 34, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill=(102, 126, 234, 255))
        draw.text((20, 14), "C", fill=(255, 255, 255, 255))

        def on_open(icon, item):
            import webbrowser; webbrowser.open(SERVER + "/")

        def on_voice(icon, item):
            _api("/voice/toggle", body={"enable": True})
            threading.Timer(2.0, lambda: _api("/voice/toggle", body={"enable": False})).start()

        def on_som(icon, item):
            _api("/som/cache/clear")

        def on_quit(icon, item):
            _api("/emergency/stop")
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Toggle Voice", on_voice),
            pystray.MenuItem("Refresh SOM Cache", on_som),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon("HermesCoAgent", img, "Hermes CoAgent v5.1", menu)
        icon.run()
    except ImportError as e:
        # Silent fail — no pystray
        sys.exit(0)
    except Exception as e:
        sys.exit(0)

if __name__ == "__main__":
    main()
