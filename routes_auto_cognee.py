# Auto-added feature: topoteretes/cognee (1800 stars)
# Description: Definitive data management for AI agents: memory, knowledge graphs, and RAG pipelines
# Source: https://github.com/topoteretes/cognee

import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "topoteretes/cognee",
    "stars": 1800,
    "desc": "Definitive data management for AI agents: memory, knowledge graphs, and RAG pipelines",
    "url": "https://github.com/topoteretes/cognee",
    "added": "2026-06-30",
    "command": "cognee-cli recall",
}


def _find_cognee_cli():
    return shutil.which("cognee-cli") or shutil.which("cognee-cli.exe")


def _clean_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{field} cannot contain null bytes")
    return value.strip()


def register_routes(app, state, require_auth):
    @app.route("/auto/cognee/info", methods=["GET"])
    @require_auth
    def route_auto_cognee_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/cognee/ping", methods=["GET"])
    @require_auth
    def route_auto_cognee_ping():
        exe = _find_cognee_cli()
        return jsonify({
            "status": "ok",
            "feature": "topoteretes/cognee",
            "available": bool(exe),
            "command": exe or "cognee-cli",
        })

    @app.route("/auto/cognee/recall", methods=["POST"])
    @require_auth
    def route_auto_cognee_recall():
        data = _json_body()
        if not isinstance(data, dict) or "query" not in data:
            return _missing_field("query")

        exe = _find_cognee_cli()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "cognee-cli command not found on PATH",
                "hint": "Install Cognee with `uv pip install cognee` or `pip install cognee`.",
            }), 503

        try:
            query = _clean_text(data.get("query"), "query")
            timeout = max(1, min(int(data.get("timeout", 60)), 300))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        if query.startswith("-"):
            return jsonify({"ok": False, "error": "query must not look like a CLI flag"}), 400

        command = [exe, "recall", query]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[cognee] recall timed out after {timeout}s")
            return jsonify({
                "ok": False,
                "error": f"cognee-cli recall timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[cognee] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[cognee] recall exit={result.returncode}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
