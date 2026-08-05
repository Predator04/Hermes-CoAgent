# Auto-added feature: AnderssonPeter/SharpDxScreenCapture (400 stars)
# Description: High-performance screen capture for Windows using DirectX/SharpDX for low-latency frame grabbing
# Source: https://github.com/AnderssonPeter/SharpDxScreenCapture

import os
import shutil
import subprocess
from pathlib import Path

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "AnderssonPeter/SharpDxScreenCapture",
    "stars": 400,
    "desc": "High-performance screen capture for Windows using DirectX/SharpDX for low-latency frame grabbing",
    "url": "https://github.com/AnderssonPeter/SharpDxScreenCapture",
    "added": "2026-06-30",
    "command": "SharpDxScreenCapture.exe --output <file>",
}


def _find_sharpdx_capture():
    configured = os.environ.get("SHARPDXSCREENCAPTURE_EXE", "").strip()
    if configured and Path(configured).is_file():
        return configured
    return (
        shutil.which("SharpDxScreenCapture.exe")
        or shutil.which("SharpDxScreenCapture")
        or shutil.which("sharpdxscreencapture.exe")
        or shutil.which("sharpdxscreencapture")
    )


def _clean_output_path(value):
    output = str(value or "").strip()
    if not output:
        raise ValueError("output must not be empty")
    if "\x00" in output:
        raise ValueError("output cannot contain null bytes")
    suffix = Path(output).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp"}:
        raise ValueError("output must end with .png, .jpg, .jpeg, or .bmp")
    # Block path traversal — only allow relative filenames or paths within screenshots dir
    resolved = Path(output).resolve()
    try:
        resolved.relative_to(SCREENSHOTS_DIR.resolve())
    except ValueError:
        raise ValueError("output path must be within screenshots directory")
    return str(resolved)


def _optional_int(value, field, default, minimum, maximum):
    if value in (None, ""):
        return default
    number = int(value)
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return number


def register_routes(app, state, require_auth):
    @app.route("/auto/sharpdxscreencapture/info", methods=["GET"])
    @require_auth
    def route_auto_sharpdxscreencapture_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/sharpdxscreencapture/ping", methods=["GET"])
    @require_auth
    def route_auto_sharpdxscreencapture_ping():
        exe = _find_sharpdx_capture()
        return jsonify({
            "status": "ok",
            "feature": "AnderssonPeter/SharpDxScreenCapture",
            "available": bool(exe),
            "command": exe or "SharpDxScreenCapture.exe",
        })

    @app.route("/auto/sharpdxscreencapture/capture", methods=["POST"])
    @require_auth
    def route_auto_sharpdxscreencapture_capture():
        data = _json_body()
        missing = _missing_field(data, "output")
        if missing:
            return missing

        exe = _find_sharpdx_capture()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "SharpDxScreenCapture command not found on PATH",
                "hint": "Build the project and set SHARPDXSCREENCAPTURE_EXE to the executable path, or add it to PATH.",
            }), 503

        try:
            output = _clean_output_path(data.get("output"))
            adapter = _optional_int(data.get("adapter"), "adapter", 0, 0, 16)
            display = _optional_int(data.get("display"), "display", 0, 0, 16)
            timeout = _optional_int(data.get("timeout"), "timeout", 15, 1, 120)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        command = [
            exe,
            "--output",
            output,
            "--adapter",
            str(adapter),
            "--display",
            str(display),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[sharpdxscreencapture] timed out after {timeout}s output={output}")
            return jsonify({
                "ok": False,
                "error": f"SharpDxScreenCapture timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[sharpdxscreencapture] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[sharpdxscreencapture] exit={result.returncode} output={output}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "output": output,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
