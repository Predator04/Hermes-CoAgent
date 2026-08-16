# Auto-added feature: junegunn/fzf (82485 stars)
# A command-line fuzzy finder — filter lists, files, processes with fuzzy matching
# Source: https://github.com/junegunn/fzf
# Install: winget install junegunn.fzf  OR  scoop install fzf

import glob
import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "junegunn/fzf",
    "stars": 82485,
    "desc": "fzf is a general-purpose command-line fuzzy finder. Filter anything — files, processes, command history, git branches — with interactive fuzzy matching. Supports --filter for non-interactive mode ideal for automation pipelines.",
    "url": "https://github.com/junegunn/fzf",
    "added": "2026-08-10",
    "command": "fzf [--filter PATTERN] [--height LINES] [--multi]",
    "install": {
        "winget": "winget install junegunn.fzf",
        "scoop": "scoop install fzf",
    },
    "endpoints": {
        "/auto/fzf/info": "Feature metadata, install status, version",
        "/auto/fzf/ping": "Health check",
        "/auto/fzf/filter": "POST — fuzzy-filter a list of strings against a query",
        "/auto/fzf/search": "POST — fuzzy-search a directory tree for matching files",
    },
}

def _find_fzf():
    """Locate fzf on this system."""
    exe = shutil.which("fzf")
    if exe:
        return exe
    # Check common install locations
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\junegunn.fzf_*\fzf.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\fzf.exe"),
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
        # fzf outputs version as first line like "0.55.0 (brew)" or similar
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):
    @app.route("/auto/fzf/info", methods=["GET"])
    @require_auth
    def route_auto_fzf_info():
        info = dict(FEATURE_INFO)
        exe = _find_fzf()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/fzf/ping", methods=["GET"])
    @require_auth
    def route_auto_fzf_ping():
        exe = _find_fzf()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "junegunn/fzf",
            "path": exe,
        })

    @app.route("/auto/fzf/filter", methods=["POST"])
    @require_auth
    def route_auto_fzf_filter():
        """Fuzzy-filter a list of strings. Body: {"query": "pattern", "items": ["str1", "str2", ...]}"""
        body = _json_body()
        query = body.get("query", "")
        items = body.get("items", [])

        if not isinstance(items, list):
            return jsonify({"error": "'items' must be a list of strings"}), 400

        exe = _find_fzf()
        if not exe:
            return jsonify({
                "error": "fzf not installed",
                "hint": "Install with: winget install junegunn.fzf",
            }), 503

        try:
            # fzf --filter does non-interactive matching — perfect for automation
            stdin = "\n".join(str(i) for i in items)
            r = subprocess.run(
                [exe, "--filter", str(query)],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=15,
            )
            # Return code 1 = no matches (not a real error in fzf)
            if r.returncode == 1:
                return jsonify({"matches": [], "query": query, "total_input": len(items)})
            if r.returncode != 0:
                _log("fzf filter error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "fzf filter failed"}), 500

            matches = [m for m in r.stdout.strip().split("\n") if m]
            return jsonify({
                "matches": matches,
                "query": query,
                "total_input": len(items),
                "total_matches": len(matches),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "fzf filter timed out"}), 504
        except Exception as e:
            _log("fzf filter exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/fzf/search", methods=["POST"])
    @require_auth
    def route_auto_fzf_search():
        """Fuzzy-search a directory. Body: {"query": "pattern", "path": "/some/dir", "type": "f|d|all"}"""
        body = _json_body()
        query = body.get("query", "")
        search_path = body.get("path", ".")
        file_type = body.get("type", "all")  # f=files, d=dirs, all=both

        exe = _find_fzf()
        if not exe:
            return jsonify({
                "error": "fzf not installed",
                "hint": "Install with: winget install junegunn.fzf",
            }), 503

        if not os.path.isdir(search_path):
            return jsonify({"error": f"Directory not found: {search_path}"}), 404

        try:
            # Use fd or dir to list files, pipe to fzf --filter
            fd_exe = shutil.which("fd")
            if fd_exe:
                # fd is faster and respects .gitignore
                type_arg = [] if file_type == "all" else (["--type", file_type])
                list_cmd = [fd_exe, "--color", "never", "--hidden", "--no-ignore"]
                if type_arg:
                    list_cmd.extend(type_arg)
                list_cmd.append(".")
                r_list = subprocess.run(
                    list_cmd,
                    cwd=search_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                items = [l for l in r_list.stdout.strip().split("\n") if l]
            else:
                # Fallback: use dir /s /b on Windows, find on Linux
                if os.name == "nt":
                    dir_cmd = ["cmd", "/c", "dir", "/s", "/b"]
                    if file_type == "f":
                        dir_cmd.append("/a:-d")
                    r_list = subprocess.run(
                        dir_cmd,
                        cwd=search_path,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                else:
                    find_cmd = ["find", ".", "-maxdepth", "10"]
                    if file_type == "f":
                        find_cmd.extend(["-type", "f"])
                    elif file_type == "d":
                        find_cmd.extend(["-type", "d"])
                    r_list = subprocess.run(
                        find_cmd,
                        cwd=search_path,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                items = [l for l in r_list.stdout.strip().split("\n") if l]

            if not query:
                return jsonify({
                    "matches": items[:200],
                    "query": query,
                    "path": search_path,
                    "total_matches": len(items),
                    "truncated": len(items) > 200,
                })

            # Filter through fzf
            stdin = "\n".join(items)
            r = subprocess.run(
                [exe, "--filter", str(query)],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode == 1:
                return jsonify({"matches": [], "query": query, "path": search_path, "total_input": len(items)})
            if r.returncode != 0:
                _log("fzf search error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "fzf search failed"}), 500

            matches = [m for m in r.stdout.strip().split("\n") if m]
            return jsonify({
                "matches": matches[:200],
                "query": query,
                "path": search_path,
                "total_input": len(items),
                "total_matches": len(matches),
                "truncated": len(matches) > 200,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "fzf search timed out"}), 504
        except Exception as e:
            _log("fzf search exception", str(e))
            return jsonify({"error": str(e)}), 500
