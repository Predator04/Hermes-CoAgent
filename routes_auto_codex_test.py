# Auto-added feature: test/codex-test (100 stars)
# Description: test
# Source: https://github.com/test/codex-test

import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "test/codex-test",
    "stars": 100,
    "desc": "test",
    "url": "https://github.com/test/codex-test",
    "added": "2026-06-30",
    "command": "codex-test",
}


def _find_codex_test():
    return shutil.which("codex-test") or shutil.which("codex-test.exe")


def _normalize_args(args):
    if not isinstance(args, list):
        raise ValueError("args must be a list")

    normalized = []
    for arg in args:
        value = str(arg)
        if "\x00" in value:
            raise ValueError("args cannot contain null bytes")
        normalized.append(value)
    return normalized


def register_routes(app, state, require_auth):
    @app.route("/auto/codex_test/info", methods=["GET"])
    @require_auth
    def route_auto_codex_test_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/codex_test/ping", methods=["GET"])
    @require_auth
    def route_auto_codex_test_ping():
        exe = _find_codex_test()
        return jsonify({
            "status": "ok",
            "feature": "test/codex-test",
            "available": bool(exe),
            "command": exe or "codex-test",
        })

    @app.route("/auto/codex_test/run", methods=["POST"])
    @require_auth
    def route_auto_codex_test_run():
        data = _json_body()
        if "args" not in data:
            return _missing_field("args")

        exe = _find_codex_test()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "codex-test command not found on PATH",
                "hint": "Install test/codex-test and make the codex-test CLI available on PATH.",
            }), 503

        try:
            args = _normalize_args(data.get("args"))
            timeout = max(1, min(int(data.get("timeout", 30)), 120))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        command = [exe] + args
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[codex-test] timed out after {timeout}s: {args}")
            return jsonify({
                "ok": False,
                "error": f"codex-test timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[codex-test] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[codex-test] exit={result.returncode} args={args}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
