# Auto-added feature: microsoft/PowerToys (115000 stars)
# Windows system utilities — FancyZones, PowerRename, Keyboard Manager, and advanced window management tools
# Source: https://github.com/microsoft/PowerToys

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "microsoft/PowerToys",
  "stars": 115000,
  "desc": "Windows system utilities \u2014 FancyZones, PowerRename, Keyboard Manager, and advanced window management tools",
  "url": "https://github.com/microsoft/PowerToys",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/powertoys/info", methods=["GET"])
    @require_auth
    def route_auto_powertoys_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/powertoys/ping", methods=["GET"])
    @require_auth
    def route_auto_powertoys_ping():
        return jsonify({"status": "ok", "feature": "microsoft/PowerToys"})