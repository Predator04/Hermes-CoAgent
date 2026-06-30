# Auto-added feature: openinterpreter/open-interpreter (58000 stars)
# Natural language computer control — lets LLMs run code and control the desktop
# Source: https://github.com/openinterpreter/open-interpreter

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "openinterpreter/open-interpreter",
  "stars": 58000,
  "desc": "Natural language computer control \u2014 lets LLMs run code and control the desktop",
  "url": "https://github.com/openinterpreter/open-interpreter",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/open_interpreter/info", methods=["GET"])
    @require_auth
    def route_auto_open_interpreter_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/open_interpreter/ping", methods=["GET"])
    @require_auth
    def route_auto_open_interpreter_ping():
        return jsonify({"status": "ok", "feature": "openinterpreter/open-interpreter"})