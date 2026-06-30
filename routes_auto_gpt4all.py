# Auto-added feature: nomic-ai/gpt4all (72000 stars)
# Local LLM inference on CPU — GPT4All runs models locally on any machine without GPU
# Source: https://github.com/nomic-ai/gpt4all

from flask import jsonify
from shared import _log

FEATURE_INFO = {
  "repo": "nomic-ai/gpt4all",
  "stars": 72000,
  "desc": "Local LLM inference on CPU \u2014 GPT4All runs models locally on any machine without GPU",
  "url": "https://github.com/nomic-ai/gpt4all",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/gpt4all/info", methods=["GET"])
    @require_auth
    def route_auto_gpt4all_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/gpt4all/ping", methods=["GET"])
    @require_auth
    def route_auto_gpt4all_ping():
        return jsonify({"status": "ok", "feature": "nomic-ai/gpt4all"})