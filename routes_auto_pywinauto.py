# Auto-added feature: nickie/pywinauto (5200 stars)
# Python GUI automation for Windows — send mouse/keyboard, manage windows and controls via UIA and Win32 APIs
# Source: https://github.com/nickie/pywinauto

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "nickie/pywinauto",
  "stars": 5200,
  "desc": "Python GUI automation for Windows \u2014 send mouse/keyboard, manage windows and controls via UIA and Win32 APIs",
  "url": "https://github.com/nickie/pywinauto",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/pywinauto/info", methods=["GET"])
    @require_auth
    def route_auto_pywinauto_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/pywinauto/ping", methods=["GET"])
    @require_auth
    def route_auto_pywinauto_ping():
        return jsonify({"status": "ok", "feature": "nickie/pywinauto"})