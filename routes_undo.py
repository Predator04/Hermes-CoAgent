"""Action history tracking and practical undo routes."""

import threading
import time

from flask import Blueprint, jsonify, request

from shared import _console, _json_body


MAX_HISTORY = 100
_LOCK = threading.RLock()
_HISTORY = []


def _normalize_action_type(action_type):
    action_type = str(action_type or "").strip().lower().replace("\\", "/")
    aliases = {
        "click": "mouse/click",
        "mouse/click": "mouse/click",
        "dblclick": "mouse/dblclick",
        "doubleclick": "mouse/dblclick",
        "mouse/dblclick": "mouse/dblclick",
        "mouse/doubleclick": "mouse/dblclick",
        "type": "key/type",
        "key/type": "key/type",
        "text": "key/type",
        "drag": "mouse/drag",
        "mouse/drag": "mouse/drag",
        "scroll": "scroll",
        "mouse/scroll": "scroll",
    }
    return aliases.get(action_type, action_type)


def _append_history(entry):
    with _LOCK:
        _HISTORY.append(entry)
        if len(_HISTORY) > MAX_HISTORY:
            del _HISTORY[:len(_HISTORY) - MAX_HISTORY]


def _client_post(app, path, payload):
    headers = {}
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        headers["Authorization"] = auth_header
    with app.test_client() as client:
        response = client.post(path, json=payload, headers=headers)
    body = response.get_json(silent=True)
    if body is None:
        body = response.get_data(as_text=True)
    return body, int(response.status_code)


def _coerce_int(params, key, default=0):
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _undo_click(app, params, double=False):
    x = _coerce_int(params, "x")
    y = _coerce_int(params, "y")
    button = params.get("button", "left")
    path = "/mouse/dblclick" if double else "/mouse/click"
    body = {"x": x, "y": y, "button": button, "background": params.get("background", True)}
    if not double:
        body["retry"] = False
    response, status = _client_post(app, path, body)
    if status >= 400:
        return {"error": "undo click failed", "details": response}, status
    return {"undone": "dblclick" if double else "click", "at": {"x": x, "y": y}, "result": response}, 200


def _undo_type(params):
    previous_text = params.get("previous_text", params.get("before_text", params.get("replacement_text")))
    try:
        import pyautogui
    except Exception as exc:
        return {"error": f"pyautogui unavailable: {exc}"}, 500

    if previous_text is not None:
        try:
            import pyperclip

            pyperclip.copy(str(previous_text))
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.02)
            pyautogui.hotkey("ctrl", "v")
            return {"undone": "type", "strategy": "restore_previous_text", "chars": len(str(previous_text))}, 200
        except Exception as exc:
            return {"error": f"failed to restore previous text: {exc}"}, 500

    typed_text = str(params.get("text", ""))
    if not typed_text:
        return {"error": "cannot undo type action without text or previous_text"}, 400
    try:
        pyautogui.press("backspace", presses=len(typed_text), interval=0.01)
    except AttributeError:
        for _ in typed_text:
            pyautogui.hotkey("backspace")
    except Exception as exc:
        return {"error": f"failed to backspace typed text: {exc}"}, 500
    return {"undone": "type", "strategy": "backspace", "chars": len(typed_text)}, 200


def _undo_drag(app, params):
    x1 = _coerce_int(params, "x1")
    y1 = _coerce_int(params, "y1")
    x2 = _coerce_int(params, "x2")
    y2 = _coerce_int(params, "y2")
    response, status = _client_post(app, "/mouse/drag", {
        "x1": x2,
        "y1": y2,
        "x2": x1,
        "y2": y1,
        "button": params.get("button", "left"),
        "background": params.get("background", True),
    })
    if status >= 400:
        return {"error": "undo drag failed", "details": response}, status
    return {
        "undone": "drag",
        "from": {"x": x2, "y": y2},
        "to": {"x": x1, "y": y1},
        "result": response,
    }, 200


def _undo_scroll(app, params):
    clicks = _coerce_int(params, "clicks", _coerce_int(params, "delta", 0))
    response, status = _client_post(app, "/mouse/scroll", {"clicks": -clicks})
    if status >= 400:
        return {"error": "undo scroll failed", "details": response}, status
    return {"undone": "scroll", "clicks": -clicks, "result": response}, 200


def _undo_action(app, entry):
    action_type = _normalize_action_type(entry.get("action_type"))
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    if action_type == "mouse/click":
        return _undo_click(app, params, double=False)
    if action_type == "mouse/dblclick":
        return _undo_click(app, params, double=True)
    if action_type == "key/type":
        return _undo_type(params)
    if action_type == "mouse/drag":
        return _undo_drag(app, params)
    if action_type == "scroll":
        return _undo_scroll(app, params)
    return {"error": "cannot undo this action type", "action_type": entry.get("action_type")}, 400


def register_routes(app, state, require_auth):
    bp = Blueprint("undo", __name__)

    @bp.route("/undo/track", methods=["POST"])
    @require_auth
    def route_undo_track():
        data = _json_body()
        action_type = data.get("action_type")
        if not action_type:
            return jsonify({"error": "Missing required field: action_type"}), 400
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        entry = {
            "action_type": str(action_type),
            "params": params,
            "timestamp": data.get("timestamp") or time.time(),
            "screenshot_before": data.get("screenshot_before") or data.get("before_screenshot"),
            "screenshot_after": data.get("screenshot_after") or data.get("screenshot_path"),
        }
        _append_history(entry)
        _console(f"[undo] tracked action_type={entry['action_type']}")
        return jsonify({"status": "tracked", "count": len(_HISTORY), "action": entry})

    @bp.route("/undo/last", methods=["POST"])
    @require_auth
    def route_undo_last():
        with _LOCK:
            if not _HISTORY:
                return jsonify({"error": "No actions to undo"}), 404
            entry = dict(_HISTORY.pop())

        payload, status = _undo_action(app, entry)
        if status >= 400:
            with _LOCK:
                _HISTORY.append(entry)  # re-insert on failure
        return jsonify(payload), status

    @bp.route("/undo/history", methods=["GET"])
    @require_auth
    def route_undo_history():
        try:
            limit = int(request.args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, MAX_HISTORY))
        with _LOCK:
            actions = list(reversed(_HISTORY[-limit:]))
        return jsonify({"history": actions, "count": len(actions), "max": MAX_HISTORY})

    @bp.route("/undo/clear", methods=["POST"])
    @require_auth
    def route_undo_clear():
        with _LOCK:
            cleared = len(_HISTORY)
            _HISTORY.clear()
        return jsonify({"status": "cleared", "cleared": cleared})

    app.register_blueprint(bp)
