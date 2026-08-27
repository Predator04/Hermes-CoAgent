"""Workstation session-state snapshot and session-change event routes.

This module gives agents a clean preflight answer to the question "can I
actually do GUI automation right now?" plus a reactive, push-based session
event source (lock/unlock, logon/logoff, console/RDP connect-disconnect).

Endpoints:
  GET  /session/state          — full snapshot of the workstation session and
                                 desktop state (locked, remote, console-active,
                                 idle time, monitor power, user, gui_ready).
  GET  /session/events         — recent session-change events observed (ring
                                 buffer), plus monitor thread status.
  POST /session/events/test    — inject a synthetic session event (fires any
                                 subscribed webhooks) for end-to-end testing.

Session-change monitor:
  On register_routes() a daemon thread creates a message-only window and calls
  WTSRegisterSessionNotification(NOTIFY_FOR_THIS_SESSION). WM_WTSSESSION_CHANGE
  messages are decoded and (a) appended to the ring buffer and (b) dispatched
  to any subscribed webhooks via routes_webhooks.fire_webhook.

  Event names (also accepted by POST /webhooks/register): session_lock,
  session_unlock, logon, logoff, console_connect, console_disconnect,
  remote_connect, remote_disconnect.

All Win32 / ctypes imports are wrapped in try/except so this file imports
cleanly under a Linux syntax check and degrades gracefully off-Windows.
"""

import threading
import time

from flask import jsonify

from shared import _json_body, _log


# ---------------------------------------------------------------------------
# Event name / constant tables
# ---------------------------------------------------------------------------

# WM_WTSSESSION_CHANGE wParam values (wtsapi32.h)
_WTS_EVENT_MAP = {
    0x1: "console_connect",
    0x2: "console_disconnect",
    0x3: "remote_connect",
    0x4: "remote_disconnect",
    0x5: "logon",
    0x6: "logoff",
    0x7: "session_lock",
    0x8: "session_unlock",
}

# WTSConnectState (WTS_INFO_CLASS == 0) values
_CONNECT_STATE_NAMES = {
    0: "active",
    1: "connected",
    2: "connect_query",
    3: "shadow",
    4: "disconnected",
    5: "idle",
    6: "listen",
    7: "reset",
    8: "down",
    9: "init",
}

# Events this module emits; mirrored in routes_webhooks._ALLOWED_EVENTS so that
# POST /webhooks/register accepts them.
SESSION_EVENTS = tuple(sorted(_WTS_EVENT_MAP.values()))

# Ring buffer of recent session events.
_SESSION_EVENTS = []
_SESSION_EVENTS_LOCK = threading.Lock()
_SESSION_EVENTS_MAX = 200

# Monitor thread handle + stop flag (module-level so restart is possible).
_MONITOR_THREAD = None
_MONITOR_STOP = threading.Event()
_MONITOR_ERROR = None


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Snapshot helpers (each returns None on failure rather than raising)
# ---------------------------------------------------------------------------

def _session_id():
    try:
        import ctypes
        from ctypes import wintypes
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        sess = wintypes.DWORD()
        if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sess)):
            return int(sess.value)
    except Exception:
        pass
    return None


def _username():
    try:
        import ctypes
        from ctypes import wintypes
        size = wintypes.DWORD(256)
        buf = ctypes.create_unicode_buffer(256)
        if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    return None


def _is_locked():
    """True when the interactive desktop is locked (OpenInputDesktop fails)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # DESKTOP_SWITCHDESKTOP (0x0100). OpenInputDesktop returns NULL when the
        # secure/Winlogon desktop owns the input, which is how lock is detected.
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if hdesk:
            user32.CloseDesktop(hdesk)
            return False
        return True
    except Exception:
        return None


def _is_remote_session():
    """True when running in a remote (RDP) session — SM_REMOTESESSION (0x1000)."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
    except Exception:
        return None


