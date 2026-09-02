"""Voice command routes for Hermes CoAgent."""
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from flask import jsonify, request

from shared import SERVER_PORT, _json_body, _log

# Module-level marker so callers can discover the voice feature via /voice/status.
VOICE_MODULE = "voice"

_VOICE_LOCK = threading.Lock()
_VOICE_STOP = threading.Event()
_VOICE_THREAD = None
_RECORD_STOP = threading.Event()
_RECORD_THREAD = None
_WHISPER_MODEL = None
_WHISPER_MODEL_LOCK = threading.Lock()
_VOICE_STATE = {
    "listening": False,
    "recording": False,
    "last_command": None,
    "last_text": None,
    "last_error": None,
    "last_engine": None,
    "command_count": 0,
    "started_at": None,
    "stopped_at": None,
    "chunk_seconds": 5,
    "record_started_at": None,
    "record_stopped_at": None,
}

_OPEN_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "browser": "msedge.exe",
}


def _faster_whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _speech_recognition_available():
    try:
        import speech_recognition  # noqa: F401
        return True
    except ImportError:
        return False


def _pyaudio_available():
    try:
        import pyaudio  # noqa: F401
        return True
    except ImportError:
        return False


def _pyttsx3_available():
    try:
        import pyttsx3  # noqa: F401
        return True
    except ImportError:
        return False


def _powershell_tts_available():
    return os.name == "nt"


def _transcribe_engines_available():
    return _faster_whisper_available() or _speech_recognition_available()


def _speak_engines_available():
    return _pyttsx3_available() or _powershell_tts_available()


def _voice_snapshot():
    with _VOICE_LOCK:
        payload = dict(_VOICE_STATE)
        payload["thread_alive"] = bool(_VOICE_THREAD and _VOICE_THREAD.is_alive())
        payload["record_thread_alive"] = bool(_RECORD_THREAD and _RECORD_THREAD.is_alive())
        payload["transcribe_available"] = _transcribe_engines_available()
        payload["transcribe_engines"] = {
            "faster_whisper": _faster_whisper_available(),
            "speech_recognition": _speech_recognition_available(),
            "pyaudio": _pyaudio_available(),
        }
        payload["speak_available"] = _speak_engines_available()
        payload["speak_engines"] = {
            "pyttsx3": _pyttsx3_available(),
            "sapi_powershell": _powershell_tts_available(),
        }
        payload["goal_integration"] = True
        payload["module"] = VOICE_MODULE
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
            raw = resp.read()
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
    if not (pos.get("ok") and isinstance(pos.get("response"), dict)):
        return None
    payload = pos.get("response")
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
        coords = _click_payload(normalized)
        if not coords:
            return None
        return {"kind": "api", "label": "click", "method": "POST", "path": "/mouse/click",
                "data": coords}

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


def _get_whisper_model():
    global _WHISPER_MODEL
    with _WHISPER_MODEL_LOCK:
        if _WHISPER_MODEL is None:
            from faster_whisper import WhisperModel
            model_name = os.environ.get("HERMES_WHISPER_MODEL", "base")
            _WHISPER_MODEL = WhisperModel(model_name)
        return _WHISPER_MODEL


def _transcribe_file(path, language):
    lang = (language or "").strip() or None
    if _faster_whisper_available():
        try:
            model = _get_whisper_model()
            segments, _info = model.transcribe(path, language=lang)
            text = " ".join((seg.text or "").strip() for seg in segments).strip()
            return {"ok": True, "text": text, "engine": "faster-whisper"}
        except Exception as e:
            _log(f"[VOICE] faster-whisper failed: {type(e).__name__}: {e}")
    if _speech_recognition_available():
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(path) as source:
                audio = recognizer.record(source)
            google_lang = lang or "en-US"
            text = recognizer.recognize_google(audio, language=google_lang)
            return {"ok": True, "text": text, "engine": "google"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "engine": "google"}
    return {
        "ok": False,
        "error": "no transcription engine installed",
        "hint": "pip install faster-whisper  OR  pip install SpeechRecognition",
    }


