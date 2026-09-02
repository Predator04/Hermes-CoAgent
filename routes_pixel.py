"""Screen pixel / color sampling primitives (issue #1240).

Deterministic-first grounding: read a single screen pixel via GDI GetPixel
(microseconds, no full-screen capture) and block-wait for a pixel condition.
Serves the "prefer deterministic over paid vision" direction (#785).

Endpoints:
    GET  /screen/pixel       — read one pixel's color (x, y, optional monitor)
    POST /screen/wait-pixel  — block until a pixel matches a condition or timeout
"""

import ctypes
import re
import time

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

# Conditions supported by /screen/wait-pixel
_SUPPORTED_CONDITIONS = ("==", "!=", "changed", "near")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

# GDI COLORREF for an invalid/out-of-clip point
_CLR_INVALID = 0xFFFFFFFF


def _parse_color(value):
    """Parse '#RRGGBB' / 'RRGGBB' / [r,g,b] / (r,g,b) into an (r, g, b) tuple."""
    if isinstance(value, str):
        m = _HEX_RE.match(value.strip())
        if not m:
            raise ValueError("Invalid color %r: expected '#RRGGBB'" % (value,))
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            rgb = tuple(int(c) for c in value)
        except (TypeError, ValueError):
            raise ValueError("Invalid color %r: expected '#RRGGBB' or [r,g,b]" % (value,))
        if all(0 <= c <= 255 for c in rgb):
            return rgb
        raise ValueError("RGB components out of range: %r" % (value,))
    raise ValueError("Invalid color %r: expected '#RRGGBB' or [r,g,b]" % (value,))


def _monitor_bounds(monitor_index):
    """Return (left, top) of the given monitor, or (0, 0) for the virtual screen.

    monitor_index follows the /screen convention: 0 (or omitted) = full virtual
    desktop, 1 = primary, 2 = second monitor, etc.
    """
    if not monitor_index or monitor_index <= 0:
        return 0, 0
    try:
        import ctypes.wintypes as _wt

        class _MONITORINFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("rcMonitor", _wt.RECT),
                ("rcWork", _wt.RECT),
                ("dwFlags", ctypes.c_uint),
                ("szDevice", ctypes.c_wchar * 32),
            ]

        _MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(_wt.RECT), ctypes.c_longlong,
        )
        handles = []

        def _cb(hmon, _hdc, _rect, _data):
            handles.append(hmon)
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
        if monitor_index - 1 < len(handles):
            info = _MONITORINFOEX()
            info.cbSize = ctypes.sizeof(_MONITORINFOEX)
            ctypes.windll.user32.GetMonitorInfoW(handles[monitor_index - 1], ctypes.byref(info))
            return int(info.rcMonitor.left), int(info.rcMonitor.top)
    except Exception as exc:  # noqa: BLE001
        _log("screen/pixel monitor bounds failed: %s" % exc)
    return 0, 0


def _read_pixel(x, y):
    """Read a single pixel via GDI GetPixel on the desktop DC. Returns (r, g, b)."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.GetPixel.restype = ctypes.c_uint32
    gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    hdc = user32.GetDC(None)
    if not hdc:
        raise RuntimeError("GetDC failed — no interactive desktop access (Session 0?)")
    try:
        colorref = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(None, hdc)
    if colorref == _CLR_INVALID:
        raise ValueError("Pixel (%d, %d) is outside the visible desktop" % (x, y))
    return colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF


def _rgb_to_hex(rgb):
    return "#%02X%02X%02X" % tuple(rgb)


def register_routes(app, state, require_auth):
    @app.route("/screen/pixel", methods=["GET"])
    @require_auth
    def route_screen_pixel():
        x = request.args.get("x")
        y = request.args.get("y")
        if x is None or y is None:
            return jsonify({"error": "Missing required query params: x, y"}), 400
        try:
            x = int(x)
            y = int(y)
        except (TypeError, ValueError):
            return jsonify({"error": "x and y must be integers"}), 400
        monitor = request.args.get("monitor", 0, type=int)
        try:
            ox, oy = _monitor_bounds(monitor)
            r, g, b = _read_pixel(x + ox, y + oy)
            return jsonify({"ok": True, "x": x, "y": y, "monitor": monitor,
                            "hex": _rgb_to_hex((r, g, b)), "rgb": [r, g, b]})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            _log("screen/pixel failed: %s" % exc)
            return jsonify({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}), 500

    @app.route("/screen/wait-pixel", methods=["POST"])
    @require_auth
    def route_screen_wait_pixel():
        d = _json_body()
        if d.get("x") is None or d.get("y") is None:
            return jsonify({"error": "Missing required field: x and y"}), 400
        try:
            x = int(d["x"])
            y = int(d["y"])
        except (TypeError, ValueError):
            return jsonify({"error": "x and y must be integers"}), 400

        condition = str(d.get("condition", "==")).lower()
        if condition not in _SUPPORTED_CONDITIONS:
            return jsonify({"error": "Unknown condition '%s'" % condition,
                            "valid": list(_SUPPORTED_CONDITIONS)}), 400

        try:
            tolerance = max(0, int(d.get("tolerance", 0) or 0))
            interval_ms = max(10, int(d.get("interval_ms", 50) or 50))
            monitor = int(d.get("monitor", 0) or 0)
            timeout_ms = int(d.get("timeout_ms", 10000) or 10000)
        except (TypeError, ValueError):
            return jsonify({"error": "tolerance, timeout_ms, interval_ms, and monitor must be numeric"}), 400
        # 0/negative must not disable the timeout (infinite loop); cap at 60s.
        timeout_ms = max(1, min(60000, timeout_ms))

        target = None
        if condition in ("==", "!=", "near"):
            if d.get("color") is None:
                return _missing_field("color")
            try:
                target = _parse_color(d["color"])
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        ox, oy = _monitor_bounds(monitor)
        ax, ay = x + ox, y + oy

        start = time.perf_counter()
        attempts = 0

        def _matches(rgb, initial):
            if condition == "changed":
                return tuple(rgb) != tuple(initial)
            if condition == "near":
                return all(abs(rgb[i] - target[i]) <= tolerance for i in range(3))
            if condition == "==":
                return all(abs(rgb[i] - target[i]) <= tolerance for i in range(3))
            if condition == "!=":
                return not all(abs(rgb[i] - target[i]) <= tolerance for i in range(3))
            return False

        try:
            initial = _read_pixel(ax, ay)
            while True:
                attempts += 1
                rgb = _read_pixel(ax, ay)
                if _matches(rgb, initial):
                    return jsonify({"ok": True, "matched": True, "x": x, "y": y,
                                    "monitor": monitor, "hex": _rgb_to_hex(rgb),
                                    "rgb": list(rgb),
                                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
                                    "attempts": attempts, "condition": condition})
                elapsed_ms = (time.perf_counter() - start) * 1000
                if timeout_ms and elapsed_ms >= timeout_ms:
                    return jsonify({"ok": True, "matched": False, "timed_out": True,
                                    "x": x, "y": y, "monitor": monitor,
                                    "hex": _rgb_to_hex(rgb), "rgb": list(rgb),
                                    "elapsed_ms": round(elapsed_ms, 1),
                                    "attempts": attempts, "condition": condition})
                time.sleep(interval_ms / 1000.0)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            _log("screen/wait-pixel failed: %s" % exc)
            return jsonify({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}), 500
