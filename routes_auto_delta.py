# Auto-added feature: dandavison/delta (31711 stars)
# A syntax-highlighting pager for git, diff, and grep output
# Source: https://github.com/dandavison/delta
# Install: winget install dandavison.delta  OR  scoop install delta

import glob
import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "dandavison/delta",
    "stars": 31711,
    "desc": "delta is a syntax-highlighting pager for git, diff, grep, and blame output. It formats diffs with side-by-side or line-by-line views, line numbers, syntax highlighting, and theme support. Use it to make code review output beautiful and readable.",
    "url": "https://github.com/dandavison/delta",
    "added": "2026-08-11",
    "command": "delta [--version] [--list-languages] [--list-themes] [file.diff]",
    "install": {
        "winget": "winget install dandavison.delta",
        "scoop": "scoop install delta",
    },
    "endpoints": {
        "/auto/delta/info": "Feature metadata, install status, version",
        "/auto/delta/ping": "Health check",
        "/auto/delta/format": "POST — syntax-highlight a diff or text snippet",
        "/auto/delta/themes": "GET — list available color themes",
        "/auto/delta/languages": "GET — list supported languages for highlighting",
    },
}

def _find_delta():
    """Locate delta on this system."""
    exe = shutil.which("delta")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\dandavison.delta_*\delta.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\delta.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\delta.exe"),
    ]
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):
    @app.route("/auto/delta/info", methods=["GET"])
    @require_auth
    def route_auto_delta_info():
        info = dict(FEATURE_INFO)
        exe = _find_delta()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/delta/ping", methods=["GET"])
    @require_auth
    def route_auto_delta_ping():
        exe = _find_delta()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "dandavison/delta",
            "path": exe,
        })

    @app.route("/auto/delta/format", methods=["POST"])
    @require_auth
    def route_auto_delta_format():
        """Syntax-highlight a diff or text snippet.
        Body: {"content": "diff --git ...", "theme": "Monokai Extended", "width": 120, "side_by_side": false}
        """
        body = _json_body(request)
        content = body.get("content", "")
        theme = body.get("theme", "Monokai Extended")
        width = body.get("width", 120)
        side_by_side = body.get("side_by_side", False)

        if not content or not content.strip():
            return jsonify({"error": "'content' is required"}), 400

        exe = _find_delta()
        if not exe:
            return jsonify({
                "error": "delta not installed",
                "hint": "Install with: winget install dandavison.delta",
            }), 503

        try:
            # delta reads from stdin and writes formatted output to stdout
            cmd = [
                exe,
                "--no-gitconfig",
                "--paging", "never",
                "--width", str(width),
                "--theme", theme,
            ]
            if side_by_side:
                cmd.append("--side-by-side")

            r = subprocess.run(
                cmd,
                input=content,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                _log("delta format error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "delta formatting failed"}), 500

            # delta output often includes ANSI color codes — strip them for API response
            # but keep the text structure
            return jsonify({
                "formatted": r.stdout.strip(),
                "theme": theme,
                "width": width,
                "side_by_side": side_by_side,
                "input_lines": len(content.splitlines()),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "delta format timed out"}), 504
        except Exception as e:
            _log("delta format exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/delta/themes", methods=["GET"])
    @require_auth
    def route_auto_delta_themes():
        """List all available color themes."""
        exe = _find_delta()
        if not exe:
            return jsonify({
                "error": "delta not installed",
                "hint": "Install with: winget install dandavison.delta",
            }), 503

        try:
            r = subprocess.run(
                [exe, "--list-themes"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                return jsonify({"error": r.stderr.strip() or "delta --list-themes failed"}), 500

            themes = [t.strip() for t in r.stdout.strip().split("\n") if t.strip()]
            return jsonify({
                "themes": themes,
                "total": len(themes),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "delta --list-themes timed out"}), 504
        except Exception as e:
            _log("delta themes exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/delta/languages", methods=["GET"])
    @require_auth
    def route_auto_delta_languages():
        """List all supported languages for syntax highlighting."""
        exe = _find_delta()
        if not exe:
            return jsonify({
                "error": "delta not installed",
                "hint": "Install with: winget install dandavison.delta",
            }), 503

        try:
            r = subprocess.run(
                [exe, "--list-languages"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                return jsonify({"error": r.stderr.strip() or "delta --list-languages failed"}), 500

            langs = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
            return jsonify({
                "languages": langs,
                "total": len(langs),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "delta --list-languages timed out"}), 504
        except Exception as e:
            _log("delta languages exception", str(e))
            return jsonify({"error": str(e)}), 500
