# Auto-added feature: iBotPeaches/Apktool (21000 stars)
# APK reverse engineering tool — decode resources to nearly original form, rebuild after modification
# Source: https://github.com/iBotPeaches/Apktool

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "iBotPeaches/Apktool",
  "stars": 21000,
  "desc": "APK reverse engineering tool \u2014 decode resources to nearly original form, rebuild after modification",
  "url": "https://github.com/iBotPeaches/Apktool",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/apktool/info", methods=["GET"])
    @require_auth
    def route_auto_apktool_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/apktool/ping", methods=["GET"])
    @require_auth
    def route_auto_apktool_ping():
        return jsonify({"status": "ok", "feature": "iBotPeaches/Apktool"})