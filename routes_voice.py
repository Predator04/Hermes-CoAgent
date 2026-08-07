"""Voice command routes for Hermes CoAgent."""
import json
import re
import threading
import time
import urllib.error
import urllib.request

from flask import jsonify

from shared import SERVER_PORT, _json_body, _log

_VOICE_LOCK = threading.Lock()
_VOICE_STOP = threading.Event()
_VOICE_THREAD = None
_VOICE_STATE = {
    "listening": False,
    "last_command": None,
    "last_text": None,
    "last_error": None,
    "command_count": 0,
    "started_at": None,
    "stopped_at": None,
    "chunk_seconds": 5,
}

_OPEN_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "browser": "msedge.exe",
}


def _voice_snapshot():
    with _VOICE_LOCK:
        payload = dict(_VOICE_STATE)
        payload["thread_alive"] = bool(_VOICE_THREAD and _VOICE_THREAD.is_alive())
        return payload


def _set_voice_state(**updates):
    with _VOICE_LOCK:
        _VOICE_STATE.update(updates)


def _auth_headers():
    headers = {"Content-Type": "application/json"}
    try:
        import auth as _auth
        if getattr(_auth, "AUTH_ENABLED", False) and getattr(_auth, "AUTH_TOKEN", None):
            headers["Authorization"] = f"Bearer {_auth.AUTH_TOKEN}"
    except Exception:
        pass
    return headers


def _api_call(path, method="POST", data=None, timeout=10):
    url = f"http://127.0.0.1:{SERVER_PORT}{path}"
    body = None
    headers = _auth_headers()
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(4096)
            status = getattr(resp, "status", 200)
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    parsed = raw.decode("utf-8", errors="replace")[:300]
            return {"ok": 200 <= status < 300, "status": status, "response": parsed}
    except urllib.error.HTTPError as e:
        raw = e.read(2048)
        detail = raw.decode("utf-8", errors="replace") if raw else str(e)
        return {"ok": False, "status": e.code, "error": detail[:500]}
    except Exception as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}


def _word(text, keyword):
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _after_keyword(text, keyword):
    match = re.search(rf"\b{re.escape(keyword)}\b\s*(.*)$", text, flags=re.I)
    return match.group(1).strip() if match else ""


def _click_payload(text):
    nums = re.findall(r"-?\d+", text)
    if len(nums) >= 2:
        return {"x": int(nums[0]), "y": int(nums[1])}
    pos = _api_call("/cursor/pos", method="GET", timeout=3)
    payload = pos.get("response") if pos.get("ok") and isinstance(pos.get("response"), dict) else {}
    return {"x": int(payload.get("x", 0)), "y": int(payload.get("y", 0))}


def _normalize_open_target(target):
    target = target.strip().strip('"').strip("'")
    if not target:
        return ""
    lowered = target.lower()
    if lowered in _OPEN_ALIASES:
        return _OPEN_ALIASES[lowered]
    if re.match(r"^https?://", target, re.I):
        return target
    # Executables (not URLs)
    if lowered.endswith((".exe", ".lnk", ".msi", ".bat", ".cmd", ".ps1")):
        return target
    # Domain-like strings get https:// prefix
    if "." in target and re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$", target):
        return "https://" + target
    return target


def _match_command(text):
    normalized = " ".join((text or "").lower().split())
    if not normalized:
        return None

    if normalized in ("stop", "stop listening", "stop voice", "exit", "quit"):
        return {"kind": "stop", "label": "stop"}

    if _word(normalized, "screenshot") or (_word(normalized, "screen") and _word(normalized, "shot")):
        return {"kind": "api", "label": "screenshot", "method": "GET", "path": "/screen/fresh", "data": None}

    if _word(normalized, "lock"):
        return {"kind": "api", "label": "lock", "method": "POST", "path": "/power/lock", "data": {}}

    if _word(normalized, "sleep"):
        return {"kind": "api", "label": "sleep", "method": "POST", "path": "/power/sleep", "data": {}}

    if _word(normalized, "scroll"):
        clicks = 3 if _word(normalized, "up") else -3
        nums = re.findall(r"-?\d+", normalized)
        if nums:
            clicks = abs(int(nums[0])) if _word(normalized, "up") else -abs(int(nums[0]))
        return {"kind": "api", "label": "scroll", "method": "POST", "path": "/mouse/scroll",
                "data": {"clicks": clicks}}

    if _word(normalized, "click"):
        return {"kind": "api", "label": "click", "method": "POST", "path": "/mouse/click",
                "data": _click_payload(normalized)}

    if _word(normalized, "type"):
        value = _after_keyword(text, "type")
        if value:
            return {"kind": "api", "label": "type", "method": "POST", "path": "/key/type",
                    "data": {"text": value}}

    if _word(normalized, "open"):
        target = _normalize_open_target(_after_keyword(text, "open"))
        if target:
            return {"kind": "api", "label": "open", "method": "POST", "path": "/app/open",
                    "data": {"path": target}}

    return None


