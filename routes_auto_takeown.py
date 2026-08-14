# Auto-added feature: microsoft/windows (built-in) — TakeOwn
# Description: takeown.exe — Windows file ownership recovery tool.
#   Recover access to files/folders by reassigning ownership to current
#   user or administrators group. Supports recursive, remote, and
#   wildcard-based ownership recovery.
# Source: Built-in Windows tool at C:\Windows\system32\takeown.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows file ownership recovery — take ownership of files/folders recursively, assign to current user or Administrators group, skip symlinks, operate on remote systems",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/takeown",
    "added": "2026-07-21",
    "command": "takeown /F <path> [/R] [/A] [/D Y|N] [/SKIPSL]",
}


def _find_takeown():
    """Locate takeown.exe — always in system32 on Windows."""
    exe = shutil.which("takeown") or shutil.which("takeown.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\takeown.exe",
        r"C:\Windows\SysWOW64\takeown.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_takeown_available():
    exe = _find_takeown()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_takeown(args, timeout=30):
    """Run takeown with given args, return (stdout, stderr, exit_code)."""
    exe = _find_takeown()
    if not exe:
        raise RuntimeError("takeown not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def register_routes(app, state, require_auth):
    @app.route("/auto/takeown/info", methods=["GET"])
    @require_auth
    def route_auto_takeown_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/takeown/ping", methods=["GET"])
    @require_auth
    def route_auto_takeown_ping():
        exe = _find_takeown()
        available = _is_takeown_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "takeown (built-in)",
            "available": available,
            "command": exe or "takeown",
        })

    @app.route("/auto/takeown/status", methods=["GET"])
    @require_auth
    def route_auto_takeown_status():
        """Check what takeown.exe is available for."""
        try:
            stdout, stderr, rc = _run_takeown(["/?"])
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "available": True,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "takeown check timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/takeown/take", methods=["POST"])
    @require_auth
    def route_auto_takeown_take():
        """Take ownership of a file or directory.
        
        Body:
          path (required): File or directory path
          recursive (optional, bool): Apply recursively to subdirectories
          admins (optional, bool): Give ownership to Administrators group instead of current user
          default_answer (optional, str): 'Y' or 'N' — default answer when no list-folder permission
          skipsl (optional, bool): Do not follow symbolic links (only with recursive)
        """
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        filepath = body.get("path", "")
        if not isinstance(filepath, str):
            return jsonify({"ok": False, "error": "path must be a string"}), 400
        filepath = filepath.strip()
        if not filepath:
            return _missing_field("path")
        if (
            filepath.startswith(("/", "-"))
            or "\x00" in filepath
            or "\n" in filepath
            or "\r" in filepath
            or '"' in filepath
        ):
            return jsonify({"ok": False, "error": "path must not contain flags, quotes, or newlines"}), 400

        args = ["/F", filepath]

        if body.get("recursive", False):
            args.append("/R")
            da = body.get("default_answer", "")
            if da and str(da).upper() in ("Y", "N"):
                args.extend(["/D", str(da).upper()])
            else:
                args.extend(["/D", "Y"])

        if body.get("admins", False):
            args.append("/A")

        if body.get("skipsl", False):
            args.append("/SKIPSL")

        try:
            stdout, stderr, rc = _run_takeown(args)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "path": filepath,
                "args": args,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "takeown timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
