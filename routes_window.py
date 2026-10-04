"""Window lifecycle control routes.

Completes the window-control surface for an AI agent driving the desktop:
/window/list and /window/focus already live in routes_mouse.py; this module
adds graceful close, minimize, maximize, and restore so an agent can clean
up windows it opened and control window state end-to-end.

All selectors match the /window/focus convention: exactly one of pid, title,
or name (case-insensitive substring on title or process name).
"""

import ctypes
import ctypes.wintypes
import time

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR  # noqa: F401  (kept per route convention)

window_bp = Blueprint("window", __name__)

WM_CLOSE = 0x0010
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9


def _json_body():
    return request.get_json(silent=True) or {}


def _enum_windows():
    """Return a list of (hwnd, title, pid) for all windows with a non-empty title."""
    windows = []

    def _enum_cb(hwnd, _lparam):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            if title.strip():
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                windows.append((int(hwnd), title, int(pid.value)))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    cb = WNDENUMPROC(_enum_cb)
    ctypes.windll.user32.EnumWindows(cb, 0)
    return windows


def _process_name(pid):
    try:
        import psutil
    except Exception:
        return ""
    try:
        return psutil.Process(int(pid)).name() or ""
    except Exception:
        return ""


def _find_target():
    """Resolve the pid/title/name selector to a matching (hwnd, title, pid).

    Returns (hwnd, title, pid) on match, or (None, None, error_tuple).
    error_tuple is (message, status_code).
    """
    d = _json_body()
    target_pid = d.get("pid")
    if target_pid is not None:
        try:
            target_pid = int(target_pid)
        except (TypeError, ValueError):
            return None, None, ({"error": "pid must be an integer"}, 400)
    target_title = d.get("title")
    target_name = d.get("name")

    if not any([target_pid is not None, target_title, target_name]):
        return None, None, ({"error": "Provide pid, title, or name"}, 400)

    windows = _enum_windows()
    matches = []
    for hwnd, title, pid in windows:
        if target_pid is not None and pid == target_pid:
            matches.append((hwnd, title, pid))
        elif target_title and target_title.lower() in title.lower():
            matches.append((hwnd, title, pid))
        elif target_name:
            proc_name = _process_name(pid).lower()
            if target_name.lower() in title.lower() or target_name.lower() in proc_name:
                matches.append((hwnd, title, pid))

    if not matches:
        return None, None, (
            {"error": "No window found matching criteria", "windows_found": len(windows)},
            404,
        )
    return matches[0], None, None


def _handle(selector_action):
    """Shared handler for close/minimize/maximize/restore."""
    (hwnd, title, pid), _ctx, err = _find_target()
    if err is not None:
        return jsonify(err[0]), err[1]

    if selector_action == "close":
        # Graceful WM_CLOSE; poll briefly to confirm actual closure.
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        closed = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if not ctypes.windll.user32.IsWindow(hwnd):
                closed = True
                break
        return jsonify({
            "status": "ok",
            "action": "close",
            "hwnd": hwnd,
            "title": title,
            "closed": closed,
        })

    sw_cmd = {
        "minimize": SW_MINIMIZE,
        "maximize": SW_MAXIMIZE,
        "restore": SW_RESTORE,
    }[selector_action]
    ctypes.windll.user32.ShowWindow(hwnd, sw_cmd)
    return jsonify({
        "status": "ok",
        "action": selector_action,
        "hwnd": hwnd,
        "title": title,
    })


@window_bp.route("/window/close", methods=["POST"])
def route_window_close():
    try:
        return _handle("close")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@window_bp.route("/window/minimize", methods=["POST"])
def route_window_minimize():
    try:
        return _handle("minimize")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@window_bp.route("/window/maximize", methods=["POST"])
def route_window_maximize():
    try:
        return _handle("maximize")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@window_bp.route("/window/restore", methods=["POST"])
def route_window_restore():
    try:
        return _handle("restore")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def register_routes(app, state, require_auth):
    app.register_blueprint(window_bp)
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, window_bp.name, require_auth)
