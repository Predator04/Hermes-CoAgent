"""Palm and broad-touch rejection settings."""

import ctypes
import ctypes.wintypes
import threading
import time

from flask import jsonify

from shared import _json_body


SM_DIGITIZER = 94
NID_INTEGRATED_TOUCH = 0x01
NID_EXTERNAL_TOUCH = 0x02
NID_INTEGRATED_PEN = 0x04
NID_EXTERNAL_PEN = 0x08
NID_MULTI_INPUT = 0x40
NID_READY = 0x80
TWF_FINETOUCH = 0x00000001
TWF_WANTPALM = 0x00000002

_LOCK = threading.RLock()
_SETTINGS = {
    "enabled": False,
    "area_threshold": 1200,
    "radius_threshold": 20,
    "width_threshold": 42,
    "height_threshold": 42,
}
_FILTERED_EVENTS = 0
_REGISTERED_WINDOWS = []
_LAST_ENABLE_RESULT = {}


def _has_user32():
    return hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32")


def _configure_user32():
    """Set 64-bit-safe prototypes for the touch window APIs."""
    if not _has_user32():
        return None
    user32 = ctypes.windll.user32
    try:
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        user32.GetDesktopWindow.restype = ctypes.wintypes.HWND
        user32.RegisterTouchWindow.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.ULONG)
        user32.RegisterTouchWindow.restype = ctypes.wintypes.BOOL
    except Exception:
        pass
    return user32


def _digitizer_info():
    if not _has_user32():
        return {"available": False, "raw": 0, "reason": "Win32 user32 is unavailable"}
    raw = int(ctypes.windll.user32.GetSystemMetrics(SM_DIGITIZER))
    return {
        "available": bool(raw & NID_READY),
        "raw": raw,
        "integrated_touch": bool(raw & NID_INTEGRATED_TOUCH),
        "external_touch": bool(raw & NID_EXTERNAL_TOUCH),
        "integrated_pen": bool(raw & NID_INTEGRATED_PEN),
        "external_pen": bool(raw & NID_EXTERNAL_PEN),
        "multi_input": bool(raw & NID_MULTI_INPUT),
    }


def _register_touch_windows():
    user32 = _configure_user32()
    if user32 is None:
        return {"registered": [], "errors": ["Win32 user32 is unavailable"]}
    candidates = []
    try:
        candidates.append(("foreground", user32.GetForegroundWindow()))
    except Exception:
        pass
    try:
        candidates.append(("desktop", user32.GetDesktopWindow()))
    except Exception:
        pass
    registered = []
    errors = []
    for label, hwnd in candidates:
        if not hwnd:
            continue
        try:
            ok = bool(user32.RegisterTouchWindow(hwnd, TWF_WANTPALM))
            if ok:
                registered.append({"label": label, "hwnd": int(hwnd)})
            else:
                errors.append({"label": label, "hwnd": int(hwnd), "last_error": ctypes.windll.kernel32.GetLastError()})
        except Exception as e:
            errors.append({"label": label, "error": f"{type(e).__name__}: {e}"})
    with _LOCK:
        _REGISTERED_WINDOWS[:] = registered
    return {"registered": registered, "errors": errors}


def _coerce_int(data, key, current, minimum, maximum):
    if key not in data:
        return current
    try:
        value = int(data[key])
    except (ValueError, TypeError):
        return current
    return max(minimum, min(value, maximum))


def _should_filter(width=0, height=0, radius=0):
    with _LOCK:
        settings = dict(_SETTINGS)
    area = int(width) * int(height)
    return (
        settings["enabled"]
        and (
            area > settings["area_threshold"]
            or int(radius) > settings["radius_threshold"]
            or int(width) > settings["width_threshold"]
            or int(height) > settings["height_threshold"]
        )
    )


def _safe_int(value):
    """Coerce a value to int, defaulting to 0 on non-numeric input."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _filter_sample_events(events):
    global _FILTERED_EVENTS
    filtered = []
    for event in events:
        if not isinstance(event, dict):
            continue
        width = _safe_int(event.get("width", event.get("cx", 0)) or 0)
        height = _safe_int(event.get("height", event.get("cy", 0)) or 0)
        radius = _safe_int(event.get("radius", 0) or 0)
        rejected = _should_filter(width=width, height=height, radius=radius)
        row = dict(event)
        row["rejected"] = rejected
        row["area"] = width * height
        filtered.append(row)
        if rejected:
            with _LOCK:
                _FILTERED_EVENTS += 1
    return filtered


def _status():
    with _LOCK:
        return {
            "settings": dict(_SETTINGS),
            "filtered_events": _FILTERED_EVENTS,
            "registered_windows": list(_REGISTERED_WINDOWS),
            "last_enable_result": dict(_LAST_ENABLE_RESULT),
            "digitizer": _digitizer_info(),
            "time": time.time(),
        }


def register_routes(app, state, require_auth):
    @app.route("/palmreject/settings", methods=["POST", "GET"])
    @require_auth
    def route_palmreject_settings():
        data = _json_body()
        with _LOCK:
            if data:
                _SETTINGS["area_threshold"] = _coerce_int(data, "area_threshold", _SETTINGS["area_threshold"], 1, 100000)
                _SETTINGS["radius_threshold"] = _coerce_int(data, "radius_threshold", _SETTINGS["radius_threshold"], 1, 1000)
                _SETTINGS["width_threshold"] = _coerce_int(data, "width_threshold", _SETTINGS["width_threshold"], 1, 1000)
                _SETTINGS["height_threshold"] = _coerce_int(data, "height_threshold", _SETTINGS["height_threshold"], 1, 1000)
                if "enabled" in data:
                    _SETTINGS["enabled"] = bool(data["enabled"])
        sample = data.get("events") if isinstance(data.get("events"), list) else []
        return jsonify({"status": "updated" if data else "ok", "sample": _filter_sample_events(sample), **_status()})

    @app.route("/palmreject/on", methods=["POST"])
    @require_auth
    def route_palmreject_on():
        global _LAST_ENABLE_RESULT
        result = _register_touch_windows()
        with _LOCK:
            _SETTINGS["enabled"] = True
            _LAST_ENABLE_RESULT = result
        return jsonify({"status": "enabled", "note": "palm rejection requires touch hardware", **_status()})

    @app.route("/palmreject/off", methods=["POST"])
    @require_auth
    def route_palmreject_off():
        with _LOCK:
            _SETTINGS["enabled"] = False
        return jsonify({"status": "disabled", **_status()})

    @app.route("/palmreject/events", methods=["POST", "GET"])
    @require_auth
    def route_palmreject_events():
        with _LOCK:
            count = _FILTERED_EVENTS
        return jsonify({
            "status": "ok",
            "filtered_events": count,
            "note": "palm rejection requires touch hardware",
        })
