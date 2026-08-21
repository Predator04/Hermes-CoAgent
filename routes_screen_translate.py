"""DPI-aware screen <-> input coordinate translation.

On high-DPI, ultrawide (5120x1440) or mixed-DPI multi-monitor setups a pixel an
agent sees in a screenshot (physical/device pixels) is NOT the coordinate the
input APIs expect (logical/DIP). This module exposes the canonical transform so
calling agents don't have to re-implement (and get wrong) the DPI math.

    GET  /screen/scale      — per-monitor DPI scale + physical/logical virtual bounds
    POST /screen/translate  — convert a point between physical and logical space

Coordinate model:
  * physical  = device pixels (what a screenshot captures)
  * logical   = DIP / input coordinates, scaled by (dpi / 96)
  * "monitor" space (default) treats x,y as relative to the target monitor's
    top-left.  "virtual" space treats x,y as absolute across the whole desktop;
    the monitor offset is factored in and normalized using the primary scale.
"""

import ctypes

from flask import jsonify

from shared import _json_body, _log


def _declare_dpi_aware():
    """Declare this process DPI-aware (Per-Monitor V2) so Win32 input and screen
    APIs agree on coordinate space. Must run before any UI is created; the call
    is idempotent and a silent no-op on non-Windows hosts."""
    try:
        if not hasattr(ctypes, "windll"):
            return False
        user32 = ctypes.windll.user32
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4 (Win10 1703+)
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return True
        except Exception:
            pass
        # Fallback: SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE == 2)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return True
        except Exception:
            pass
        # Last resort: SetProcessDPIAware() (system DPI aware)
        try:
            user32.SetProcessDPIAware()
            return True
        except Exception:
            return False
    except Exception:
        return False


_declare_dpi_aware()


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _monitor_enum():
    """Enumerate monitors with physical bounds + per-monitor DPI. Returns a list
    of dicts ordered by EnumDisplayMonitors callback order."""
    import ctypes.wintypes as _wt

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("rcMonitor", _wt.RECT),
            ("rcWork", _wt.RECT),
            ("dwFlags", ctypes.c_uint),
            ("szDevice", ctypes.c_wchar * 32),
        ]

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(_wt.RECT), ctypes.c_longlong,
    )
    hmonitors = []

    def _cb(hmon, _hdc, _rect, _data):
        hmonitors.append(hmon)
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)

    monitors = []
    MONITORINFOF_PRIMARY = 1
    for idx, hmon in enumerate(hmonitors):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        dpi_x = ctypes.c_uint(96)
        dpi_y = ctypes.c_uint(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        except Exception:
            pass
        monitors.append({
            "index": idx,
            "id": idx + 1,
            "name": info.szDevice.strip() or f"Monitor {idx + 1}",
            "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            "left": r.left,
            "top": r.top,
            "width": r.right - r.left,
            "height": r.bottom - r.top,
            "right": r.right,
            "bottom": r.bottom,
            "dpi_x": dpi_x.value,
            "dpi_y": dpi_y.value,
            "scale_x": round(dpi_x.value / 96.0, 4),
            "scale_y": round(dpi_y.value / 96.0, 4),
        })
    return monitors


def _virtual_bounds(monitors):
    """Physical + logical virtual-screen bounding box across all monitors."""
    if not monitors:
        return {"left": 0, "top": 0, "width": 0, "height": 0}, {"left": 0, "top": 0, "width": 0, "height": 0}
    left = min(m["left"] for m in monitors)
    top = min(m["top"] for m in monitors)
    right = max(m["right"] for m in monitors)
    bottom = max(m["bottom"] for m in monitors)
    primary = next((m for m in monitors if m["is_primary"]), monitors[0])
    sx = primary["scale_x"] or 1.0
    sy = primary["scale_y"] or 1.0
    physical = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    logical = {
        "left": round(left / sx),
        "top": round(top / sy),
        "width": round((right - left) / sx),
        "height": round((bottom - top) / sy),
    }
    return physical, logical


def _pick_monitor(monitors, monitor_id, x, y):
    if monitor_id is not None:
        for m in monitors:
            if m["id"] == monitor_id:
                return m
    for m in monitors:
        if m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]:
            return m
    return next((m for m in monitors if m["is_primary"]), monitors[0] if monitors else None)


def _translate(x, y, monitor, from_space, to_space, absolute):
    sx = monitor["scale_x"] or 1.0
    sy = monitor["scale_y"] or 1.0
    if not absolute:
        # x,y are relative to the monitor's top-left.
        px, py = x, y
    else:
        # x,y are absolute in the *from* space — strip the monitor offset first.
        if from_space == "physical":
            px, py = x - monitor["left"], y - monitor["top"]
        else:
            px, py = x - round(monitor["left"] / sx), y - round(monitor["top"] / sy)

    if from_space == to_space:
        out_x, out_y = px, py
    elif from_space == "physical" and to_space == "logical":
        out_x, out_y = round(px / sx), round(py / sy)
    elif from_space == "logical" and to_space == "physical":
        out_x, out_y = round(px * sx), round(py * sy)
    else:
        raise ValueError(f"unknown from/to pair: {from_space} -> {to_space}")

    if absolute:
        if to_space == "physical":
            out_x += monitor["left"]
            out_y += monitor["top"]
        else:
            out_x += round(monitor["left"] / sx)
            out_y += round(monitor["top"] / sy)
    return out_x, out_y


def register_routes(app, state, require_auth):
    @app.route("/screen/scale", methods=["GET"])
    @require_auth
    def route_screen_scale():
        try:
            monitors = _monitor_enum()
        except Exception as exc:
            _log(f"screen/scale failed: {exc}")
            return jsonify({"error": str(exc)}), 500
        physical, logical = _virtual_bounds(monitors)
        return jsonify({
            "status": "ok",
            "count": len(monitors),
            "virtual_screen_physical": physical,
            "virtual_screen_logical": logical,
            "monitors": monitors,
        })

    @app.route("/screen/translate", methods=["POST"])
    @require_auth
    def route_screen_translate():
        data = _json_body() or {}
        try:
            x = float(data.get("x"))
            y = float(data.get("y"))
        except (TypeError, ValueError):
            return jsonify({"error": "x and y must be numbers"}), 400
        from_space = str(data.get("from", "physical")).lower()
        to_space = str(data.get("to", "logical")).lower()
        if from_space not in ("physical", "logical") or to_space not in ("physical", "logical"):
            return jsonify({"error": "from/to must be 'physical' or 'logical'"}), 400
        monitor_id = data.get("monitor_id")
        absolute = _parse_bool(data.get("absolute", False))
        try:
            monitors = _monitor_enum()
        except Exception as exc:
            _log(f"screen/translate monitor enum failed: {exc}")
            return jsonify({"error": str(exc)}), 500
        if not monitors:
            return jsonify({"error": "no monitors detected"}), 500
        monitor = _pick_monitor(monitors, monitor_id, x, y)
        if monitor is None:
            return jsonify({"error": "no monitor found"}), 404
        try:
            out_x, out_y = _translate(x, y, monitor, from_space, to_space, absolute)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "status": "ok",
            "x": out_x,
            "y": out_y,
            "from": from_space,
            "to": to_space,
            "absolute": absolute,
            "monitor_id": monitor["id"],
            "monitor_name": monitor["name"],
            "scale_x": monitor["scale_x"],
            "scale_y": monitor["scale_y"],
        })
