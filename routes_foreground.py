"""Foreground-window one-shot context route.

Collapses the common agent probe sequence (which window is active, where
is it, what does it look like) into a single GET call so an AI agent does
not need to chain hwnd, title, rect, and screenshot round-trips.
"""

import base64
import ctypes
import ctypes.wintypes
import io

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR  # noqa: F401  (kept per route convention)


foreground_bp = Blueprint("foreground", __name__)


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
        import psutil  # optional dependency
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


def _virtual_screen_bbox(user32):
    # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
    vx = int(user32.GetSystemMetrics(76))
    vy = int(user32.GetSystemMetrics(77))
    vw = int(user32.GetSystemMetrics(78))
    vh = int(user32.GetSystemMetrics(79))
    return vx, vy, vx + vw, vy + vh


def _clamp_bbox_to_virtual(user32, rect):
    vleft, vtop, vright, vbottom = _virtual_screen_bbox(user32)
    left = max(vleft, int(rect["left"]))
    top = max(vtop, int(rect["top"]))
    right = min(vright, int(rect["right"]))
    bottom = min(vbottom, int(rect["bottom"]))
    if right <= left:
        right = left + 1
    if bottom <= top:
        bottom = top + 1
    return (left, top, right, bottom)


def _capture_window_screenshot(user32, rect):
    """Return (b64_jpeg, out_w, out_h, error_str). error_str is None on success."""
    try:
        from PIL import Image, ImageGrab
    except Exception as exc:
        return None, 0, 0, "PIL not available: {0}".format(exc)

    try:
        bbox = _clamp_bbox_to_virtual(user32, rect)
        img = ImageGrab.grab(bbox=bbox)
    except Exception as exc:
        return None, 0, 0, "{0}: {1}".format(type(exc).__name__, exc)

    try:
        w, h = img.size
        if w <= 0 or h <= 0:
            return None, 0, 0, "empty capture"
        longer = max(w, h)
        if longer > 1024:
            scale = 1024.0 / float(longer)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            img = img.resize((nw, nh), Image.LANCZOS)
            w, h = img.size
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=40)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return b64, w, h, None
    except Exception as exc:
        return None, 0, 0, "encode failed: {0}: {1}".format(type(exc).__name__, exc)


def _truthy(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")


@foreground_bp.route("/window/foreground", methods=["GET"])
def window_foreground():
    """Return the full context for the active foreground window in one call."""
    try:
        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow())

        title = _get_window_text(user32, hwnd) if hwnd else ""
        class_name = _get_class_name(user32, hwnd) if hwnd else ""

        if not hwnd or (not title and not class_name):
            return jsonify({"error": "no foreground window"}), 404

        pid = _get_pid(user32, hwnd)
        process_name = _get_process_name(pid)
        rect = _get_rect(user32, hwnd)
        visible = bool(user32.IsWindowVisible(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        zoomed = bool(user32.IsZoomed(hwnd))

        payload = {
            "hwnd": int(hwnd),
            "title": title,
            "class_name": class_name,
            "pid": int(pid),
            "process_name": process_name,
            "rect": rect,
            "visible": visible,
            "iconic": iconic,
            "zoomed": zoomed,
        }

        if _truthy(request.args.get("screenshot")):
            b64, out_w, out_h, err = _capture_window_screenshot(user32, rect)
            if b64 is None:
                payload["screenshot"] = None
                payload["screenshot_error"] = err or "unknown capture error"
            else:
                payload["screenshot"] = b64
                payload["screenshot_mime"] = "image/jpeg"
                payload["screenshot_width"] = int(out_w)
                payload["screenshot_height"] = int(out_h)

        return jsonify(payload)
    except Exception as exc:
        print("[FOREGROUND] error: {0}: {1}".format(type(exc).__name__, exc))
        return jsonify({"error": str(exc)}), 500


def register_routes(app, state, require_auth):
    app.register_blueprint(foreground_bp)
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, foreground_bp.name, require_auth)
