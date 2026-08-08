# Auto-added feature: obsproject/obs-studio (62000 stars)
# Open-source streaming/recording software — scene composition, source filters, transitions, and capture cards
# Source: https://github.com/obsproject/obs-studio

from flask import jsonify

FEATURE_INFO = {
  "repo": "obsproject/obs-studio",
  "stars": 62000,
  "desc": "Open-source streaming/recording software \u2014 scene composition, source filters, transitions, and capture cards",
  "url": "https://github.com/obsproject/obs-studio",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/obs_studio/info", methods=["GET"])
    @require_auth
    def route_auto_obs_studio_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/obs_studio/ping", methods=["GET"])
    @require_auth
    def route_auto_obs_studio_ping():
        return jsonify({"status": "ok", "feature": "obsproject/obs-studio"})