def _speak_text(text, rate=None):
    if _pyttsx3_available():
        try:
            import pyttsx3
            engine = pyttsx3.init()
            if rate is not None:
                try:
                    engine.setProperty("rate", int(rate))
                except (TypeError, ValueError):
                    pass
            engine.say(text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
            return {"ok": True, "spoken": True, "engine": "pyttsx3"}
        except Exception as e:
            _log(f"[VOICE] pyttsx3 speak failed: {type(e).__name__}: {e}")
    if _powershell_tts_available():
        text_path = None
        ps_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as tf:
                tf.write(text)
                text_path = tf.name
            ps_script = (
                "param([Parameter(Mandatory=$true)][string]$TextPath, [int]$Rate = 0)\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "if ($Rate -ne 0) { $s.Rate = $Rate }\n"
                "$t = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)\n"
                "$s.Speak($t)\n"
            )
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", encoding="utf-8", delete=False) as pf:
                pf.write(ps_script)
                ps_path = pf.name
            args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps_path, "-TextPath", text_path]
            if rate is not None:
                try:
                    args.extend(["-Rate", str(int(rate))])
                except (TypeError, ValueError):
                    pass
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            completed = subprocess.run(args, timeout=60, creationflags=flags, capture_output=True)
            if completed.returncode != 0:
                err = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
                return {"ok": False, "error": f"PowerShell TTS failed (exit {completed.returncode}): {err[:300]}", "engine": "sapi"}
            return {"ok": True, "spoken": True, "engine": "sapi"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "engine": "sapi"}
        finally:
            for p in (text_path, ps_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    return {
        "ok": False,
        "error": "no TTS engine available",
        "hint": "pip install pyttsx3  OR  run on Windows with PowerShell",
    }


def _feed_goal_runner(text):
    return _api_call(
        "/copilot/goal",
        method="POST",
        data={"goal": text, "max_steps": 10},
        timeout=15,
    )


def _record_loop(seconds, language, feed_goal):
    tmp_path = None
    try:
        try:
            import speech_recognition as sr
        except ImportError:
            _set_voice_state(
                recording=False,
                last_error="SpeechRecognition not installed. Run: pip install SpeechRecognition pyaudio",
                record_stopped_at=time.time(),
            )
            return
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                except Exception:
                    pass
                audio = recognizer.record(source, duration=seconds)
        except Exception as e:
            _set_voice_state(
                recording=False,
                last_error=f"{type(e).__name__}: {e}",
                record_stopped_at=time.time(),
            )
            _log(f"[VOICE] Record failed: {type(e).__name__}: {e}")
            return
        if _RECORD_STOP.is_set():
            _set_voice_state(recording=False, record_stopped_at=time.time())
            return
        try:
            wav_bytes = audio.get_wav_data()
        except Exception as e:
            _set_voice_state(
                recording=False,
                last_error=f"{type(e).__name__}: {e}",
                record_stopped_at=time.time(),
            )
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(wav_bytes)
            tmp_path = tf.name
        result = _transcribe_file(tmp_path, language)
        text = result.get("text", "") if result.get("ok") else ""
        _set_voice_state(
            recording=False,
            last_text=text or None,
            last_engine=result.get("engine"),
            last_error=None if result.get("ok") else result.get("error"),
            record_stopped_at=time.time(),
        )
        _log(f"[VOICE] Record captured seconds={seconds} engine={result.get('engine')} ok={result.get('ok')}")
        if feed_goal and text:
            goal_result = _feed_goal_runner(text)
            _log(f"[VOICE] Goal fed from record: ok={goal_result.get('ok')} status={goal_result.get('status')}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _pick_audio_suffix(filename, content_type):
    known = (".wav", ".webm", ".ogg", ".mp3", ".m4a", ".flac", ".aac")
    if filename:
        low = filename.lower()
        for ext in known:
            if low.endswith(ext):
                return ext
    ctype = (content_type or "").lower()
    if "webm" in ctype:
        return ".webm"
    if "ogg" in ctype:
        return ".ogg"
    if "mpeg" in ctype or "mp3" in ctype:
        return ".mp3"
    if "flac" in ctype:
        return ".flac"
    if "aac" in ctype or "m4a" in ctype:
        return ".m4a"
    return ".wav"


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

        d = _json_body() or {}
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

    @app.route("/voice/transcribe", methods=["POST"])
    @require_auth
    def route_voice_transcribe():
        if not _transcribe_engines_available():
            return jsonify({
                "ok": False,
                "error": "no transcription engine installed",
                "hint": "pip install faster-whisper  OR  pip install SpeechRecognition",
            }), 503

        language = "en"
        audio_bytes = b""
        filename = ""
        ctype = (request.content_type or "").lower()

        uploaded = None
        try:
            if request.files:
                uploaded = request.files.get("audio")
        except Exception:
            uploaded = None

        if uploaded is not None:
            filename = uploaded.filename or ""
            audio_bytes = uploaded.read() or b""
            form_lang = request.form.get("language")
            if form_lang:
                language = form_lang
        elif "application/json" in ctype:
            body = _json_body() or {}
            language = body.get("language", language)
            data_field = body.get("audio_base64") or body.get("audio")
            if isinstance(data_field, str) and data_field:
                import base64
                try:
                    audio_bytes = base64.b64decode(data_field)
                except Exception:
                    audio_bytes = b""
        else:
            form_lang = None
            try:
                form_lang = request.form.get("language")
            except Exception:
                pass
            if form_lang:
                language = form_lang
            audio_bytes = request.get_data(cache=False) or b""

        if not audio_bytes:
            return jsonify({"ok": False, "error": "no audio data provided"}), 400

        suffix = _pick_audio_suffix(filename, ctype)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tf.write(audio_bytes)
                tmp_path = tf.name
            result = _transcribe_file(tmp_path, language)
            if not result.get("ok"):
                _set_voice_state(last_error=result.get("error"))
                status = 503 if "no transcription engine" in (result.get("error") or "") else 500
                return jsonify(result), status
            _set_voice_state(
                last_text=result.get("text") or None,
                last_engine=result.get("engine"),
                last_error=None,
            )
            _log(f"[VOICE] Transcribed bytes={len(audio_bytes)} engine={result.get('engine')}")
            return jsonify(result)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.route("/voice/record", methods=["POST"])
    @require_auth
    def route_voice_record():
        global _RECORD_THREAD
        d = _json_body() or {}
        action = str(d.get("action", "start")).lower().strip()

        if action == "stop":
            _RECORD_STOP.set()
            _set_voice_state(recording=False, record_stopped_at=time.time())
            _log("[VOICE] Record stop requested")
            return jsonify(_voice_snapshot())

        if not _speech_recognition_available():
            return jsonify({
                "ok": False,
                "error": "SpeechRecognition not installed",
                "hint": "pip install SpeechRecognition pyaudio",
            }), 503

        try:
            seconds = max(1, min(int(d.get("seconds", 5)), 120))
        except (TypeError, ValueError):
            seconds = 5
        language = d.get("language", "en")
        feed_goal = bool(d.get("feed_goal", False))

        with _VOICE_LOCK:
            if _RECORD_THREAD and _RECORD_THREAD.is_alive():
                payload = dict(_VOICE_STATE)
                payload["status"] = "already_recording"
                return jsonify(payload)
            _RECORD_STOP.clear()
            _VOICE_STATE.update({
                "recording": True,
                "record_started_at": time.time(),
                "record_stopped_at": None,
                "last_error": None,
            })
            _RECORD_THREAD = threading.Thread(
                target=_record_loop,
                args=(seconds, language, feed_goal),
                name="voice_record",
                daemon=True,
            )
            _RECORD_THREAD.start()
        _log(f"[VOICE] Record started seconds={seconds} language={language} feed_goal={feed_goal}")
        return jsonify({
            "status": "recording",
            "recording": True,
            "seconds": seconds,
            "language": language,
            "feed_goal": feed_goal,
        })

    @app.route("/voice/speak", methods=["POST"])
    @require_auth
    def route_voice_speak():
        d = _json_body() or {}
        text = str(d.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "text is required"}), 400
        if len(text) > 10000:
            return jsonify({"ok": False, "error": "text too long (max 10000 chars)"}), 400
        rate = d.get("rate")
        if not _speak_engines_available():
            return jsonify({
                "ok": False,
                "error": "no TTS engine available",
                "hint": "pip install pyttsx3  OR  run on Windows with PowerShell",
            }), 503
        result = _speak_text(text, rate=rate)
        if not result.get("ok"):
            return jsonify(result), 500
        _log(f"[VOICE] Speak ok engine={result.get('engine')} chars={len(text)}")
        return jsonify(result)

    @app.route("/voice/goal", methods=["POST"])
    @require_auth
    def route_voice_goal():
        d = _json_body() or {}
        text = str(d.get("text") or "").strip()
        if not text:
            with _VOICE_LOCK:
                text = str(_VOICE_STATE.get("last_text") or "").strip()
        if not text:
            return jsonify({
                "ok": False,
                "error": "no text provided and no last transcript available",
                "goal_started": False,
            }), 400
        result = _feed_goal_runner(text)
        if not result.get("ok"):
            status = result.get("status")
            code = status if isinstance(status, int) and 400 <= status < 600 else 502
            return jsonify({
                "ok": False,
                "error": "goal runner unavailable",
                "detail": result.get("error") or result.get("response"),
                "status": status,
                "goal_started": False,
                "text": text,
            }), code
        _log(f"[VOICE] Goal started from voice text chars={len(text)}")
        return jsonify({
            "ok": True,
            "goal_started": True,
            "text": text,
            "response": result.get("response"),
            "status": result.get("status"),
        })
