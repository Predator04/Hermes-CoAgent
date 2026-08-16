# Auto-added feature: Aider-AI/aider (48267 stars)
# AI pair programming in your terminal — delegate coding tasks headlessly
# Source: https://github.com/Aider-AI/aider
# Install: pip install aider-install  OR  pipx install aider-install  OR  uv tool install aider-install

import os
import glob
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "Aider-AI/aider",
    "stars": 48267,
    "desc": "aider is AI pair programming in your terminal. It edits code in a local git repo using LLMs (OpenAI, Anthropic, DeepSeek, local models). Can run headlessly with --yes --message for fully automated code edits.",
    "url": "https://github.com/Aider-AI/aider",
    "added": "2026-08-16",
    "command": "aider --yes --no-git --message \"<prompt>\"",
    "install": {
        "pip": "pip install aider-install",
        "pipx": "pipx install aider-install",
        "uv": "uv tool install aider-install",
    },
}


def _find_tool():
    """Locate the aider executable on this system."""
    exe = shutil.which("aider")
    if exe:
        return exe
    # Common pip / pipx install locations on Windows
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\Scripts\aider.exe"),
        os.path.expandvars(r"%APPDATA%\Python\Python*\Scripts\aider.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\bin\aider.exe"),
        os.path.expandvars(r"%USERPROFILE%\pipx\venvs\aider-chat\Scripts\aider.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\AiderAI.Aider_*\aider.exe"),
    ]
    for c in candidates:
        matches = glob.glob(c)
        if matches:
            return matches[0]
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/aider/info", methods=["GET"])
    @require_auth
    def route_auto_aider_info():
        info = dict(FEATURE_INFO)
        exe = _find_tool()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15)
                info["version"] = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
            except Exception:
                info["version"] = "unknown"
        return jsonify(info)

    @app.route("/auto/aider/ping", methods=["GET"])
    @require_auth
    def route_auto_aider_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "Aider-AI/aider",
            "path": exe,
        })

    @app.route("/auto/aider/run", methods=["POST"])
    @require_auth
    def route_auto_aider_run():
        """Run aider headlessly against a git repo with a coding prompt.

        JSON body:
            cwd (str, required): Directory containing the code to edit.
            message (str, required): The coding task / prompt for the LLM.
            model (str, optional): Model to use (e.g. 'gpt-4o', 'claude-3-5-sonnet', 'deepseek').
                                   Defaults to aider's configured model.
            auto_commit (bool, optional): Let aider git-commit its edits. Default False.
            timeout (int, optional): Max seconds to wait. Default 300, max 1800.

        Requires an LLM API key in the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY,
        DEEPSEEK_API_KEY, etc.) or aider's ~/.aider.conf.yml.
        """
        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "aider is not installed",
                "hint": "Install with: pip install aider-install  (or pipx/uv)",
            }), 503

        data = _json_body() or {}
        cwd = (data.get("cwd") or "").strip()
        message = (data.get("message") or "").strip()

        if not cwd:
            return jsonify({"error": "Missing 'cwd' field"}), 400
        if not message:
            return jsonify({"error": "Missing 'message' field"}), 400
        if not os.path.isdir(cwd):
            return jsonify({"error": f"cwd does not exist or is not a directory: {cwd}"}), 400

        model = (data.get("model") or "").strip()
        timeout = data.get("timeout", 300)
        try:
            timeout = max(10, min(int(timeout), 1800))
        except (ValueError, TypeError):
            timeout = 300

        cmd = [exe, "--yes"]
        if not data.get("auto_commit"):
            cmd += ["--no-git", "--no-auto-commits"]
        if model:
            cmd += ["--model", model]
        cmd += ["--message", message]

        try:
            r = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
            return jsonify({
                "ok": r.returncode == 0,
                "returncode": r.returncode,
                "cwd": cwd,
                "model": model or "default",
                "stdout": r.stdout[-4000:],
                "stderr": r.stderr[-4000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": f"aider timed out after {timeout}s", "cwd": cwd}), 504
        except Exception as e:
            _log("auto_aider_run", f"Unexpected error: {e}")
            return jsonify({"error": str(e)}), 500
