"""Multi-monitor & display topology management (issue #1243).

First-class, read/write control of the physical display layout beyond the
primary/virtual desktop: enumerate displays with friendly names + refresh rate
+ orientation + DPI, rotate / change resolution (test-first), set the primary
display, and move a window onto a specific monitor.

Endpoints:
    GET  /display/list        — enumerate displays (bounds, resolution, refresh,
                                orientation, DPI, primary, friendly name)
    POST /display/set         — change orientation / resolution / refresh rate
                                (validated via CDS_TEST before applying)
    POST /display/primary     — set the primary display
    POST /display/move-window — move (+ optionally focus/maximize) a window
                                onto a specific monitor
"""

import ctypes
import time

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

# DisplayConfig / ChangeDisplaySettingsEx constants
DM_ORIENTATION = 0x00000001
DM_POSITION = 0x00000020
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000

CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002
CDS_SET_PRIMARY = 0x00000010

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISP_CHANGE_FAILED = -1
DISP_CHANGE_BADMODE = -2
DISP_CHANGE_BADPARAM = -5

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF  # -1 as unsigned DWORD

# dmDisplayOrientation values
_ORIENTATION_TO_DEVMODE = {0: 0, 90: 1, 180: 2, 270: 3}
_DEVMODE_TO_ORIENTATION = {0: 0, 1: 90, 2: 180, 3: 270}

_DISP_CHANGE_MESSAGES = {
    DISP_CHANGE_SUCCESSFUL: "The settings change was successful.",
    DISP_CHANGE_RESTART: "The computer must be restarted for the changes to take effect.",
    DISP_CHANGE_FAILED: "The display driver failed the specified graphics mode.",
    DISP_CHANGE_BADMODE: "The graphics mode is not supported.",
    DISP_CHANGE_BADPARAM: "An invalid parameter was passed in.",
}


class _POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_uint),
        ("dmPosition", _POINTL),
        ("dmDisplayOrientation", ctypes.c_uint),
        ("dmDisplayFixedOutput", ctypes.c_uint),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_uint),
        ("dmPelsWidth", ctypes.c_uint),
        ("dmPelsHeight", ctypes.c_uint),
        ("dmDisplayFlags", ctypes.c_uint),
        ("dmDisplayFrequency", ctypes.c_uint),
    ]


class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_uint),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


def _enum_monitors():
    """Return a list of MONITORINFOEX-like dicts via EnumDisplayMonitors."""
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
    handles = []

    def _cb(hmon, _hdc, _rect, _data):
        handles.append(hmon)
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)

    monitors = []
    for idx, hmon in enumerate(handles):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        monitors.append({"index": idx + 1, "hmon": hmon, "info": info})
    return monitors


def _friendly_names():
    """Map display device name ('\\\\.\\DISPLAYn') -> friendly name (e.g. 'Dell U2720Q')."""
    names = {}
    i = 0
    while True:
        adapter = _DISPLAY_DEVICE()
        adapter.cb = ctypes.sizeof(_DISPLAY_DEVICE)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(adapter), 0):
            break
        i += 1
        # Monitor attached to this adapter
        mon = _DISPLAY_DEVICE()
        mon.cb = ctypes.sizeof(_DISPLAY_DEVICE)
        if ctypes.windll.user32.EnumDisplayDevicesW(adapter.DeviceName, 0, ctypes.byref(mon), 0):
            if mon.DeviceString and mon.DeviceString.strip():
                names[adapter.DeviceName] = mon.DeviceString.strip()
            elif adapter.DeviceString and adapter.DeviceString.strip():
                names[adapter.DeviceName] = adapter.DeviceString.strip()
    return names


def _current_mode(device_name):
    """Read the current DEVMODE for a display (resolution, refresh, orientation)."""
    dm = _DEVMODEW()
    dm.dmSize = ctypes.sizeof(_DEVMODEW)
    if not ctypes.windll.user32.EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return None
    return dm


