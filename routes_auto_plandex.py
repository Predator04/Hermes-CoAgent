# Auto-added feature: plandex-ai/plandex (11000 stars)
# AI coding agent for terminal — plans and builds large-scale software changes autonomously
# Source: https://github.com/plandex-ai/plandex

from flask import jsonify

FEATURE_INFO = {
  "repo": "plandex-ai/plandex",
  "stars": 11000,
  "desc": "AI coding agent for terminal \u2014 plans and builds large-scale software changes autonomously",
  "url": "https://github.com/plandex-ai/plandex",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/plandex/info", methods=["GET"])
    @require_auth
    def route_auto_plandex_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/plandex/ping", methods=["GET"])
    @require_auth
    def route_auto_plandex_ping():
        return jsonify({"status": "ok", "feature": "plandex-ai/plandex"})