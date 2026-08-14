# Auto-added feature: horsicq/Detect-It-Easy (11337 stars)
# File type identifier / packer & compiler detector (PE, ELF, APK, IPA, JAR, archives...) via signature + heuristic analysis
# Source: https://github.com/horsicq/Detect-It-Easy
# Install: winget install horsicq.DIE-engine  OR  scoop install detect-it-easy

import glob
import os
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "horsicq/Detect-It-Easy",
    "stars": 11337,
    "desc": "Detect It Easy (DiE) is a powerful file type identification tool popular among malware analysts and reverse engineers. It identifies file format, compiler, packer/protector, and linker via combined signature + heuristic analysis. The console build 'diec' (batch mode) emits machine-readable JSON (-j), XML (-x), CSV (-c) or plain text. Use it to fingerprint binaries before deeper analysis.",
    "url": "https://github.com/horsicq/Detect-It-Easy",
    "added": "2026-08-13",
    "command": "diec.exe [-j] [-d] [-u] [-r] [-i] <file-or-directory>",
    "install": {
        "winget": "winget install horsicq.DIE-engine",
        "scoop": "scoop install detect-it-easy",
    },
    "endpoints": {
        "/auto/detect_it_easy/info": "Feature metadata, install status, version",
        "/auto/detect_it_easy/ping": "Health check",
        "/auto/detect_it_easy/detect": "POST — fingerprint a file or directory (json, deep, heuristic, recursive, info)",
    },
}


def _find_diec():
    """Locate diec (Detect It Easy console) on this system."""
    for name in ("diec.exe", "diec"):
        exe = shutil.which(name)
        if exe:
            return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\horsicq.DIE-engine_*\diec.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\diec.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\detect-it-easy\*\diec.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\die-engine\*\diec.exe"),
        r"C:\Program Files\Detect It Easy\diec.exe",
        r"C:\Program Files (x86)\Detect It Easy\diec.exe",
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
    for flag in ("--version", "-v"):
        try:
            r = subprocess.run([exe, flag], capture_output=True, text=True, timeout=5,
                               encoding="utf-8", errors="replace")
            out = (r.stdout.strip() or r.stderr.strip())
            if out:
                first = out.split("\n")[0].strip()
                return first
        except Exception:
            pass
    return "unknown"


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def register_routes(app, state, require_auth):
    @app.route("/auto/detect_it_easy/info", methods=["GET"])
    @require_auth
    def route_auto_detect_it_easy_info():
        info = dict(FEATURE_INFO)
        exe = _find_diec()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/detect_it_easy/ping", methods=["GET"])
    @require_auth
    def route_auto_detect_it_easy_ping():
        exe = _find_diec()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "horsicq/Detect-It-Easy",
            "path": exe,
        })

    @app.route("/auto/detect_it_easy/detect", methods=["POST"])
    @require_auth
    def route_auto_detect_it_easy_detect():
        """Fingerprint a file or directory.
        Body: {"path": "C:\\sample.exe", "json": true, "deep": false, "heuristic": false, "recursive": false, "info": false}
        """
        body = _json_body()
        if not isinstance(body, dict):
            return _missing_field("path")
        target = body.get("path")
        if not target:
            return _missing_field("path")

        target = os.path.expandvars(os.path.expanduser(str(target)))
        if target.startswith("-"):
            return jsonify({"error": "path must not look like a CLI flag"}), 400
        if not os.path.exists(target):
            return jsonify({"error": f"Path does not exist: {target}"}), 404

        json_out = _as_bool(body.get("json"), True)
        deep = _as_bool(body.get("deep"), False)
        heuristic = _as_bool(body.get("heuristic"), False)
        recursive = _as_bool(body.get("recursive"), False)
        info_only = _as_bool(body.get("info"), False)

        exe = _find_diec()
        if not exe:
            return jsonify({
                "error": "diec (Detect It Easy console) not installed",
                "hint": "Install with: winget install horsicq.DIE-engine   OR   scoop install detect-it-easy",
            }), 503

        try:
            cmd = [exe]
            if json_out:
                cmd.append("-j")
            if deep:
                cmd.append("-d")
            if heuristic:
                cmd.append("-u")
            if recursive:
                cmd.append("-r")
            if info_only:
                cmd.append("-i")
            cmd.append(target)

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace")

            if r.returncode != 0 and not r.stdout:
                _log("die_detect", f"diec exited {r.returncode}: {r.stderr.strip()}")
                return jsonify({"error": r.stderr.strip() or "diec scan failed"}), 500

            return jsonify({
                "target": target,
                "is_dir": os.path.isdir(target),
                "exit_code": r.returncode,
                "format": "json" if json_out else "plaintext",
                "deep": deep,
                "heuristic": heuristic,
                "recursive": recursive,
                "result": (r.stdout or "").strip() or (r.stderr or "").strip(),
            })
        except subprocess.TimeoutExpired:
            _log("die_detect", f"detect on {target} timed out")
            return jsonify({"error": "diec scan timed out after 60s", "target": target}), 504
        except Exception as e:
            _log("die_detect", f"Error detecting {target}: {e}")
            return jsonify({"error": str(e), "target": target}), 500
