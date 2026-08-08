"""Android phone bridge routes using ADB."""

import base64
import subprocess

from flask import Response, jsonify, request

from shared import COAGENT_DIR, _json_body


PHONE_SCREENSHOT = COAGENT_DIR / "phone.png"


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


def _json_result(result, status_ok=200):
    status = status_ok if result.get("ok") else 500
    safe = dict(result)
    if isinstance(safe.get("stdout"), bytes):
        safe["stdout_b64"] = base64.b64encode(safe.pop("stdout")).decode("ascii")
    return jsonify(safe), status


def _input_text(text):
    value = str(text)
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
        return _json_result(_run_adb(data, ["shell", "input", "tap", str(int(data.get("x", 0))), str(int(data.get("y", 0)))]))

    @app.route("/phone/type", methods=["POST"])
    @require_auth
    def route_phone_type():
        data = _json_body()
        text = data.get("text")
        if text is None:
            return _error("text is required")
        return _json_result(_run_adb(data, ["shell", "input", "text", _input_text(text)]))

    @app.route("/phone/swipe", methods=["POST"])
    @require_auth
    def route_phone_swipe():
        data = _json_body()
        args = ["shell", "input", "swipe", str(int(data.get("x1", 0))), str(int(data.get("y1", 0))),
                str(int(data.get("x2", 0))), str(int(data.get("y2", 0)))]
        if data.get("duration_ms") is not None:
            args.append(str(int(data.get("duration_ms"))))
        return _json_result(_run_adb(data, args))

    @app.route("/phone/key", methods=["POST"])
    @require_auth
    def route_phone_key():
        data = _json_body()
        keycode = data.get("keycode") or data.get("key")
        if keycode is None:
            return _error("keycode is required")
        return _json_result(_run_adb(data, ["shell", "input", "keyevent", str(keycode)]))

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
        return _json_result(_run_adb(data, shell_args, timeout=int(data.get("timeout", 30) or 30)))

    @app.route("/phone/app/start", methods=["POST"])
    @require_auth
    def route_phone_app_start():
        data = _json_body()
        package = data.get("package")
        if not isinstance(package, str) or not package:
            return _error("package is required")
        return _json_result(_run_adb(data, ["shell", "monkey", "-p", package, "1"], timeout=20))

    @app.route("/phone/app/stop", methods=["POST"])
    @require_auth
    def route_phone_app_stop():
        data = _json_body()
        package = data.get("package")
        if not isinstance(package, str) or not package:
            return _error("package is required")
        return _json_result(_run_adb(data, ["shell", "am", "force-stop", package], timeout=20))

    @app.route("/phone/sms/read", methods=["POST"])
    @require_auth
    def route_phone_sms_read():
        data = _json_body()
        projection = data.get("projection", "address,date,type,body")
        uri = data.get("uri", "content://sms")
        result = _run_adb(data, ["shell", "content", "query", "--uri", str(uri), "--projection", str(projection), "--sort", "date DESC"], timeout=int(data.get("timeout", 20) or 20))
        return _json_result(result)

    @app.route("/phone/status", methods=["POST", "GET"])
    @require_auth
    def route_phone_status():
        data = _json_body()
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
