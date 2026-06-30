# Auto-added feature: RapidAI/RapidOCR (3500 stars)
# Description: Cross-platform OCR engine using ONNX Runtime for text detection, recognition, and table extraction
# Source: https://github.com/RapidAI/RapidOCR

import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "RapidAI/RapidOCR",
    "stars": 3500,
    "desc": "Cross-platform OCR engine using ONNX Runtime for text detection, recognition, and table extraction",
    "url": "https://github.com/RapidAI/RapidOCR",
    "added": "2026-06-30",
    "command": "rapidocr -img <image>",
}


def _find_rapidocr():
    return shutil.which("rapidocr") or shutil.which("rapidocr.exe")


def _clean_image(value):
    image = str(value or "").strip()
    if not image:
        raise ValueError("image must not be empty")
    if "\x00" in image:
        raise ValueError("image cannot contain null bytes")
    return image


def _clean_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def register_routes(app, state, require_auth):
    @app.route("/auto/rapidocr/info", methods=["GET"])
    @require_auth
    def route_auto_rapidocr_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/rapidocr/ping", methods=["GET"])
    @require_auth
    def route_auto_rapidocr_ping():
        exe = _find_rapidocr()
        return jsonify({
            "status": "ok",
            "feature": "RapidAI/RapidOCR",
            "available": bool(exe),
            "command": exe or "rapidocr",
        })

    @app.route("/auto/rapidocr/ocr", methods=["POST"])
    @require_auth
    def route_auto_rapidocr_ocr():
        data = _json_body()
        missing = _missing_field(data, "image")
        if missing:
            return missing

        exe = _find_rapidocr()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "rapidocr command not found on PATH",
                "hint": "Install RapidOCR with `pip install rapidocr onnxruntime`.",
            }), 503

        try:
            image = _clean_image(data.get("image"))
            visualize = _clean_bool(data.get("visualize"))
            timeout = max(1, min(int(data.get("timeout", 60)), 300))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        command = [exe, "-img", image]
        if visualize:
            command.append("--vis_res")

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
            _log(f"[rapidocr] OCR timed out after {timeout}s image={image}")
            return jsonify({
                "ok": False,
                "error": f"rapidocr OCR timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[rapidocr] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[rapidocr] OCR exit={result.returncode} image={image}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "image": image,
            "visualize": visualize,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
