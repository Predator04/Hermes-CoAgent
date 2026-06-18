"""v7.3 feature routes: cursor overlay, recording, waits, and stabilization."""
from flask import jsonify
from shared import _json_body


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
        d = _json_body()
        query = d.get("query", "")
        if not query or not isinstance(query, str) or len(query) > 200:
            return jsonify({"error": "Invalid or missing 'query' field"}), 400
        try:
            import coagent_features as cf
            return jsonify(cf.wait_element(d))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/wait/element-gone", methods=["POST"])
    @require_auth
    def route_wait_element_gone():
        d = _json_body()
        try:
            import coagent_features as cf
            return jsonify(cf.wait_element_gone(d))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/stabilize", methods=["POST"])
    @require_auth
    def route_stabilize():
        d = _json_body()
        try:
            import coagent_features as cf
            return jsonify(cf.stabilize_action(d))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/enable", methods=["POST"])
    @require_auth
    def route_cursor_enable():
        d = _json_body()
        if "enable" in d and "enabled" not in d:
            d["enabled"] = d["enable"]
        try:
            import coagent_features as cf
            return jsonify(cf.cursor_set_enabled(d))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/style", methods=["POST"])
    @require_auth
    def route_cursor_style():
        try:
            import coagent_features as cf
            return jsonify(cf.cursor_set_style(_json_body()))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/cursor/status", methods=["GET"])
    @require_auth
    def route_cursor_status():
        try:
            import coagent_features as cf
            return jsonify(cf.cursor_get_status())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/start", methods=["POST"])
    @require_auth
    def route_recording_start():
        try:
            import coagent_features as cf
            return jsonify(cf.recording_start(_json_body()))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/stop", methods=["POST"])
    @require_auth
    def route_recording_stop():
        try:
            import coagent_features as cf
            return jsonify(cf.recording_stop())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/recording/status", methods=["GET"])
    @require_auth
    def route_recording_status():
        try:
            import coagent_features as cf
            return jsonify(cf.recording_status())
        except Exception as e:
            return jsonify({"error": str(e)}), 500
