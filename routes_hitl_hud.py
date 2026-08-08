"""HITL (Human-in-the-Loop) HUD Overlay routes.

Before the agent acts, flash a semi-transparent overlay on the target element.
Supports pause/resume via state.emergency_stop.
"""
import logging
import threading
import time

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
hitl_bp = Blueprint("hitl_hud", __name__)

_HITL_STATE = {
    "paused": False,
    "preview_active": False,
    "confirmations_required": 0,
    "total_previews": 0,
    "delay_ms": 1000,
    "require_confirmation": True,
    "hotkey": "Ctrl+Esc",
}
_HITL_LOCK = threading.Lock()
_PREVIEW_HWND = None


def _debug_failure(context, exc):
    _LOGGER.debug("hitl_hud %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _flash_rect(bbox, duration_ms=2000, color_rgba=(255, 0, 0, 80)):
    """Draw a semi-transparent rectangle overlay using win32gui."""
    try:
        import win32gui
        import win32con

        x, y, w, h = bbox
        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST,
            "STATIC", None,
            win32con.WS_POPUP,
            x, y, w, h,
            0, 0, 0, None
        )
        if not hwnd:
            return False
        win32gui.SetLayeredWindowAttributes(hwnd, 0, color_rgba[3], win32con.LWA_ALPHA)
        hwnd_dc = win32gui.GetDC(hwnd)
        from win32api import RGB
        brush = win32gui.CreateSolidBrush(RGB(color_rgba[0], color_rgba[1], color_rgba[2]))
        old_brush = win32gui.SelectObject(hwnd_dc, brush)
        win32gui.Rectangle(hwnd_dc, 0, 0, w, h)
        win32gui.SelectObject(hwnd_dc, old_brush)
        win32gui.DeleteObject(brush)
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        global _PREVIEW_HWND
        _PREVIEW_HWND = hwnd
        time.sleep(duration_ms / 1000.0)
        win32gui.DestroyWindow(hwnd)
        _PREVIEW_HWND = None
        return True
    except Exception as exc:
        _debug_failure("flash_rect", exc)
        return False


@hitl_bp.route("/hitl/preview", methods=["POST"])
def _hitl_preview():
    body = request.get_json(force=True, silent=True) or {}
    bbox = body.get("bbox")
    if not bbox or len(bbox) < 4:
        return jsonify({"ok": False, "error": "bbox [x,y,w,h] required"}), 400
    duration = int(body.get("duration_ms", 2000))
    ok = _flash_rect(bbox, duration)
    with _HITL_LOCK:
        _HITL_STATE["total_previews"] += 1
        _HITL_STATE["preview_active"] = False
    return jsonify({"ok": ok, "bbox": bbox, "duration_ms": duration})


@hitl_bp.route("/hitl/status", methods=["GET"])
def _hitl_status():
    with _HITL_LOCK:
        return jsonify({"ok": True, **_HITL_STATE})


@hitl_bp.route("/hitl/pause", methods=["POST"])
def _hitl_pause():
    state = _get_state()
    if state is not None:
        state.emergency_stop = True
    with _HITL_LOCK:
        _HITL_STATE["paused"] = True
    return jsonify({"ok": True, "paused": True})


@hitl_bp.route("/hitl/resume", methods=["POST"])
def _hitl_resume():
    state = _get_state()
    if state is not None:
        state.emergency_stop = False
    with _HITL_LOCK:
        _HITL_STATE["paused"] = False
    return jsonify({"ok": True, "paused": False})


@hitl_bp.route("/hitl/configure", methods=["POST"])
def _hitl_configure():
    body = request.get_json(force=True, silent=True) or {}
    with _HITL_LOCK:
        for key in ("delay_ms", "require_confirmation", "hotkey"):
            if key in body:
                _HITL_STATE[key] = body[key]
    return jsonify({"ok": True, **_HITL_STATE})


def _get_state():
    try:
        from hermes_coagent import state
        return state
    except Exception:
        return None


def register_routes(app, state, require_auth):
    app.register_blueprint(hitl_bp)
    _LOGGER.info("HITL HUD routes registered")
