"""Android phone bridge routes using ADB."""

import base64
import re
import subprocess

from flask import Response, jsonify, request

from shared import COAGENT_DIR, _json_body


PHONE_SCREENSHOT = COAGENT_DIR / "phone.png"

# Allowed Android keycodes (common subset)
_KEYCODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


def _safe_int(val, default=0):
    """Safely coerce a value to int, returning default on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_timeout(val, default=30, max_val=300):
    """Safely coerce and clamp timeout value."""
    t = _safe_int(val, default)
    return max(1, min(t, max_val))


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _adb_base(data):
    args = ["adb"]
    serial = data.get("serial") or data.get("device")
    if serial:
        args.extend(["-s", str(serial)])
    return args


def _run_adb(data, args, timeout=30, binary=False):
    cmd = _adb_base(data) + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=not binary, timeout=timeout)
        if binary:
            stdout = proc.stdout
            stderr = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else str(proc.stderr)
        else:
            stdout = proc.stdout
            stderr = proc.stderr
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "ok": proc.returncode == 0,
        }
    except FileNotFoundError:
        return {"cmd": cmd, "returncode": None, "stdout": b"" if binary else "", "stderr": "adb.exe not found in PATH", "ok": False}
    except subprocess.TimeoutExpired as e:
        return {"cmd": cmd, "returncode": None, "stdout": e.stdout or (b"" if binary else ""), "stderr": "adb command timed out", "ok": False}
    except (ValueError, OSError) as e:
        return {"cmd": cmd, "returncode": None, "stdout": b"" if binary else "", "stderr": str(e), "ok": False}


def _json_result(result, status_ok=200):
    status = status_ok if result.get("ok") else 500
    safe = dict(result)
    if isinstance(safe.get("stdout"), bytes):
        safe["stdout_b64"] = base64.b64encode(safe.pop("stdout")).decode("ascii")
    return jsonify(safe), status


# Shell metacharacters rejected in adb text input. Single quote, glob chars, and
# control whitespace are unsafe because adb shell re-joins args and re-parses
# them through the on-device sh.
_FORBIDDEN_TEXT_CHARS = set(';&|`$<>(){}\'*?~[]#\t!\n\r')


def _input_text(text):
    value = str(text)
    # Reject shell metacharacters that could cause command injection via adb shell
    if any(ch in value for ch in _FORBIDDEN_TEXT_CHARS):
        return None  # caller should reject the request
    return value.replace("%", "%25").replace(" ", "%s").replace("\\", "\\\\").replace('"', '\\"')


def register_routes(app, state, require_auth):
    @app.route("/phone/list", methods=["POST", "GET"])
    @require_auth
    def route_phone_list():
        return _json_result(_run_adb({}, ["devices", "-l"], timeout=10))

    @app.route("/phone/screenshot", methods=["POST"])
    @require_auth
    def route_phone_screenshot():
        data = _json_body()
        result = _run_adb(data, ["exec-out", "screencap", "-p"], timeout=20, binary=True)
        if not result.get("ok"):
            return _json_result(result)
        raw = result.get("stdout", b"")
        PHONE_SCREENSHOT.write_bytes(raw)
        if request.args.get("raw") in {"1", "true", "yes"}:
            return Response(raw, mimetype="image/png")
        return jsonify({"status": "ok", "path": str(PHONE_SCREENSHOT), "bytes": len(raw), "png_b64": base64.b64encode(raw).decode("ascii")})

    @app.route("/phone/tap", methods=["POST"])
    @require_auth
    def route_phone_tap():
        data = _json_body()
        x = _safe_int(data.get("x"), 0)
        y = _safe_int(data.get("y"), 0)
        return _json_result(_run_adb(data, ["shell", "input", "tap", str(x), str(y)]))

    @app.route("/phone/type", methods=["POST"])
    @require_auth
    def route_phone_type():
        data = _json_body()
        text = data.get("text")
        if text is None:
            return _error("text is required")
        safe_text = _input_text(text)
        if safe_text is None:
            return _error("text contains unsafe characters")
        return _json_result(_run_adb(data, ["shell", "input", "text", safe_text]))

    @app.route("/phone/swipe", methods=["POST"])
    @require_auth
    def route_phone_swipe():
        data = _json_body()
        x1 = _safe_int(data.get("x1"), 0)
        y1 = _safe_int(data.get("y1"), 0)
        x2 = _safe_int(data.get("x2"), 0)
        y2 = _safe_int(data.get("y2"), 0)
        args = ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2)]
        if data.get("duration_ms") is not None:
            args.append(str(_safe_int(data.get("duration_ms"))))
        return _json_result(_run_adb(data, args))

    @app.route("/phone/key", methods=["POST"])
    @require_auth
    def route_phone_key():
        data = _json_body()
        keycode = data.get("keycode") or data.get("key")
        if keycode is None:
            return _error("keycode is required")
        keycode_str = str(keycode)
        if not _KEYCODE_PATTERN.match(keycode_str):
            return _error(f"invalid keycode: {keycode_str}")
        return _json_result(_run_adb(data, ["shell", "input", "keyevent", keycode_str]))

    @app.route("/phone/shell", methods=["POST"])
    @require_auth
    def route_phone_shell():
        data = _json_body()
        command = data.get("command")
        if isinstance(command, list):
            shell_args = ["shell", *[str(item) for item in command]]
        elif isinstance(command, str) and command.strip():
            shell_args = ["shell", command]
        else:
            return _error("command is required")
        return _json_result(_run_adb(data, shell_args, timeout=_safe_timeout(data.get("timeout"), 30)))

    @app.route("/phone/app/start", methods=["POST"])
    @require_auth
    def route_phone_app_start():
        data = _json_body()
        package = data.get("package")
        if not isinstance(package, str) or not package:
            return _error("package is required")
        if re.search(r'[;&|`$<>(){}\s]', package):
            return _error("invalid package name")
        return _json_result(_run_adb(data, ["shell", "monkey", "-p", package, "1"], timeout=20))

    @app.route("/phone/app/stop", methods=["POST"])
    @require_auth
    def route_phone_app_stop():
        data = _json_body()
        package = data.get("package")
        if not isinstance(package, str) or not package:
            return _error("package is required")
        if re.search(r'[;&|`$<>(){}\s]', package):
            return _error("invalid package name")
        return _json_result(_run_adb(data, ["shell", "am", "force-stop", package], timeout=20))

    @app.route("/phone/sms/read", methods=["POST"])
    @require_auth
    def route_phone_sms_read():
        data = _json_body()
        projection = data.get("projection", "address,date,type,body")
        uri = data.get("uri", "content://sms")
        # Validate URI starts with content:// and has no shell metacharacters
        uri_str = str(uri)
        if not uri_str.startswith("content://") or re.search(r'[;&|`$<>(){}\n\r]', uri_str):
            return _error("invalid URI")
        proj_str = str(projection)
        if re.search(r'[;&|`$<>(){}\n\r]', proj_str):
            return _error("invalid projection")
        result = _run_adb(data, ["shell", "content", "query", "--uri", uri_str, "--projection", proj_str, "--sort", "date DESC"], timeout=_safe_timeout(data.get("timeout"), 20))
        return _json_result(result)

    @app.route("/phone/status", methods=["POST", "GET"])
    @require_auth
    def route_phone_status():
        data = _json_body()
        if request.method == "GET":
            data = {**request.args.to_dict(), **data}
        battery = _run_adb(data, ["shell", "dumpsys", "battery"], timeout=10)
        signal = _run_adb(data, ["shell", "dumpsys", "telephony.registry"], timeout=10)
        wifi = _run_adb(data, ["shell", "dumpsys", "wifi"], timeout=10)
        model = _run_adb(data, ["shell", "getprop", "ro.product.model"], timeout=10)
        brand = _run_adb(data, ["shell", "getprop", "ro.product.brand"], timeout=10)
        android = _run_adb(data, ["shell", "getprop", "ro.build.version.release"], timeout=10)
        return jsonify({
            "battery": battery,
            "signal": signal,
            "wifi": wifi,
            "model": model,
            "brand": brand,
            "android": android,
        })
