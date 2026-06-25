"""Local screenshot relay for Hermes CoAgent.

Runs in the interactive desktop session and serves screenshots to the main
CoAgent process on 127.0.0.1:9124. This is intentionally small and dependency
light because it is launched by launch_all.ps1 as a fallback when the main
server cannot capture the desktop directly.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = "127.0.0.1"
PORT = 9124
LOG_FILE = Path(__file__).resolve().with_name("screenshot_relay.log")


def _log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def _pil_capture():
    from PIL import ImageGrab

    try:
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        return ImageGrab.grab()


def _mss_capture():
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def _win32_capture():
    from PIL import Image
    import win32con
    import win32gui
    import win32ui

    hwnd = win32gui.GetDesktopWindow()
    hwnd_dc = src_dc = mem_dc = bitmap = None
    try:
        left = win32api_get_metric(76)
        top = win32api_get_metric(77)
        width = win32api_get_metric(78) or win32api_get_metric(0) or 1920
        height = win32api_get_metric(79) or win32api_get_metric(1) or 1080
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)
        mem_dc.BitBlt((0, 0), (width, height), src_dc, (left, top), win32con.SRCCOPY)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bits,
            "raw",
            "BGRX",
            0,
            1,
        )
    finally:
        try:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass
        try:
            if mem_dc is not None:
                mem_dc.DeleteDC()
        except Exception:
            pass
        try:
            if src_dc is not None:
                src_dc.DeleteDC()
        except Exception:
            pass
        try:
            if hwnd_dc is not None:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def win32api_get_metric(index: int) -> int:
    try:
        import win32api

        return int(win32api.GetSystemMetrics(index))
    except Exception:
        return 0


def _capture_image():
    errors = []
    for name, capture in (("pil", _pil_capture), ("mss", _mss_capture), ("win32", _win32_capture)):
        try:
            image = capture()
            if image is not None:
                return image, name, errors
            errors.append(f"{name}: returned no image")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return None, "", errors


def _encode_image(image, fmt: str, quality: int):
    buffer = io.BytesIO()
    if fmt == "png":
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue(), "image/jpeg"


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "HermesScreenshotRelay/1.0"

    def log_message(self, fmt, *args):
        _log(fmt % args)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "relay": "screenshot", "port": self.server.server_port})
            return
        if parsed.path not in {"/screen", "/screenshot"}:
            self._json(404, {"error": "not found", "path": parsed.path})
            return

        query = parse_qs(parsed.query)
        fmt = (query.get("format", ["jpeg"])[0] or "jpeg").lower()
        if fmt not in {"jpeg", "jpg", "png"}:
            self._json(400, {"error": "format must be jpeg or png"})
            return
        if fmt == "jpg":
            fmt = "jpeg"
        try:
            quality = max(1, min(95, int(query.get("quality", ["85"])[0])))
        except (TypeError, ValueError):
            quality = 85

        started = time.perf_counter()
        image, method, errors = _capture_image()
        if image is None:
            detail = "; ".join(errors)
            _log(f"capture failed: {detail}")
            self._json(500, {"error": "capture failed", "detail": detail})
            return
        try:
            data, content_type = _encode_image(image, "png" if fmt == "png" else "jpeg", quality)
        except Exception as exc:
            self._json(500, {"error": "encode failed", "detail": f"{type(exc).__name__}: {exc}"})
            return

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Capture-Method", method)
        self.send_header("X-Capture-Latency-Ms", str(latency_ms))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes CoAgent screenshot relay")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RelayHandler)
    _log(f"relay started host={args.host} port={args.port}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _log("relay stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