def _display_list():
    monitors = _enum_monitors()
    friendly = _friendly_names()
    out = []
    MONITORINFOF_PRIMARY = 1
    for mon in monitors:
        info = mon["info"]
        device_name = info.szDevice.strip()
        r = info.rcMonitor
        w = info.rcWork
        is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)

        dpi_x = ctypes.c_uint(96)
        dpi_y = ctypes.c_uint(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(
                mon["hmon"], 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
            )
        except Exception:  # noqa: BLE001
            pass

        entry = {
            "index": mon["index"],
            "name": device_name or ("Monitor %d" % mon["index"]),
            "friendly_name": friendly.get(device_name, ""),
            "is_primary": is_primary,
            "left": int(r.left),
            "top": int(r.top),
            "width": int(r.right - r.left),
            "height": int(r.bottom - r.top),
            "work_area": {
                "left": int(w.left),
                "top": int(w.top),
                "width": int(w.right - w.left),
                "height": int(w.bottom - w.top),
            },
            "dpi": {"x": dpi_x.value, "y": dpi_y.value},
            "scaling_pct": round(dpi_x.value / 96.0 * 100),
            "resolution": None,
            "orientation": 0,
        }

        dm = _current_mode(device_name)
        if dm is not None:
            entry["resolution"] = {
                "width": int(dm.dmPelsWidth),
                "height": int(dm.dmPelsHeight),
                "refresh_hz": int(dm.dmDisplayFrequency),
                "bits_per_pixel": int(dm.dmBitsPerPel),
            }
            entry["orientation"] = _DEVMODE_TO_ORIENTATION.get(
                int(dm.dmDisplayOrientation), 0
            )
        out.append(entry)

    primary = next((m for m in out if m["is_primary"]), out[0] if out else {})
    return {"status": "ok", "count": len(out), "displays": out, "primary": primary}


def _find_monitor(monitor):
    """Resolve a monitor index to (device_name, MONITORINFOEX)."""
    monitors = _enum_monitors()
    if monitor < 1 or monitor > len(monitors):
        return None, None
    mon = monitors[monitor - 1]
    return mon["info"].szDevice.strip(), mon["info"]


def _apply_display_change(device_name, dm, flags):
    user32 = ctypes.windll.user32
    user32.ChangeDisplaySettingsExW.argtypes = [
        ctypes.c_wchar_p, ctypes.POINTER(_DEVMODEW), ctypes.c_void_p,
        ctypes.c_uint, ctypes.c_void_p,
    ]
    user32.ChangeDisplaySettingsExW.restype = ctypes.c_long
    return int(user32.ChangeDisplaySettingsExW(device_name, ctypes.byref(dm), None, flags, None))


def register_routes(app, state, require_auth):
    @app.route("/display/list", methods=["GET"])
    @require_auth
    def route_display_list():
        try:
            return jsonify(_display_list())
        except Exception as exc:  # noqa: BLE001
            _log("display/list failed: %s" % exc)
            return jsonify({"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)}), 500

    @app.route("/display/set", methods=["POST"])
    @require_auth
    def route_display_set():
        d = _json_body()
        monitor = int(d.get("monitor", 1) or 1)
        orientation = d.get("orientation")
        resolution = d.get("resolution")
        refresh = d.get("refresh")

        device_name, info = _find_monitor(monitor)
        if device_name is None:
            return jsonify({"error": "monitor index %d out of range" % monitor,
                            "monitor_count": len(_enum_monitors())}), 400

        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        dm.dmDeviceName = device_name

        if orientation is not None:
            try:
                orient = int(orientation)
            except (TypeError, ValueError):
                return jsonify({"error": "orientation must be 0, 90, 180 or 270"}), 400
            if orient not in _ORIENTATION_TO_DEVMODE:
                return jsonify({"error": "orientation must be 0, 90, 180 or 270"}), 400
            dm.dmFields |= DM_ORIENTATION
            dm.dmDisplayOrientation = _ORIENTATION_TO_DEVMODE[orient]

        if resolution is not None:
            if not isinstance(resolution, dict) or "width" not in resolution or "height" not in resolution:
                return jsonify({"error": "resolution must be {\"width\": int, \"height\": int}"}), 400
            try:
                w = int(resolution["width"])
                h = int(resolution["height"])
            except (TypeError, ValueError):
                return jsonify({"error": "resolution width/height must be integers"}), 400
            if w <= 0 or h <= 0:
                return jsonify({"error": "resolution must be positive"}), 400
            dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT
            dm.dmPelsWidth = w
            dm.dmPelsHeight = h

        if refresh is not None:
            try:
                r = int(refresh)
            except (TypeError, ValueError):
                return jsonify({"error": "refresh must be an integer Hz"}), 400
            if r <= 0:
                return jsonify({"error": "refresh must be positive"}), 400
            dm.dmFields |= DM_DISPLAYFREQUENCY
            dm.dmDisplayFrequency = r

        if dm.dmFields == 0:
            return jsonify({"error": "Nothing to change — supply orientation, resolution, or refresh"}), 400

        # Validate first: CDS_TEST applies nothing but returns success only if valid.
        test_rc = _apply_display_change(device_name, dm, CDS_TEST)
        if test_rc != DISP_CHANGE_SUCCESSFUL:
            return jsonify({"ok": False, "error": "Display mode rejected",
                            "code": test_rc,
                            "detail": _DISP_CHANGE_MESSAGES.get(test_rc, "Unknown error")}), 400

        apply_rc = _apply_display_change(device_name, dm, CDS_UPDATEREGISTRY)
        if apply_rc not in (DISP_CHANGE_SUCCESSFUL, DISP_CHANGE_RESTART):
            return jsonify({"ok": False, "error": "Display change failed",
                            "code": apply_rc,
                            "detail": _DISP_CHANGE_MESSAGES.get(apply_rc, "Unknown error")}), 500

        _log("display/set applied on %s (fields=0x%X)" % (device_name, dm.dmFields))
        return jsonify({"ok": True, "monitor": monitor, "device": device_name,
                        "orientation": orientation, "resolution": resolution,
                        "refresh": refresh,
                        "requires_restart": apply_rc == DISP_CHANGE_RESTART})

    @app.route("/display/primary", methods=["POST"])
    @require_auth
    def route_display_primary():
        d = _json_body()
        monitor = int(d.get("monitor", 1) or 1)

        device_name, info = _find_monitor(monitor)
        if device_name is None:
            return jsonify({"error": "monitor index %d out of range" % monitor,
                            "monitor_count": len(_enum_monitors())}), 400

        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        dm.dmDeviceName = device_name
        dm.dmFields = DM_POSITION
        dm.dmPosition.x = 0
        dm.dmPosition.y = 0

        rc = _apply_display_change(device_name, dm, CDS_SET_PRIMARY | CDS_UPDATEREGISTRY)
        if rc != DISP_CHANGE_SUCCESSFUL:
            return jsonify({"ok": False, "error": "Failed to set primary display",
                            "code": rc,
                            "detail": _DISP_CHANGE_MESSAGES.get(rc, "Unknown error")}), 500

        _log("display/primary set to %s" % device_name)
        return jsonify({"ok": True, "monitor": monitor, "device": device_name, "primary": True})

    @app.route("/display/move-window", methods=["POST"])
    @require_auth
    def route_display_move_window():
        d = _json_body()
        title = str(d.get("title", "") or "").strip()
        if not title:
            return _missing_field("title")
        monitor = int(d.get("monitor", 1) or 1)
        maximize = bool(d.get("maximize", False))
        focus = bool(d.get("focus", False))

        try:
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
            handles = []

            def _cb(hmon, _hdc, _rect, _data):
                handles.append(hmon)
                return True

            ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)
            if monitor < 1 or monitor > len(handles):
                return jsonify({"error": "monitor index %d out of range" % monitor,
                                "monitor_count": len(handles)}), 400

            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(MONITORINFOEX)
            ctypes.windll.user32.GetMonitorInfoW(handles[monitor - 1], ctypes.byref(info))
            r = info.rcWork

            windows = []

            def _wcb(hwnd, _):
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                if title.lower() in (buf.value or "").lower():
                    windows.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
            )
            ctypes.windll.user32.EnumWindows(WNDENUMPROC(_wcb), 0)

            if not windows:
                return jsonify({"error": "No visible window matching '%s'" % title}), 404

            hwnd = windows[0]
            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.05)

            if maximize:
                ctypes.windll.user32.MoveWindow(hwnd, r.left, r.top,
                                                r.right - r.left, r.bottom - r.top, True)
                ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
            else:
                work_w = r.right - r.left
                work_h = r.bottom - r.top
                ctypes.windll.user32.MoveWindow(hwnd, r.left, r.top,
                                                min(work_w, 1280), min(work_h, 720), True)

            if focus:
                ctypes.windll.user32.SetForegroundWindow(hwnd)

            _log("Moved '%s' to monitor %d maximize=%s focus=%s" % (title, monitor, maximize, focus))
            return jsonify({"status": "ok", "hwnd": hwnd, "monitor": monitor,
                            "maximize": maximize, "focus": focus})
        except Exception as exc:  # noqa: BLE001
            _log("display/move-window failed: %s" % exc)
            return jsonify({"error": "%s: %s" % (type(exc).__name__, exc)}), 500
