# Auto-added feature: hluk/CopyQ (11956 stars)
# Description: Clipboard manager with advanced features and scripting
# Source: https://github.com/hluk/CopyQ

import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "hluk/CopyQ",
    "stars": 11956,
    "desc": "Clipboard manager with advanced features — manage clipboard history, copy/paste text, search, and scripting via copyq CLI",
    "url": "https://github.com/hluk/CopyQ",
    "added": "2026-07-05",
    "command": "copyq <subcommand>",
}


def _find_copyq():
    return shutil.which("copyq") or shutil.which("copyq.exe")


def _is_copyq_running():
    exe = _find_copyq()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "eval", "true"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_text(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("text must not be empty")
    if "\x00" in text:
        raise ValueError("text cannot contain null bytes")
    return text


def register_routes(app, state, require_auth):
    @app.route("/auto/copyq/info", methods=["GET"])
    @require_auth
    def route_auto_copyq_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/copyq/ping", methods=["GET"])
    @require_auth
    def route_auto_copyq_ping():
        exe = _find_copyq()
        running = _is_copyq_running() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "hluk/CopyQ",
            "available": bool(exe),
            "running": running,
            "command": exe or "copyq",
        })

    @app.route("/auto/copyq/clipboard", methods=["GET"])
    @require_auth
    def route_auto_copyq_clipboard_get():
        exe = _find_copyq()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "copyq command not found on PATH",
                "hint": "Install CopyQ from https://hluk.github.io/CopyQ/",
            }), 503

        try:
            result = subprocess.run(
                [exe, "clipboard"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except OSError as exc:
            _log(f"[copyq] clipboard read failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "copyq clipboard read timed out"}), 504

        ok = result.returncode == 0
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "text": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502

    @app.route("/auto/copyq/clipboard", methods=["POST"])
    @require_auth
    def route_auto_copyq_clipboard_set():
        data = _json_body()
        missing = _missing_field(data, "text")
        if missing:
            return missing

        exe = _find_copyq()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "copyq command not found on PATH",
                "hint": "Install CopyQ from https://hluk.github.io/CopyQ/",
            }), 503

        try:
            text = _clean_text(data.get("text"))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        try:
            result = subprocess.run(
                [exe, "copy", text],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except OSError as exc:
            _log(f"[copyq] clipboard write failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "copyq clipboard write timed out"}), 504

        ok = result.returncode == 0
        _log(f"[copyq] clipboard write exit={result.returncode} length={len(text)}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "length": len(text),
            "stderr": result.stderr,
        }), 200 if ok else 502

    @app.route("/auto/copyq/history", methods=["GET"])
    @require_auth
    def route_auto_copyq_history():
        exe = _find_copyq()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "copyq command not found on PATH",
                "hint": "Install CopyQ from https://hluk.github.io/CopyQ/",
            }), 503

        try:
            limit = max(1, min(int(request.args.get("limit", 10)), 100))
        except (TypeError, ValueError):
            limit = 10

        command = [exe, "separator", "\\n---\\n",
                   "read", str(min(limit - 1, 99)), "0"]

        try:
            result = subprocess.run(
                [exe, "eval",
                 "--",
                 f"var items = []; "
                 f"for (var i = 0; i < min(size(), {limit}); ++i) {{ "
                 f"  items.push(str(read(i))); "
                 f"}}",
                 "items.join('\\n---SEPARATOR---\\n')"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except OSError as exc:
            _log(f"[copyq] history failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "copyq history timed out"}), 504

        ok = result.returncode == 0
        if not ok:
            return jsonify({
                "ok": False,
                "exit_code": result.returncode,
                "stderr": result.stderr,
            }), 502

        items = [item.strip()
                 for item in result.stdout.split("\n---SEPARATOR---\n")
                 if item.strip()]
        return jsonify({
            "ok": True,
            "count": len(items),
            "items": items,
            "exit_code": result.returncode,
            "stderr": result.stderr,
        })

    @app.route("/auto/copyq/eval", methods=["POST"])
    @require_auth
    def route_auto_copyq_eval():
        """Execute arbitrary CopyQ script expression."""
        data = _json_body()
        missing = _missing_field(data, "script")
        if missing:
            return missing

        exe = _find_copyq()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "copyq command not found on PATH",
                "hint": "Install CopyQ from https://hluk.github.io/CopyQ/",
            }), 503

        try:
            script = _clean_text(data.get("script"))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        try:
            result = subprocess.run(
                [exe, "eval", "--", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[copyq] eval timed out after 10s script={script[:80]}")
            return jsonify({
                "ok": False,
                "error": "copyq eval timed out",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[copyq] eval failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[copyq] eval exit={result.returncode}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
