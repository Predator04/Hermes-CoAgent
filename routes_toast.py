"""Windows toast notification routes."""

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import _wrap_registered_blueprint_routes


toast_bp = Blueprint("toast", __name__)

try:
    from win11toast import toast as _win11_toast

    HAS_WIN11TOAST = True
except ImportError:
    _win11_toast = None
    HAS_WIN11TOAST = False


def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _require_win11toast():
    if HAS_WIN11TOAST:
        return None
    return _error(
        "win11toast not installed. Install with: pip install win11toast",
        501,
        package="win11toast",
    )


def _get_string(data, field, required=True, default=""):
    value = data.get(field, default)
    if required and not value:
        return None, _error(f"{field} is required")
    if value is None:
        return default, None
    if not isinstance(value, str):
        return None, _error(f"{field} must be a string")
    return value, None


def _normalize_buttons(buttons):
    if buttons is None:
        return None, None
    if not isinstance(buttons, list):
        return None, _error("buttons must be a list")
    normalized = []
    for item in buttons[:5]:
        if not isinstance(item, dict):
            return None, _error("each button must be an object")
        text = item.get("text")
        action = item.get("action", "")
        if not isinstance(text, str) or not text:
            return None, _error("button text is required")
        if not isinstance(action, str):
            return None, _error("button action must be a string")
        normalized.append({
            "activationType": "protocol",
            "arguments": action or text,
            "content": text,
        })
    return normalized, None


def _toast_kwargs(data):
    kwargs = {}
    for key in ("icon", "image"):
        value = data.get(key)
        if value is not None:
            if not isinstance(value, str):
                return None, _error(f"{key} must be a string path")
            kwargs[key] = value
    buttons, error = _normalize_buttons(data.get("buttons"))
    if error:
        return None, error
    if buttons:
        kwargs["buttons"] = buttons
    return kwargs, None


@toast_bp.route("/toast", methods=["GET"])
def route_toast_index():
    return jsonify({
        "endpoints": [
            {"path": "/toast", "method": "GET", "desc": "List toast endpoints"},
            {"path": "/toast/show", "method": "POST", "desc": "Show a Windows toast notification"},
            {"path": "/toast/input", "method": "POST", "desc": "Show a toast with a text input field"},
        ],
        "dependency": {"package": "win11toast", "installed": HAS_WIN11TOAST},
    })


@toast_bp.route("/toast/show", methods=["POST"])
def route_toast_show():
    missing = _require_win11toast()
    if missing:
        return missing
    data = _json_payload()
    title, error = _get_string(data, "title")
    if error:
        return error
    message, error = _get_string(data, "message")
    if error:
        return error
    kwargs, error = _toast_kwargs(data)
    if error:
        return error
    try:
        _win11_toast(title, message, **kwargs)
        return jsonify({"status": "shown", "title": title, "message": message})
    except Exception as e:
        return _error(str(e), 500, type=type(e).__name__)


@toast_bp.route("/toast/input", methods=["POST"])
def route_toast_input():
    missing = _require_win11toast()
    if missing:
        return missing
    data = _json_payload()
    title, error = _get_string(data, "title")
    if error:
        return error
    message, error = _get_string(data, "message")
    if error:
        return error
    placeholder, error = _get_string(data, "placeholder", required=False, default="")
    if error:
        return error
    kwargs, error = _toast_kwargs(data)
    if error:
        return error
    kwargs["input"] = {
        "id": "reply",
        "type": "text",
        "placeHolderContent": placeholder,
    }
    try:
        _win11_toast(title, message, **kwargs)
        return jsonify({
            "status": "shown",
            "type": "input",
            "title": title,
            "message": message,
            "placeholder": placeholder,
        })
    except Exception as e:
        return _error(str(e), 500, type=type(e).__name__)


def register_routes(app, state, require_auth):
    app.register_blueprint(toast_bp)
    _wrap_registered_blueprint_routes(app, toast_bp.name, require_auth)
