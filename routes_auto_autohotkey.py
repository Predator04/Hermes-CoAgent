# Auto-added feature: AutoHotkey/AutoHotkey (12693 stars)
# Description: AutoHotkey - macro-creation and automation-oriented scripting utility for Windows
# Source: https://github.com/AutoHotkey/AutoHotkey

import os
import shutil
import subprocess
import tempfile

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "AutoHotkey/AutoHotkey",
    "stars": 12693,
    "desc": "AutoHotkey - macro-creation and automation-oriented scripting utility for Windows — run AHK scripts, compile, send keys, and control automation via AutoHotkey CLI",
    "url": "https://github.com/AutoHotkey/AutoHotkey",
    "added": "2026-07-06",
    "command": "AutoHotkey64.exe / AutoHotkey32.exe",
}


def _find_autohotkey():
    return (
        shutil.which("AutoHotkey64.exe")
        or shutil.which("AutoHotkey32.exe")
        or shutil.which("autohotkey64")
        or shutil.which("autohotkey32")
        or shutil.which("autohotkey")
    )


def _find_ahk2exe():
    return shutil.which("Ahk2Exe.exe") or shutil.which("ahk2exe")


def _is_autohotkey_available():
    exe = _find_autohotkey()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "/ErrorStdOut"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # AHK returns a usage/error message when run without a script
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_script(value):
    script = str(value or "").strip()
    if not script:
        raise ValueError("script must not be empty")
    if "\x00" in script:
        raise ValueError("script cannot contain null bytes")
    if len(script) > 65536:
        raise ValueError("script exceeds max length (65536 chars)")
    return script


def _clean_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def register_routes(app, state, require_auth):
    @app.route("/auto/autohotkey/info", methods=["GET"])
    @require_auth
    def route_auto_autohotkey_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/autohotkey/ping", methods=["GET"])
    @require_auth
    def route_auto_autohotkey_ping():
        exe = _find_autohotkey()
        available = _is_autohotkey_available() if exe else False
        compiler = _find_ahk2exe()
        return jsonify({
            "status": "ok",
            "feature": "AutoHotkey/AutoHotkey",
            "available": bool(exe),
            "running": available,
            "command": exe or "AutoHotkey64.exe",
            "compiler": bool(compiler),
        })

    @app.route("/auto/autohotkey/run", methods=["POST"])
    @require_auth
    def route_auto_autohotkey_run():
        data = _json_body()
        missing = _missing_field(data, "script")
        if missing:
            return missing

        exe = _find_autohotkey()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "AutoHotkey not found on PATH",
                "hint": "Install AutoHotkey from https://www.autohotkey.com/",
            }), 503

        try:
            script = _clean_script(data.get("script"))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        wait = _clean_bool(data.get("wait", True))
        timeout_sec = 30
        try:
            timeout_sec = max(1, min(int(data.get("timeout", 30)), 120))
        except (TypeError, ValueError):
            timeout_sec = 30

        tmp_ahk = None
        try:
            fd, tmp_ahk = tempfile.mkstemp(suffix=".ahk", prefix="coagent_")
            os.close(fd)
            with open(tmp_ahk, "w", encoding="utf-8") as f:
                f.write(script)

            cmd = [exe, tmp_ahk]
            if wait:
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout_sec,
                        shell=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    # Kill lingering AHK process
                    subprocess.run(
                        ["taskkill", "/f", "/im", os.path.basename(exe)],
                        capture_output=True,
                        timeout=3,
                    )
                    _log(f"[autohotkey] script timed out after {timeout_sec}s")
                    return jsonify({
                        "ok": False,
                        "error": "AutoHotkey script timed out",
                        "stdout": exc.stdout or "",
                        "stderr": exc.stderr or "",
                    }), 504
                except OSError as exc:
                    _log(f"[autohotkey] launch failed: {exc}")
                    return jsonify({"ok": False, "error": str(exc)}), 500

                ok = result.returncode == 0
                _log(f"[autohotkey] script exit={result.returncode}")
                return jsonify({
                    "ok": ok,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }), 200 if ok else 502
            else:
                # Fire-and-forget: launch detached, don't wait
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    )
                    _log(f"[autohotkey] launched detached pid={proc.pid}")
                    return jsonify({
                        "ok": True,
                        "pid": proc.pid,
                        "message": "Script launched in background",
                    })
                except OSError as exc:
                    _log(f"[autohotkey] detached launch failed: {exc}")
                    return jsonify({"ok": False, "error": str(exc)}), 500

        finally:
            if tmp_ahk and os.path.exists(tmp_ahk):
                try:
                    os.unlink(tmp_ahk)
                except OSError:
                    pass

    @app.route("/auto/autohotkey/compile", methods=["POST"])
    @require_auth
    def route_auto_autohotkey_compile():
        data = _json_body()
        missing = _missing_field(data, "script")
        if missing:
            return missing

        compiler = _find_ahk2exe()
        if not compiler:
            return jsonify({
                "ok": False,
                "error": "Ahk2Exe compiler not found",
                "hint": "Install AutoHotkey with compiler from https://www.autohotkey.com/",
            }), 503

        try:
            script = _clean_script(data.get("script"))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        out_name = str(data.get("output", "coagent_script.exe")).strip()
        if not out_name.endswith(".exe"):
            out_name += ".exe"

        tmp_ahk = None
        tmp_exe = None
        try:
            fd1, tmp_ahk = tempfile.mkstemp(suffix=".ahk", prefix="coagent_")
            os.close(fd1)
            with open(tmp_ahk, "w", encoding="utf-8") as f:
                f.write(script)

            tmp_exe = os.path.join(
                tempfile.gettempdir(),
                out_name,
            )

            cmd = [compiler, "/in", tmp_ahk, "/out", tmp_exe]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                _log("[autohotkey] compilation timed out")
                return jsonify({
                    "ok": False,
                    "error": "Compilation timed out after 60s",
                }), 504
            except OSError as exc:
                _log(f"[autohotkey] compiler launch failed: {exc}")
                return jsonify({"ok": False, "error": str(exc)}), 500

            ok = result.returncode == 0 and os.path.exists(tmp_exe)
            exe_size = os.path.getsize(tmp_exe) if ok else 0
            _log(f"[autohotkey] compile exit={result.returncode} size={exe_size}")
            return jsonify({
                "ok": ok,
                "exit_code": result.returncode,
                "output": tmp_exe,
                "size_bytes": exe_size,
                "stderr": result.stderr,
            }), 200 if ok else 502

        finally:
            for p in [tmp_ahk]:
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
