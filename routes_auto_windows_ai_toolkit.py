# Auto-added feature: microsoft/windows-ai-toolkit (1200 stars)
# Windows AI integration tools and MCP servers for desktop automation on Windows
# Source: https://github.com/microsoft/windows-ai-toolkit

from flask import jsonify

FEATURE_INFO = {
  "repo": "microsoft/windows-ai-toolkit",
  "stars": 1200,
  "desc": "Windows AI integration tools and MCP servers for desktop automation on Windows",
  "url": "https://github.com/microsoft/windows-ai-toolkit",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/windows_ai_toolkit/info", methods=["GET"])
    @require_auth
    def route_auto_windows_ai_toolkit_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/windows_ai_toolkit/ping", methods=["GET"])
    @require_auth
    def route_auto_windows_ai_toolkit_ping():
        return jsonify({"status": "ok", "feature": "microsoft/windows-ai-toolkit"})