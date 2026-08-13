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
        hwnd = None
        hwnd_dc = None
        brush = None
        old_brush = None
        try:
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
        finally:
            # Always restore GDI state before sleep, regardless of errors
            if hwnd_dc is not None and old_brush is not None:
                win32gui.SelectObject(hwnd_dc, old_brush)
            if brush is not None:
                win32gui.DeleteObject(brush)
            if hwnd is not None and hwnd_dc is not None:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        global _PREVIEW_HWND
        _PREVIEW_HWND = hwnd
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
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
    try:
        duration = max(100, min(int(body.get("duration_ms", 2000)), 5000))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "duration_ms must be a number"}), 400
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


@hitl_bp.route("/hitl/redirect", methods=["POST"])
def _hitl_redirect():
    """Operator redirect prompt: enqueue a steering instruction on a running goal.

    Body: {"goal_id": "abc123", "instruction": "use the cheaper supplier",
           "rollback": false}
    If goal_id is omitted, the latest active goal is used.
    """
    body = request.get_json(force=True, silent=True) or {}
    instruction = str(body.get("instruction") or body.get("message") or "").strip()
    if not instruction:
        return jsonify({"ok": False, "error": "instruction is required"}), 400
    rollback = bool(body.get("rollback"))
    goal_id = str(body.get("goal_id") or "").strip()
    try:
        from routes_copilot_enhanced import (
            _enqueue_steer,
            _latest_goal,
            _rollback_last_completed,
            _emit_goal_timeline,
            _emit_goal_event,
            _log_entry,
            _auth_header,
            _GOALS_LOCK,
            _GOALS,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"copilot_enhanced unavailable: {exc}"}), 503
    if not goal_id:
        active = _latest_goal(active_only=True)
        if not active:
            return jsonify({"ok": False, "error": "no active goal"}), 404
        goal_id = active.get("goal_id") or active.get("id")
    with _GOALS_LOCK:
        exists = goal_id in _GOALS
    if not exists:
        return jsonify({"ok": False, "error": "goal not found", "goal_id": goal_id}), 404
    rollback_result = None
    if rollback:
        auth = _auth_header(request.headers.get("Authorization", ""))
        rollback_result = _rollback_last_completed(goal_id, auth)
        if rollback_result and rollback_result.get("rolled_back_index") is not None:
            _log_entry(
                goal_id,
                "warn",
                f"HITL rollback of step {int(rollback_result['rolled_back_index']) + 1}",
                "\U0001F9ED",
            )
            _emit_goal_event(goal_id, "steer_rollback", rollback_result)
    entry, error = _enqueue_steer(goal_id, instruction, rollback=rollback, source="hitl")
    if error:
        return jsonify({"ok": False, "error": error, "goal_id": goal_id}), 409
    _emit_goal_timeline(goal_id)
    return jsonify({
        "ok": True,
        "goal_id": goal_id,
        "steer": entry,
        "rollback": rollback_result,
    })


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
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, hitl_bp.name, require_auth)
    _LOGGER.info("HITL HUD routes registered")