def _wts_connect_state():
    """WTSConnectState for the current session (WTSActive == 0)."""
    try:
        import ctypes
        from ctypes import wintypes
        wts = ctypes.windll.wtsapi32
        pp_buffer = ctypes.c_void_p()
        bytes_returned = wintypes.DWORD()
        # hServer=NULL (WTS_CURRENT_SERVER_HANDLE), SessionId=0xFFFFFFFF
        # (WTS_CURRENT_SESSION), WTSInfoClass=0 (WTSConnectState).
        ok = wts.WTSQuerySessionInformationW(
            None, 0xFFFFFFFF, 0, ctypes.byref(pp_buffer), ctypes.byref(bytes_returned)
        )
        if not ok or not pp_buffer.value:
            return None
        try:
            return int(ctypes.cast(pp_buffer, ctypes.POINTER(ctypes.c_int)).contents.value)
        finally:
            wts.WTSFreeMemory(pp_buffer)
    except Exception:
        return None


def _get_idle_ms():
    """Milliseconds since last user input (GetLastInputInfo)."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            # Bind restype/argtypes BEFORE calling so the 64-bit tick counter
            # isn't truncated to a signed 32-bit c_int (which wraps after ~24.8
            # days of uptime). The old code called GetTickCount64() first and
            # then set .restype on the returned int, raising AttributeError and
            # leaving idle_ms permanently null.
            get_tick = ctypes.windll.kernel32.GetTickCount64
            get_tick.restype = ctypes.c_uint64
            get_tick.argtypes = []
            now = get_tick()
            return max(0, int(now) - int(lii.dwTime))
    except Exception:
        pass
    return None


def _monitor_power_state():
    """'on' / 'off' / None via GetDevicePowerState on the primary physical monitor."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
        if not hmon:
            return None

        class PHYSICAL_MONITOR(ctypes.Structure):
            _fields_ = [
                ("hPhysicalMonitor", wintypes.HANDLE),
                ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
            ]

        dxva2 = ctypes.windll.dxva2
        monitors = (PHYSICAL_MONITOR * 1)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, 1, monitors):
            return None
        hpm = monitors[0].hPhysicalMonitor
        if not hpm:
            return None
        try:
            on = wintypes.BOOL()
            if not ctypes.windll.kernel32.GetDevicePowerState(hpm, ctypes.byref(on)):
                return None
            return "on" if on.value else "off"
        finally:
            dxva2.DestroyPhysicalMonitors(1, monitors)
    except Exception:
        return None


def _build_snapshot():
    locked = _is_locked()
    connect_state = _wts_connect_state()
    remote = _is_remote_session()
    idle_ms = _get_idle_ms()
    monitor_power = _monitor_power_state()

    # WTSActive == 0: the session has an active input desktop.
    console_active = connect_state == 0 if connect_state is not None else None
    # GUI input is possible when the desktop is unlocked AND the session is active.
    gui_ready = (locked is False) and (console_active is True)

    return {
        "ok": True,
        "session_id": _session_id(),
        "username": _username(),
        "locked": locked,
        "secure_desktop": locked,
        "console_active": console_active,
        "connect_state": connect_state,
        "connect_state_name": _CONNECT_STATE_NAMES.get(connect_state, "unknown"),
        "remote_session": remote,
        "idle_ms": idle_ms,
        "idle_seconds": round(idle_ms / 1000, 1) if idle_ms is not None else None,
        "monitor_power": monitor_power,
        "gui_ready": gui_ready,
        "monitor": _monitor_status(),
    }


def _monitor_status():
    alive = bool(_MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive())
    return {
        "active": alive,
        "error": _MONITOR_ERROR,
        "backend": "wts_session_notification" if alive else None,
    }


# ---------------------------------------------------------------------------
# Session-change monitor (WTSRegisterSessionNotification)
# ---------------------------------------------------------------------------

def _record_session_event(event_type, event_code, session_id):
    record = {
        "event": event_type,
        "event_code": event_code,
        "session_id": session_id,
        "timestamp": _now(),
    }
    with _SESSION_EVENTS_LOCK:
        _SESSION_EVENTS.append(record)
        if len(_SESSION_EVENTS) > _SESSION_EVENTS_MAX:
            _SESSION_EVENTS[:] = _SESSION_EVENTS[-_SESSION_EVENTS_MAX:]
    # Best-effort webhook dispatch; the webhook module may be optional.
    try:
        from routes_webhooks import fire_webhook
        fire_webhook(event_type, record)
    except Exception as exc:
        _log(f"[session] webhook dispatch failed: {exc}")
    return record


