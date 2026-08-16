# Auto-added feature: eza-community/eza (22950 stars)
# A modern, maintained replacement for 'ls' — JSON output, git awareness, icons
# Source: https://github.com/eza-community/eza
# Install: winget install eza-community.eza  OR  scoop install eza

import os
import glob
import json
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "eza-community/eza",
    "stars": 22950,
    "desc": "eza is a modern, maintained replacement for the 'ls' command. Written in Rust, it adds git-awareness, icons, colors, tree view, and machine-readable --json output — ideal for programmatic directory enumeration from CoAgent.",
    "url": "https://github.com/eza-community/eza",
    "added": "2026-08-16",
    "command": "eza --long --git --icons [PATH]",
    "install": {
        "winget": "winget install eza-community.eza",
        "scoop": "scoop install eza",
    },
}


def _find_tool():
    """Locate the eza executable on this system."""
    exe = shutil.which("eza")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\eza-community.eza_*\eza.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\eza-community.eza_*\bin\eza.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\eza\current\eza.exe"),
        r"C:\Program Files\eza\eza.exe",
    ]
    for c in candidates:
        matches = glob.glob(c)
        if matches:
            return matches[0]
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/eza/info", methods=["GET"])
    @require_auth
    def route_auto_eza_info():
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
        return jsonify(info)

    @app.route("/auto/eza/ping", methods=["GET"])
    @require_auth
    def route_auto_eza_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "eza-community/eza",
            "path": exe,
        })

    @app.route("/auto/eza/list", methods=["GET", "POST"])
    @require_auth
    def route_auto_eza_list():
        """List directory contents via eza, with optional JSON output.

        GET params or JSON body:
            path (str, optional): Directory to list. Defaults to current dir.
            long (bool, optional): Detailed listing with size/permissions. Default True.
            git (bool, optional): Show git status per file. Default True.
            icons (bool, optional): Show file-type icons. Default False.
            all (bool, optional): Include hidden files. Default False.
            tree (bool, optional): Recursive tree view (implies --long). Default False.
            json (bool, optional): Return machine-readable JSON. Default True.
            sort (str, optional): Sort field: name|size|time|ext|none. Default 'name'.
            max_depth (int, optional): Tree depth when tree=True. Default 3.
            max_entries (int, optional): Cap returned entries. Default 500.
        """
        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "eza is not installed",
                "hint": "Install with: winget install eza-community.eza",
                "entries": [],
            }), 503

        if request.method == "POST":
            data = _json_body() or {}
        else:
            data = {k: v for k, v in request.args.items()}

        path = data.get("path", ".") or "."
        if not os.path.isdir(path):
            return jsonify({"error": f"Path does not exist or is not a directory: {path}", "entries": []}), 400

        use_json = str(data.get("json", "true")).lower() in ("1", "true", "yes")
        use_long = str(data.get("long", "true")).lower() in ("1", "true", "yes")
        use_tree = str(data.get("tree", "false")).lower() in ("1", "true", "yes")

        cmd = [exe, "--color", "never"]

        # --json implies --long in eza
        if use_json:
            cmd.append("--json")
        elif use_long:
            cmd.append("--long")

        if str(data.get("git", "true")).lower() in ("1", "true", "yes"):
            cmd.append("--git")
        if str(data.get("icons", "false")).lower() in ("1", "true", "yes"):
            cmd.append("--icons")
        if str(data.get("all", "false")).lower() in ("1", "true", "yes"):
            cmd.append("--all")

        sort = (data.get("sort") or "name").lower()
        sort_map = {"name": "--sort=Name", "size": "--sort=size", "time": "--sort=modified",
                    "ext": "--sort=extension", "none": "--sort=none"}
        if sort in sort_map:
            cmd.append(sort_map[sort])

        if use_tree:
            cmd.append("--tree")
            try:
                cmd.extend(["--level", str(max(1, min(int(data.get("max_depth", 3)), 10)))])
            except (ValueError, TypeError):
                cmd.extend(["--level", "3"])

        cmd.append("--")
        cmd.append(path)

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                _log("auto_eza_list", f"eza exited {r.returncode}: {r.stderr[:300]}")
                return jsonify({"error": r.stderr.strip() or "eza failed", "entries": []}), 500

            try:
                max_entries = max(1, min(int(data.get("max_entries", 500)), 5000))
            except (ValueError, TypeError):
                max_entries = 500

            if use_json:
                entries = json.loads(r.stdout) if r.stdout.strip() else []
                if not isinstance(entries, list):
                    entries = [entries]
                total = len(entries)
                entries = entries[:max_entries]
                return jsonify({"path": path, "total": total, "returned": len(entries), "entries": entries})
            else:
                lines = [l for l in r.stdout.split("\n") if l]
                total = len(lines)
                lines = lines[:max_entries]
                return jsonify({"path": path, "total": total, "returned": len(lines), "entries": lines})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "eza timed out after 30s", "entries": []}), 504
        except json.JSONDecodeError:
            return jsonify({"error": "eza returned non-JSON output", "entries": []}), 500
        except Exception as e:
            _log("auto_eza_list", f"Unexpected error: {e}")
            return jsonify({"error": str(e), "entries": []}), 500
