# Auto-added feature: ajeetdsouza/zoxide (38583 stars)
# A smarter cd command that remembers your most-used directories
# Source: https://github.com/ajeetdsouza/zoxide
# Install: winget install ajeetdsouza.zoxide  OR  scoop install zoxide

import glob
import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ajeetdsouza/zoxide",
    "stars": 38583,
    "desc": "zoxide is a smarter cd command, inspired by z and autojump. It remembers which directories you use most frequently, so you can jump to them in just a few keystrokes. Supports fzf integration for interactive selection.",
    "url": "https://github.com/ajeetdsouza/zoxide",
    "added": "2026-08-10",
    "command": "zoxide [query|add|remove|init] [args]",
    "install": {
        "winget": "winget install ajeetdsouza.zoxide",
        "scoop": "scoop install zoxide",
    },
    "endpoints": {
        "/auto/zoxide/info": "Feature metadata, install status, version",
        "/auto/zoxide/ping": "Health check",
        "/auto/zoxide/query": "POST — find best-matching directory for a pattern",
        "/auto/zoxide/list": "GET — list all tracked directories ranked by frecency",
    },
}

def _find_zoxide():
    """Locate zoxide on this system."""
    exe = shutil.which("zoxide")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\ajeetdsouza.zoxide_*\zoxide.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\zoxide.exe"),
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
    @app.route("/auto/zoxide/info", methods=["GET"])
    @require_auth
    def route_auto_zoxide_info():
        info = dict(FEATURE_INFO)
        exe = _find_zoxide()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/zoxide/ping", methods=["GET"])
    @require_auth
    def route_auto_zoxide_ping():
        exe = _find_zoxide()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "ajeetdsouza/zoxide",
            "path": exe,
        })

    @app.route("/auto/zoxide/query", methods=["POST"])
    @require_auth
    def route_auto_zoxide_query():
        """Query best-matching directory. Body: {"keywords": "project"}"""
        body = _json_body()
        keywords = body.get("keywords", "")

        if not keywords or not keywords.strip():
            return jsonify({"error": "'keywords' is required"}), 400

        exe = _find_zoxide()
        if not exe:
            return jsonify({
                "error": "zoxide not installed",
                "hint": "Install with: winget install ajeetdsouza.zoxide",
            }), 503

        try:
            # zoxide query <keywords> returns the single best match
            r = subprocess.run(
                [exe, "query", str(keywords).strip()],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                err = r.stderr.strip() or "No match found"
                _log("zoxide query no match", f"keywords={keywords}: {err}")
                # zoxide returns exit code 1 when no match — not a server error
                return jsonify({"match": None, "keywords": keywords, "hint": err})

            match = r.stdout.strip()
            return jsonify({
                "match": match,
                "keywords": keywords,
                "exists": os.path.isdir(match) if match else False,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "zoxide query timed out"}), 504
        except Exception as e:
            _log("zoxide query exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/zoxide/list", methods=["GET"])
    @require_auth
    def route_auto_zoxide_list():
        """List all tracked directories ranked by frecency (most-used first)."""
        exe = _find_zoxide()
        if not exe:
            return jsonify({
                "error": "zoxide not installed",
                "hint": "Install with: winget install ajeetdsouza.zoxide",
            }), 503

        try:
            # zoxide query -l lists all entries with scores
            r = subprocess.run(
                [exe, "query", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                _log("zoxide list error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "zoxide list failed"}), 500

            entries = []
            for line in r.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.strip().split(None, 1)
                if len(parts) >= 2:
                    try:
                        score = float(parts[0])
                    except (ValueError, TypeError):
                        score = 0
                    entries.append({"score": score, "path": parts[1]})
                else:
                    entries.append({"score": 0, "path": parts[0]})

            return jsonify({
                "entries": entries,
                "total": len(entries),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "zoxide list timed out"}), 504
        except Exception as e:
            _log("zoxide list exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/zoxide/add", methods=["POST"])
    @require_auth
    def route_auto_zoxide_add():
        """Add a directory to zoxide's database. Body: {"path": "/some/dir"}"""
        body = _json_body()
        dir_path = body.get("path", "")

        if not dir_path or not dir_path.strip():
            return jsonify({"error": "'path' is required"}), 400

        exe = _find_zoxide()
        if not exe:
            return jsonify({
                "error": "zoxide not installed",
                "hint": "Install with: winget install ajeetdsouza.zoxide",
            }), 503

        dir_path = os.path.abspath(dir_path.strip())
        if not os.path.isdir(dir_path):
            return jsonify({"error": f"Directory not found: {dir_path}"}), 404

        try:
            r = subprocess.run(
                [exe, "add", dir_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                _log("zoxide add error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "zoxide add failed"}), 500

            return jsonify({
                "added": dir_path,
                "status": "ok",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "zoxide add timed out"}), 504
        except Exception as e:
            _log("zoxide add exception", str(e))
            return jsonify({"error": str(e)}), 500
