# Auto-added feature: BurntSushi/ripgrep (67118 stars)
# Recursively search directories for regex patterns — blazing fast grep alternative
# Source: https://github.com/BurntSushi/ripgrep
# Install: winget install BurntSushi.ripgrep.MSVC  OR  scoop install ripgrep

import shutil
import subprocess
import json
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "BurntSushi/ripgrep",
    "stars": 67118,
    "desc": "ripgrep recursively searches directories for a regex pattern while respecting gitignore rules. Blazing fast grep alternative written in Rust.",
    "url": "https://github.com/BurntSushi/ripgrep",
    "added": "2026-08-08",
    "command": "rg [PATTERN] [PATH]",
    "install": {
        "winget": "winget install BurntSushi.ripgrep.MSVC",
        "scoop": "scoop install ripgrep",
        "choco": "choco install ripgrep",
    },
}

def _find_tool():
    """Locate rg on this system."""
    exe = shutil.which("rg")
    if exe:
        return exe
    # Check common install locations
    candidates = [
        r"C:\Program Files\ripgrep\rg.exe",
        r"C:\Program Files (x86)\ripgrep\rg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\BurntSushi.ripgrep.MSVC_*\rg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/ripgrep/info", methods=["GET"])
    @require_auth
    def route_auto_ripgrep_info():
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

    @app.route("/auto/ripgrep/ping", methods=["GET"])
    @require_auth
    def route_auto_ripgrep_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "BurntSushi/ripgrep",
            "path": exe,
        })

    @app.route("/auto/ripgrep/search", methods=["POST"])
    @require_auth
    def route_auto_ripgrep_search():
        """Execute ripgrep search with pattern and optional path."""
        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "ripgrep not installed",
                "hint": "Install with: winget install BurntSushi.ripgrep.MSVC",
            }), 503

        body = _json_body()
        pattern = body.get("pattern")
        if not pattern:
            return _missing_field("pattern")

        search_path = body.get("path", ".")
        try:
            max_lines = int(body.get("max_lines", 200))
        except (TypeError, ValueError):
            return jsonify({"error": "max_lines must be an integer"}), 400
        case_sensitive = body.get("case_sensitive", False)
        file_glob = body.get("file_glob", None)
        max_depth = body.get("max_depth", None)
        if max_depth is not None:
            try:
                max_depth = int(max_depth)
            except (TypeError, ValueError):
                return jsonify({"error": "max_depth must be an integer"}), 400

        cmd = [exe, "--no-heading", "--line-number", "--color", "never", "--max-count", str(max_lines)]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if file_glob:
            cmd.extend(["--glob", file_glob])
        if max_depth is not None:
            cmd.extend(["--max-depth", str(max_depth)])

        cmd.extend(["--", pattern, search_path])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
            lines = [l for l in r.stdout.strip().split("\n") if l]
            truncated = len(lines) >= max_lines
            result = {
                "pattern": pattern,
                "path": search_path,
                "matches": lines[:max_lines],
                "count": len(lines[:max_lines]),
                "truncated": truncated,
            }
            if r.returncode == 1:
                result["count"] = 0
                result["matches"] = []
            elif r.returncode > 1:
                return jsonify({"error": r.stderr.strip()}), 400
            return jsonify(result)
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Search timed out after 30s"}), 504

    @app.route("/auto/ripgrep/count", methods=["POST"])
    @require_auth
    def route_auto_ripgrep_count():
        """Count matches for a pattern."""
        exe = _find_tool()
        if not exe:
            return jsonify({"error": "ripgrep not installed"}), 503

        body = _json_body()
        pattern = body.get("pattern")
        if not pattern:
            return _missing_field("pattern")

        search_path = body.get("path", ".")
        file_glob = body.get("file_glob", None)

        cmd = [exe, "--count", "--no-heading", "--", pattern, search_path]
        if file_glob:
            cmd.extend(["--glob", file_glob])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
            results = {}
            total = 0
            for line in r.stdout.strip().split("\n"):
                if ":" in line:
                    fname, count_str = line.rsplit(":", 1)
                    try:
                        count = int(count_str)
                        results[fname] = count
                        total += count
                    except ValueError:
                        continue
            return jsonify({"pattern": pattern, "path": search_path, "file_counts": results, "total_matches": total})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Count timed out after 30s"}), 504

    @app.route("/auto/ripgrep/files", methods=["POST"])
    @require_auth
    def route_auto_ripgrep_files():
        """List files that would be searched (rg --files)."""
        exe = _find_tool()
        if not exe:
            return jsonify({"error": "ripgrep not installed"}), 503

        body = _json_body() if request.is_json else {}
        search_path = body.get("path", ".")
        file_glob = body.get("file_glob", None)
        try:
            max_results = int(body.get("max_results", 500))
        except (TypeError, ValueError):
            return jsonify({"error": "max_results must be an integer"}), 400

        cmd = [exe, "--files", "--", search_path]
        if file_glob:
            cmd.extend(["--glob", file_glob])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=os.getcwd())
            files = [f for f in r.stdout.strip().split("\n") if f]
            return jsonify({"path": search_path, "files": files[:max_results], "count": len(files[:max_results])})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "File listing timed out"}), 504
