# Auto-added feature: sharkdp/fd (44020 stars)
# A simple, fast and user-friendly alternative to 'find' — blazing fast file search
# Source: https://github.com/sharkdp/fd
# Install: winget install sharkdp.fd  OR  scoop install fd  OR  choco install fd

import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "sharkdp/fd",
    "stars": 44020,
    "desc": "fd is a simple, fast and user-friendly alternative to the 'find' command. It respects .gitignore, uses smart case-sensitivity, and is blazingly fast. Written in Rust.",
    "url": "https://github.com/sharkdp/fd",
    "added": "2026-08-09",
    "command": "fd [PATTERN] [PATH]",
    "install": {
        "winget": "winget install sharkdp.fd",
        "scoop": "scoop install fd",
        "choco": "choco install fd",
    },
}


def _find_tool():
    """Locate fd on this system."""
    exe = shutil.which("fd")
    if exe:
        return exe
    # Check common install locations
    candidates = [
        r"C:\Program Files\fd\fd.exe",
        r"C:\Program Files (x86)\fd\fd.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\sharkdp.fd_*\fd.exe"),
    ]
    for c in candidates:
        # Wildcard expansion for winget path
        import glob
        matches = glob.glob(c)
        if matches:
            return matches[0]
    for c in [r"C:\Program Files\fd\fd.exe", r"C:\Program Files (x86)\fd\fd.exe"]:
        if os.path.isfile(c):
            return c
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/fd/info", methods=["GET"])
    @require_auth
    def route_auto_fd_info():
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

    @app.route("/auto/fd/ping", methods=["GET"])
    @require_auth
    def route_auto_fd_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "sharkdp/fd",
            "path": exe,
        })

    @app.route("/auto/fd/search", methods=["GET", "POST"])
    @require_auth
    def route_auto_fd_search():
        """Search for files by name pattern using fd.

        GET params or JSON body:
            pattern (str): File name pattern to search for (supports regex, glob, exact)
            path (str, optional): Directory to search in. Defaults to CWD.
            type (str, optional): 'f' for files, 'd' for directories, 'l' for symlinks
            extension (str, optional): Filter by file extension (e.g. 'py', 'txt')
            case_sensitive (bool, optional): Force case-sensitive search. Default: smart case.
            max_depth (int, optional): Maximum directory depth to search.
            max_results (int, optional): Maximum results to return. Default 200.
            absolute (bool, optional): Show absolute paths. Default False.
            hidden (bool, optional): Search hidden files/dirs too. Default False.
            list_details (bool, optional): Show detailed listing. Default False.
        """
        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "fd is not installed",
                "hint": "Install with: winget install sharkdp.fd",
                "results": [],
            }), 503

        # Parse args from GET or POST
        if request.method == "POST":
            data = _json_body() or {}
        else:
            data = {k: v for k, v in request.args.items()}

        pattern = data.get("pattern", "").strip()
        if not pattern:
            return jsonify({"error": "Missing 'pattern' parameter", "results": []}), 400

        search_path = data.get("path", ".")
        if not os.path.isdir(search_path):
            return jsonify({"error": f"Path does not exist or is not a directory: {search_path}", "results": []}), 400

        # Build fd command
        cmd = [exe]

        # Type filter
        ftype = data.get("type")
        if ftype in ("f", "d", "l", "x", "e"):
            cmd.extend(["--type", ftype])

        # Extension filter
        ext = data.get("extension")
        if ext:
            cmd.extend(["--extension", ext.lstrip(".")])

        # Case sensitivity
        if data.get("case_sensitive"):
            cmd.append("--case-sensitive")

        # Max depth
        max_depth = data.get("max_depth")
        if max_depth is not None:
            try:
                cmd.extend(["--max-depth", str(int(max_depth))])
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid max_depth value: {max_depth}", "results": []}), 400

        # Max results
        max_results = data.get("max_results", 200)
        try:
            max_results = min(int(max_results), 5000)
        except (ValueError, TypeError):
            max_results = 200

        # Absolute paths
        if data.get("absolute"):
            cmd.append("--absolute-path")

        # Hidden files
        if data.get("hidden"):
            cmd.append("--hidden")

        # No ignore (search everything including .gitignored)
        if data.get("no_ignore"):
            cmd.append("--no-ignore")

        # List details
        if data.get("list_details"):
            cmd.extend(["--list-details"])

        # Strip prefix for cleaner output
        cmd.extend(["--strip-cwd-prefix"])

        # -- separator prevents argument injection
        cmd.append("--")
        cmd.append(pattern)
        cmd.append(search_path)

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0 and r.returncode != 1:
                # Exit code 1 = no results found (normal)
                _log("auto_fd_search", f"fd exited with code {r.returncode}: {r.stderr[:500]}")
                return jsonify({
                    "error": r.stderr.strip() or "fd search failed",
                    "results": [],
                }), 500

            lines = [l for l in r.stdout.strip().split("\n") if l]
            total = len(lines)
            lines = lines[:max_results]

            return jsonify({
                "pattern": pattern,
                "path": search_path,
                "total": total,
                "returned": len(lines),
                "results": lines,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "fd search timed out after 30s", "results": []}), 504
        except FileNotFoundError:
            return jsonify({
                "error": "fd executable not found",
                "hint": "Install with: winget install sharkdp.fd",
                "results": [],
            }), 503
        except Exception as e:
            _log("auto_fd_search", f"Unexpected error: {e}")
            return jsonify({"error": str(e), "results": []}), 500
