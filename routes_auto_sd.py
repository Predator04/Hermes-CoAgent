# Auto-added feature: chmln/sd (7305 stars)
# Intuitive find & replace CLI (sed alternative) — JS-flavored regex, cross-platform
# Source: https://github.com/chmln/sd
# Install: winget install chmln.sd  OR  scoop install sd

import glob
import os
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "chmln/sd",
    "stars": 7305,
    "desc": "sd is an intuitive find & replace CLI (a friendlier sed alternative). It uses JavaScript-flavored regex, avoids sed's confusing escaping, and works across files, directories, and stdin — ideal for CoAgent to script safe text transformations with a built-in dry-run preview.",
    "url": "https://github.com/chmln/sd",
    "added": "2026-08-17",
    "command": "sd [--preview] [--fixed-strings] <find> <replace_with> [files...]",
    "install": {
        "winget": "winget install chmln.sd",
        "scoop": "scoop install sd",
    },
    "endpoints": {
        "/auto/sd/info": "Feature metadata, install status, version",
        "/auto/sd/ping": "Health check",
        "/auto/sd/replace": "POST — find & replace across a file, directory, or stdin text (with dry-run preview)",
    },
}


def _find_tool():
    """Locate the sd executable on this system."""
    exe = shutil.which("sd")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\chmln.sd_*\sd.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\sd.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\sd.exe"),
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
        if r.returncode != 0:
            return "unknown"
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip() or "unknown"
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):

    @app.route("/auto/sd/info", methods=["GET"])
    @require_auth
    def route_auto_sd_info():
        info = dict(FEATURE_INFO)
        exe = _find_tool()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/sd/ping", methods=["GET"])
    @require_auth
    def route_auto_sd_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "chmln/sd",
            "path": exe,
        })

    @app.route("/auto/sd/replace", methods=["POST"])
    @require_auth
    def route_auto_sd_replace():
        """Find & replace across a file, directory, or stdin text.

        Body (JSON):
            find (str, required): Pattern to find.
            replace (str, optional): Replacement text. Default "".
            path (str, optional): File or directory to edit in place. If omitted,
                `input` text is transformed via stdin and returned.
            input (str, optional): Text to transform via stdin (used when no path).
            preview (bool, optional): Dry-run — print changes without writing. Default True.
            fixed_strings (bool, optional): Treat `find` as a literal, not regex. Default False.
            flags (str, optional): Regex flags (e.g. "i" for case-insensitive). Default "".
        """
        body = _json_body()
        find = body.get("find")
        if find in (None, ""):
            return _missing_field(body, "find")
        replace = body.get("replace", "")
        path = body.get("path") or None
        input_text = body.get("input")
        preview = str(body.get("preview", "true")).lower() in ("1", "true", "yes")
        fixed_strings = str(body.get("fixed_strings", "false")).lower() in ("1", "true", "yes")
        flags = str(body.get("flags", "") or "")

        if not path and input_text is None:
            return jsonify({"error": "Either 'path' or 'input' is required"}), 400

        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "sd is not installed",
                "hint": "Install with: winget install chmln.sd",
            }), 503

        cmd = [exe]
        if preview:
            cmd.append("--preview")
        if fixed_strings:
            cmd.append("--fixed-strings")
        if flags:
            cmd.extend(["--flags", flags])
        cmd.append(find)
        cmd.append(replace)
        if path:
            cmd.append(path)

        try:
            r = subprocess.run(
                cmd,
                input=(input_text if not path else None),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                _log(f"auto_sd_replace: sd exited {r.returncode}: {r.stderr[:300]}")
                return jsonify({"error": r.stderr.strip() or "sd failed"}), 500

            out = r.stdout
            if path:
                # Preview mode prints the resulting content to stdout; write mode
                # edits in place and emits nothing.
                return jsonify({
                    "preview": preview,
                    "path": path,
                    "changed": bool(out.strip()) if preview else True,
                    "output_lines": out.count("\n") + (1 if out else 0),
                    "sample": out[:4000],
                })
            return jsonify({
                "preview": preview,
                "changed": out != input_text,
                "output": out,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "sd timed out after 60s"}), 504
        except Exception as e:
            _log(f"auto_sd_replace exception: {e}")
            return jsonify({"error": str(e)}), 500
