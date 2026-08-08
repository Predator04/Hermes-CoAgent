# Auto-added feature: NationalSecurityAgency/ghidra (54000 stars)
# NSA's reverse engineering framework — disassembly, decompilation, scripting, and binary analysis platform
# Source: https://github.com/NationalSecurityAgency/ghidra

from flask import jsonify

FEATURE_INFO = {
  "repo": "NationalSecurityAgency/ghidra",
  "stars": 54000,
  "desc": "NSA's reverse engineering framework \u2014 disassembly, decompilation, scripting, and binary analysis platform",
  "url": "https://github.com/NationalSecurityAgency/ghidra",
  "added": "2026-06-30"
}


def register_routes(app, state, require_auth):
    @app.route("/auto/ghidra/info", methods=["GET"])
    @require_auth
    def route_auto_ghidra_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/ghidra/ping", methods=["GET"])
    @require_auth
    def route_auto_ghidra_ping():
        return jsonify({"status": "ok", "feature": "NationalSecurityAgency/ghidra"})