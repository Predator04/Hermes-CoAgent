# Auto-added feature: microsoft/playwright (72000 stars)
# Cross-browser automation framework — reliable end-to-end testing with auto-waiting and browser context isolation
# Source: https://github.com/microsoft/playwright

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "microsoft/playwright",
  "stars": 72000,
  "desc": "Cross-browser automation framework \u2014 reliable end-to-end testing with auto-waiting and browser context isolation",
  "url": "https://github.com/microsoft/playwright",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/playwright/info", methods=["GET"])
    @require_auth
    def route_auto_playwright_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/playwright/ping", methods=["GET"])
    @require_auth
    def route_auto_playwright_ping():
        return jsonify({"status": "ok", "feature": "microsoft/playwright"})