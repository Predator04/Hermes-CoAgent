"""Cua Driver integration routes."""

from flask import jsonify

from shared import _json_body, _log, _missing_field

try:
    from cua_bridge import cua_available, cua_call, cua_status
except ImportError as _cua_import_error:
    _CUA_IMPORT_ERROR = _cua_import_error

    def cua_available():
        return False

    def cua_status():
        return {"available": False, "error": str(_CUA_IMPORT_ERROR)}

    def cua_call(tool, data):
        raise FileNotFoundError(f"CUA bridge unavailable: {_CUA_IMPORT_ERROR}")
else:
    _CUA_IMPORT_ERROR = None


def _safe_json_body():
    """Parse JSON body, returning (data, None) or (None, error_tuple)."""
    try:
        return _json_body(), None
    except Exception as e:
        return None, (jsonify({"error": "Invalid JSON body", "detail": str(e)}), 400)


def _route_call(tool, data, success_status="ok"):
    try:
        result = cua_call(tool, data)
        if not isinstance(result, dict) or not result.get("ok"):
            err = result.get("error") if isinstance(result, dict) else None
            _log(f"[CUA] {tool} failed: {err!r}")
            return jsonify(result), 502
        _log(f"[CUA] {tool} ok")
        return jsonify({**result, "status": success_status})
    except FileNotFoundError as exc:
        _log(f"[CUA] {tool} unavailable: {exc}")
        return jsonify({"ok": False, "tool": tool, "error": str(exc)}), 503
    except Exception as exc:
        _log(f"[CUA] {tool} error: {exc}")
        return jsonify({"ok": False, "tool": tool, "error": str(exc)}), 500


def register_routes(app, state, require_auth):
    @app.route("/cua/status", methods=["GET"])
    @require_auth
    def route_cua_status():
        try:
            status = cua_status()
            _log(f"[CUA] status available={status.get('available')}")
            return jsonify(status)
        except Exception as exc:
            _log(f"[CUA] status error: {exc}")
            return jsonify({"available": False, "error": str(exc)}), 500

    @app.route("/cua/click", methods=["POST"])
    @require_auth
    def route_cua_click():
        data, err = _safe_json_body()
        if err:
            return err
        return _route_call("click", data, "clicked")

    @app.route("/cua/move", methods=["POST"])
    @require_auth
    def route_cua_move():
        data, err = _safe_json_body()
        if err:
            return err
        if data.get("x") is None:
            return _missing_field("x")
        if data.get("y") is None:
            return _missing_field("y")
        return _route_call("move_cursor", data, "moved")

    @app.route("/cua/type", methods=["POST"])
    @require_auth
    def route_cua_type():
        data, err = _safe_json_body()
        if err:
            return err
        if not data.get("text"):
            return _missing_field("text")
        return _route_call("type_text", data, "typed")

    @app.route("/cua/screenshot", methods=["POST"])
    @require_auth
    def route_cua_screenshot():
        data, err = _safe_json_body()
        if err:
            return err
        if data.get("pid") is None or data.get("window_id") is None:
            return jsonify({
                "ok": False,
                "error": "Cua screenshot requires pid and window_id",
                "hint": "Use /cua/status to inspect tools or /screen/fresh for full desktop capture.",
            }), 400
        payload = dict(data)
        payload.setdefault("capture_mode", "vision")
        return _route_call("get_window_state", payload, "screenshot")

    @app.route("/cua/available", methods=["GET"])
    @require_auth
    def route_cua_available():
        return jsonify({"available": cua_available()})
