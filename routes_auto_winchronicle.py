# Auto-added feature: YSCJRH/WinChronicle (1 stars)
# Local-first Windows UI Automation memory for AI agents
# Source: https://github.com/YSCJRH/WinChronicle

from flask import jsonify

FEATURE_INFO = {
  "repo": "YSCJRH/WinChronicle",
  "stars": 1,
  "desc": "Local-first Windows UI Automation memory for AI agents",
  "url": "https://github.com/YSCJRH/WinChronicle",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/winchronicle/info", methods=["GET"])
    @require_auth
    def route_auto_winchronicle_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/winchronicle/ping", methods=["GET"])
    @require_auth
    def route_auto_winchronicle_ping():
        return jsonify({"status": "ok", "feature": "YSCJRH/WinChronicle"})