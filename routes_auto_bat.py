# Auto-added feature: sharkdp/bat (60141 stars)
# A cat clone with syntax highlighting and Git integration
# Source: https://github.com/sharkdp/bat
# Install: winget install sharkdp.bat  OR  scoop install bat

import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "sharkdp/bat",
    "stars": 60141,
    "desc": "bat is a cat clone with syntax highlighting, line numbers, Git integration, and paging. Supports hundreds of languages and ships with themes.",
    "url": "https://github.com/sharkdp/bat",
    "added": "2026-08-08",
    "command": "bat [OPTIONS] [FILE]",
    "install": {
        "winget": "winget install sharkdp.bat",
        "scoop": "scoop install bat",
        "choco": "choco install bat",
    },
}

def _find_tool():
    """Locate bat on this system."""
    exe = shutil.which("bat")
    if exe:
        return exe
    # Check common install locations
    candidates = [
        r"C:\Program Files\bat\bat.exe",
        r"C:\Program Files (x86)\bat\bat.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\sharkdp.bat_*\bat.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/bat/info", methods=["GET"])
    @require_auth
    def route_auto_bat_info():
        info = dict(FEATURE_INFO)
        exe = _find_tool()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                info["version"] = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
            except Exception:
                info["version"] = "unknown"
            # List available themes
            try:
                r2 = subprocess.run([exe, "--list-themes"], capture_output=True, text=True, timeout=5)
                info["themes"] = [t.strip() for t in r2.stdout.strip().split("\n") if t.strip() and not t.startswith("Theme:")]
                info["theme_count"] = len(info["themes"])
            except Exception:
                info["themes"] = []
                info["theme_count"] = 0
        return jsonify(info)

    @app.route("/auto/bat/ping", methods=["GET"])
    @require_auth
    def route_auto_bat_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "sharkdp/bat",
            "path": exe,
        })

    @app.route("/auto/bat/cat", methods=["POST"])
    @require_auth
    def route_auto_bat_cat():
        """Read a file with bat syntax highlighting (plain text output)."""
        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "bat not installed",
                "hint": "Install with: winget install sharkdp.bat",
            }), 503

        body = _json_body(request)
        filepath = body.get("file")
        if not filepath:
            return _missing_field("file")

        if not os.path.isfile(filepath):
            return jsonify({"error": f"File not found: {filepath}"}), 404

        try:
            max_lines = int(body.get("max_lines", 500))
        except (TypeError, ValueError):
            max_lines = 500
        max_lines = max(0, max_lines)
        line_range = body.get("line_range", None)  # e.g. "10:30"
        show_line_numbers = body.get("line_numbers", True)
        language = body.get("language", None)  # force language override
        theme = body.get("theme", "ansi")

        cmd = [exe, "--color=never", "--paging=never", "--style=full" if show_line_numbers else "--style=plain"]
        if line_range:
            cmd.extend(["--line-range", line_range])
        if language:
            cmd.extend(["--language", language])
        if theme and theme != "ansi":
            cmd.extend(["--theme", theme])

        cmd.append(filepath)

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            lines = r.stdout.split("\n")
            total = len(lines)
            truncated = total > max_lines
            return jsonify({
                "file": filepath,
                "lines": lines[:max_lines],
                "total_lines": total,
                "truncated": truncated,
                "language": language or "auto",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "bat timed out reading file"}), 504

    @app.route("/auto/bat/languages", methods=["GET"])
    @require_auth
    def route_auto_bat_languages():
        """List all supported languages."""
        exe = _find_tool()
        if not exe:
            return jsonify({"error": "bat not installed"}), 503

        try:
            r = subprocess.run([exe, "--list-languages"], capture_output=True, text=True, timeout=5)
            languages = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
            return jsonify({"languages": languages, "count": len(languages)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/bat/themes", methods=["GET"])
    @require_auth
    def route_auto_bat_themes():
        """List all available themes."""
        exe = _find_tool()
        if not exe:
            return jsonify({"error": "bat not installed"}), 503

        try:
            r = subprocess.run([exe, "--list-themes"], capture_output=True, text=True, timeout=5)
            themes = [t.strip() for t in r.stdout.strip().split("\n") if t.strip()]
            return jsonify({"themes": themes, "count": len(themes)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
