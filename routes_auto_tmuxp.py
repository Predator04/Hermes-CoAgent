# Auto-added feature: tmux-python/tmuxp (5500 stars)
# Session manager for tmux — manage multiple terminal sessions with YAML configs and workspace restoration
# Source: https://github.com/tmux-python/tmuxp

from flask import jsonify

FEATURE_INFO = {
  "repo": "tmux-python/tmuxp",
  "stars": 5500,
  "desc": "Session manager for tmux \u2014 manage multiple terminal sessions with YAML configs and workspace restoration",
  "url": "https://github.com/tmux-python/tmuxp",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/tmuxp/info", methods=["GET"])
    @require_auth
    def route_auto_tmuxp_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/tmuxp/ping", methods=["GET"])
    @require_auth
    def route_auto_tmuxp_ping():
        return jsonify({"status": "ok", "feature": "tmux-python/tmuxp"})