"""v7.3 feature routes: cursor overlay, recording, waits, and stabilization."""
from flask import jsonify
from shared import _json_body


def _call_feature(name, *args):
    """Invoke a ``coagent_features`` function, returning 501 if it is not implemented.

    The ``coagent_features`` module is populated dynamically at runtime (see
    ``routes_media._install_record_action_hook``). Features such as ``wait_element``
    or ``cursor_set_style`` may not exist yet; degrade to 501 instead of raising an
    AttributeError that surfaces as a misleading HTTP 500.
    """
    import coagent_features as cf
    fn = getattr(cf, name, None)
    if fn is None:
        return jsonify({"error": f"feature '{name}' is not implemented"}), 501
    return jsonify(fn(*args))


def _coerce_bool(value):
    """Coerce a JSON value to a boolean.

    Unlike ``bool(value)``, this treats the strings ``"false"``/``"0"``/``"no"``/``"off"``
    as False so string-encoded booleans are not silently inverted to True.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def register_routes(app, state, require_auth):
    @app.route("/features", methods=["GET"])
    @require_auth
    def route_features():
        try:
            import coagent_features as cf
            return jsonify(cf.get_status() if hasattr(cf, "get_status") else {
                "cursor": cf.cursor_get_status() if hasattr(cf, "cursor_get_status") else False,
                "recording": cf.recording_status() if hasattr(cf, "recording_status") else False,
            })
        except Exception as e:
            return jsonify({"error": str(e), "cursor": False, "recording": False}), 500

    @app.route("/wait/element", methods=["POST"])
    @require_auth
    def route_wait_element():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            query = d.get("query", "")
            if not query or not isinstance(query, str) or len(query) > 200:
                return jsonify({"error": "Invalid or missing 'query' field"}), 400
            return _call_feature("wait_element", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/wait/element-gone", methods=["POST"])
    @require_auth
    def route_wait_element_gone():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            return _call_feature("wait_element_gone", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/stabilize", methods=["POST"])
    @require_auth
    def route_stabilize():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            return _call_feature("stabilize_action", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/enable", methods=["POST"])
    @require_auth
    def route_cursor_enable():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            if "enable" in d and "enabled" not in d:
                d["enabled"] = _coerce_bool(d["enable"])
            return _call_feature("cursor_set_enabled", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/style", methods=["POST"])
    @require_auth
    def route_cursor_style():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            return _call_feature("cursor_set_style", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/status", methods=["GET"])
    @require_auth
    def route_cursor_status():
        try:
            return _call_feature("cursor_get_status")
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/start", methods=["POST"])
    @require_auth
    def route_recording_start():
        try:
            d = _json_body()
            if not isinstance(d, dict):
                return jsonify({"error": "Request body must be a JSON object"}), 400
            return _call_feature("recording_start", d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/stop", methods=["POST"])
    @require_auth
    def route_recording_stop():
        try:
            return _call_feature("recording_stop")
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/status", methods=["GET"])
    @require_auth
    def route_recording_status():
        try:
            return _call_feature("recording_status")
        except Exception as e:
            return jsonify({"error": str(e)}), 500