def _session_monitor_loop():
    """Create a message-only window, register WTS notifications, and pump."""
    global _MONITOR_ERROR
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as exc:
        _MONITOR_ERROR = f"{type(exc).__name__}: {exc}"
        _log(f"[session] monitor unavailable: {exc}")
        return

    user32 = ctypes.windll.user32
    wtsapi32 = ctypes.windll.wtsapi32
    kernel32 = ctypes.windll.kernel32

    WM_WTSSESSION_CHANGE = 0x02B1
    NOTIFY_FOR_THIS_SESSION = 0
    WM_QUIT = 0x0012

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
        ctypes.c_ssize_t, ctypes.c_ssize_t,
    )

    def _wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_WTSSESSION_CHANGE:
            event_code = int(wparam & 0xFFFFFFFF)
            session_id = int(lparam & 0xFFFFFFFF)
            event_type = _WTS_EVENT_MAP.get(event_code, f"session_event_{event_code}")
            _record_session_event(event_type, event_code, session_id)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _wndproc_cb = WNDPROC(_wndproc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, ctypes.c_ssize_t, ctypes.c_ssize_t,
    ]

    class_name = "CoAgentSessionMonitorWnd"
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = _wndproc_cb
    wc.hInstance = hinst
    wc.lpszClassName = class_name

    if not user32.RegisterClassW(ctypes.byref(wc)):
        # ERROR_CLASS_ALREADY_EXISTS (1410) is fine — the class is still usable.
        err = ctypes.windll.kernel32.GetLastError()
        if err != 1410:
            _MONITOR_ERROR = f"RegisterClassW failed (error {err})"
            _log(f"[session] {_MONITOR_ERROR}")
            return

    HWND_MESSAGE = wintypes.HWND(-3)
    hwnd = user32.CreateWindowExW(
        0, class_name, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst, None
    )
    if not hwnd:
        _MONITOR_ERROR = "CreateWindowExW (message-only) failed"
        _log(f"[session] {_MONITOR_ERROR}")
        return

    if not wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        _MONITOR_ERROR = "WTSRegisterSessionNotification failed"
        _log(f"[session] {_MONITOR_ERROR}")
        user32.DestroyWindow(hwnd)
        return

    _MONITOR_ERROR = None
    _log("[session] session-change monitor active (WTSRegisterSessionNotification)")

    msg = wintypes.MSG()
    while not _MONITOR_STOP.is_set():
        try:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                if msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            _MONITOR_ERROR = f"message pump error: {exc}"
            _log(f"[session] {_MONITOR_ERROR}")
        time.sleep(0.2)

    try:
        wtsapi32.WTSUnRegisterSessionNotification(hwnd)
    except Exception:
        pass
    try:
        user32.DestroyWindow(hwnd)
    except Exception:
        pass
    _log("[session] session-change monitor stopped")


def _start_session_monitor():
    global _MONITOR_THREAD
    if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
        return False
    _MONITOR_STOP.clear()
    _MONITOR_THREAD = threading.Thread(
        target=_session_monitor_loop, name="session-monitor", daemon=True
    )
    _MONITOR_THREAD.start()
    return True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/session/state", methods=["GET"])
    @require_auth
    def route_session_state():
        return jsonify(_build_snapshot())

    @app.route("/session/events", methods=["GET"])
    @require_auth
    def route_session_events():
        with _SESSION_EVENTS_LOCK:
            events = list(_SESSION_EVENTS)
        return jsonify({
            "events": events,
            "count": len(events),
            "monitor": _monitor_status(),
        })

    @app.route("/session/events/test", methods=["POST"])
    @require_auth
    def route_session_events_test():
        body = _json_body() or {}
        event_type = str(body.get("event") or "session_test").strip() or "session_test"
        record = _record_session_event(event_type, None, _session_id())
        return jsonify({"status": "queued", "event": event_type, "record": record})

    # Start the push-based session-change monitor in the background.
    _start_session_monitor()
