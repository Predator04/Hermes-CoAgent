"""Top-level window enumeration and activation routes.

GET  /windows          -- list all top-level windows (hwnd, title, class, pid, etc.)
POST /window/activate  -- bring a window to the foreground by hwnd or title substring
"""

import ctypes
import ctypes.wintypes

from flask import Blueprint, jsonify, request

from shared import _wrap_registered_blueprint_routes, _json_body  # noqa: F401

bp = Blueprint("windows", __name__)

SW_RESTORE = 9


def _get_window_text(user32, hwnd):
    try:
        length = int(user32.GetWindowTextLengthW(hwnd))
    except Exception:
        length = 0
    buf_size = max(length + 1, 512)
    buf = ctypes.create_unicode_buffer(buf_size)
    user32.GetWindowTextW(hwnd, buf, buf_size)
    return buf.value or ""


def _get_class_name(user32, hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _get_pid(user32, hwnd):
    pid = ctypes.wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _get_process_name(pid):
    if not pid:
        return ""
    try:
        import psutil
    except Exception:
        return ""
    try:
        return psutil.Process(int(pid)).name() or ""
    except Exception:
        return ""


def _get_rect(user32, hwnd):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
    }


def _truthy(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y", "t")


def _enum_all_windows():
    """Return a list of raw window dicts for every top-level window."""
    user32 = ctypes.windll.user32
    results = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def _cb(hwnd, _lparam):
        try:
            title = _get_window_text(user32, hwnd)
            class_name = _get_class_name(user32, hwnd)
            if not title and not class_name:
                return True
            pid = _get_pid(user32, hwnd)
            results.append({
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_name,
                "pid": int(pid),
                "process_name": _get_process_name(pid),
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "iconic": bool(user32.IsIconic(hwnd)),
                "zoomed": bool(user32.IsZoomed(hwnd)),
                "rect": _get_rect(user32, hwnd),
            })
        except Exception:
            pass
        return True

    cb = WNDENUMPROC(_cb)
    user32.EnumWindows(cb, 0)
    return results


def _activate_hwnd(hwnd):
    """Restore if minimised, then bring to foreground using AttachThreadInput."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if bool(user32.IsIconic(hwnd)):
        user32.ShowWindow(hwnd, SW_RESTORE)

    # Attach calling thread's input queue to the target window's thread so
    # SetForegroundWindow succeeds even when called from a background process.
    current_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    attached = False
    if target_tid and target_tid != current_tid:
        attached = bool(user32.AttachThreadInput(current_tid, target_tid, True))

    user32.SetForegroundWindow(hwnd)

    if attached:
        user32.AttachThreadInput(current_tid, target_tid, False)


@bp.route("/windows", methods=["GET"])
def route_list_windows():
    """Return all top-level windows; pass ?visible=1 to filter to visible only."""
    try:
        only_visible = _truthy(request.args.get("visible"))
        windows = _enum_all_windows()
        if only_visible:
            windows = [w for w in windows if w["visible"]]
        return jsonify({"ok": True, "count": len(windows), "windows": windows})
    except Exception as exc:
        print("[WINDOWS] error: {0}: {1}".format(type(exc).__name__, exc))
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/window/activate", methods=["POST"])
def route_window_activate():
    """Bring a window to the foreground by hwnd (int) or title (substring)."""
    try:
        body = _json_body()
        raw_hwnd = body.get("hwnd")
        title_query = body.get("title")

        if raw_hwnd is None and not title_query:
            return jsonify({"ok": False, "error": "provide hwnd or title", "code": "BAD_REQUEST"}), 400

        user32 = ctypes.windll.user32

        if raw_hwnd is not None:
            try:
                hwnd = int(raw_hwnd)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "hwnd must be an integer", "code": "BAD_REQUEST"}), 400
            if not bool(user32.IsWindow(hwnd)):
                return jsonify({"ok": False, "error": "hwnd is not a valid window", "code": "WINDOW_NOT_FOUND"}), 404
            title = _get_window_text(user32, hwnd)
            pid = _get_pid(user32, hwnd)
            process_name = _get_process_name(pid)
        else:
            needle = title_query.lower()
            windows = _enum_all_windows()
            match = next((w for w in windows if needle in w["title"].lower()), None)
            if match is None:
                return jsonify({"ok": False, "error": "no window title matches '{0}'".format(title_query), "code": "WINDOW_NOT_FOUND"}), 404
            hwnd = match["hwnd"]
            title = match["title"]
            process_name = match["process_name"]

        _activate_hwnd(hwnd)
        return jsonify({"ok": True, "hwnd": hwnd, "title": title, "process_name": process_name})

    except Exception as exc:
        print("[WINDOWS/ACTIVATE] error: {0}: {1}".format(type(exc).__name__, exc))
        return jsonify({"ok": False, "error": str(exc)}), 500


def register_routes(app, state, require_auth):
    from shared import _wrap_registered_blueprint_routes
    app.register_blueprint(bp)
    _wrap_registered_blueprint_routes(app, bp.name, require_auth)