def _execute_command(command):
    if command["kind"] == "stop":
        _VOICE_STOP.set()
        return {"ok": True, "status": 200, "response": {"status": "stopping"}}
    return _api_call(command["path"], method=command["method"], data=command["data"])


def _voice_loop(language):
    try:
        import speech_recognition as sr
    except ImportError:
        _set_voice_state(
            listening=False,
            last_error="SpeechRecognition not installed. Run: pip install SpeechRecognition",
            stopped_at=time.time(),
        )
        _log("[VOICE] SpeechRecognition import failed")
        return

    recognizer = sr.Recognizer()
    _set_voice_state(listening=True, last_error=None)
    _log("[VOICE] Listening loop started")
    try:
        with sr.Microphone() as source:
            try:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
            except Exception as e:
                _log(f"[VOICE] Ambient noise calibration skipped: {type(e).__name__}: {e}")
            while not _VOICE_STOP.is_set():
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=5)
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    _set_voice_state(last_error=f"{type(e).__name__}: {e}")
                    _log(f"[VOICE] Listen failed: {type(e).__name__}: {e}")
                    time.sleep(1)
                    continue

                try:
                    text = recognizer.recognize_google(audio, language=language)
                except sr.UnknownValueError:
                    continue
                except Exception as e:
                    _set_voice_state(last_error=f"{type(e).__name__}: {e}")
                    _log(f"[VOICE] Speech recognition failed: {type(e).__name__}: {e}")
                    continue

                command = _match_command(text)
                _set_voice_state(last_text=text)
                if not command:
                    _log(f"[VOICE] No command match: {text}")
                    continue

                result = _execute_command(command)
                with _VOICE_LOCK:
                    _VOICE_STATE["last_command"] = command["label"]
                    _VOICE_STATE["command_count"] += 1
                    _VOICE_STATE["last_error"] = None if result.get("ok") else result.get("error")
                _log(f"[VOICE] {text!r} -> {command['label']} status={result.get('status')} ok={result.get('ok')}")
    except Exception as e:
        _set_voice_state(last_error=f"{type(e).__name__}: {e}")
        _log(f"[VOICE] Loop stopped by error: {type(e).__name__}: {e}")
    finally:
        _set_voice_state(listening=False, stopped_at=time.time())
        _log("[VOICE] Listening loop stopped")


def register_routes(app, state, require_auth):
    @app.route("/voice/status", methods=["GET"])
    @require_auth
    def route_voice_status():
        return jsonify(_voice_snapshot())

    @app.route("/voice/start", methods=["POST"])
    @require_auth
    def route_voice_start():
        global _VOICE_THREAD
        try:
            import speech_recognition  # noqa: F401
        except ImportError:
            msg = "SpeechRecognition not installed. Run: pip install SpeechRecognition"
            _set_voice_state(last_error=msg, listening=False)
            _log(f"[VOICE] Start failed: {msg}")
            return jsonify({"error": msg}), 503

        d = _json_body()
        language = d.get("language", "en-US")
        with _VOICE_LOCK:
            if _VOICE_THREAD and _VOICE_THREAD.is_alive():
                payload = dict(_VOICE_STATE)
                payload["status"] = "already_running"
                return jsonify(payload)
            _VOICE_STOP.clear()
            _VOICE_STATE.update({
                "listening": True,
                "last_error": None,
                "started_at": time.time(),
                "stopped_at": None,
                "chunk_seconds": 5,
            })
            _VOICE_THREAD = threading.Thread(
                target=_voice_loop,
                args=(language,),
                name="voice_commands",
                daemon=True,
            )
            _VOICE_THREAD.start()
        _log("[VOICE] Start requested")
        return jsonify({"status": "started", "listening": True, "chunk_seconds": 5})

    @app.route("/voice/stop", methods=["POST"])
    @require_auth
    def route_voice_stop():
        _VOICE_STOP.set()
        _set_voice_state(listening=False, stopped_at=time.time())
        _log("[VOICE] Stop requested")
        return jsonify({"status": "stopping", "listening": False})
