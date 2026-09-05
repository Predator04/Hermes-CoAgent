"""System-audio (loopback) transcription — transcribe what the OS is playing.

Endpoints:
  POST /audio/transcribe-loopback - capture N seconds of system loopback audio
                                     and return the transcript
  GET  /audio/loopback/status     - device availability + recording state

Composes two existing capabilities: the dshow loopback capture already proven
in routes_video (ffmpeg dshow) and the transcription engine ladder in
routes_voice (_transcribe_file: faster-whisper -> SpeechRecognition/google).

No new heavy dependencies. Loopback device naming varies by machine (Realtek
"Stereo Mix", WASAPI loopback registrations, etc.), so the device is
configurable per-call, via the HERMES_LOOPBACK_DEVICE env var, and discoverable
through the status endpoint.

Windows-only + third-party imports are wrapped in try/except so this file
imports cleanly under a Linux syntax check.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time

from flask import jsonify

from shared import _json_body, _log

_DEFAULT_DEVICE_ENV = "HERMES_LOOPBACK_DEVICE"
_DEFAULT_DEVICE = "Stereo Mix"
_DEFAULT_SECONDS = 15
_MAX_SECONDS = 300

_STATE_LOCK = threading.Lock()
_ACTIVE = {"recording": False, "started_at": None, "device": None}


def _find_ffmpeg():
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _capture_loopback(ffmpeg, device, seconds):
    """Capture `seconds` of loopback audio to a temp WAV.

    Returns (path, error). Error is None on success.
    """
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="coagent_loopback_")
    os.close(fd)
    try:
        os.unlink(path)  # ffmpeg -y will (re)create it
    except OSError:
        pass
    argv = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "dshow", "-i", f"audio={device}",
        "-t", str(seconds),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        path,
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(argv, capture_output=True,
                              timeout=seconds + 15, creationflags=flags)
    except subprocess.TimeoutExpired:
        return path, "capture timed out"
    except FileNotFoundError:
        return path, "ffmpeg not found"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        return path, f"ffmpeg exited {proc.returncode}: {err[:400]}"
    return path, None


def _engines_available():
    try:
        from routes_voice import _transcribe_engines_available
        return bool(_transcribe_engines_available())
    except Exception:
        return False


def _transcribe(path, language):
    try:
        from routes_voice import _transcribe_file
        return _transcribe_file(path, language)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def register_routes(app, state, require_auth):

    @app.route("/audio/transcribe-loopback", methods=["POST"])
    @require_auth
    def route_transcribe_loopback():
        """Capture system loopback audio and return the transcript.

        Body: {"seconds": 15, "language": null, "device": "Stereo Mix"}
        """
        if os.name != "nt":
            return jsonify({"error": "Windows-only (dshow loopback capture)"}), 501
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            return jsonify({"error": "ffmpeg not found on PATH"}), 501

        body = _json_body() or {}
        try:
            seconds = int(body.get("seconds", _DEFAULT_SECONDS))
        except (TypeError, ValueError):
            seconds = _DEFAULT_SECONDS
        seconds = max(1, min(seconds, _MAX_SECONDS))
        device = (body.get("device") or os.environ.get(_DEFAULT_DEVICE_ENV)
                  or _DEFAULT_DEVICE)
        language = (str(body.get("language") or "")).strip() or None

        with _STATE_LOCK:
            if _ACTIVE["recording"]:
                return jsonify({"error": "loopback capture already in progress"}), 409
            _ACTIVE["recording"] = True
            _ACTIVE["started_at"] = time.time()
            _ACTIVE["device"] = device

        path = None
        try:
            path, err = _capture_loopback(ffmpeg, device, seconds)
            if err:
                return jsonify({
                    "ok": False,
                    "error": err,
                    "device": device,
                    "hint": "check GET /audio/loopback/status for available devices",
                }), 502
            result = _transcribe(path, language)
            result["seconds"] = seconds
            result["device"] = device
            result["method"] = "loopback"
            return jsonify(result)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            with _STATE_LOCK:
                _ACTIVE["recording"] = False
                _ACTIVE["started_at"] = None
                _ACTIVE["device"] = None

    @app.route("/audio/loopback/status", methods=["GET"])
    @require_auth
    def route_loopback_status():
        """Device availability + current recording state."""
        ffmpeg = _find_ffmpeg()
        devices = []
        if ffmpeg and os.name == "nt":
            try:
                from routes_video import _list_dshow_audio_devices
                devices, _err = _list_dshow_audio_devices(ffmpeg)
                devices = devices or []
            except Exception as exc:
                _log(f"[loopback] device list failed: {exc}")
        return jsonify({
            "available": bool(ffmpeg),
            "ffmpeg": bool(ffmpeg),
            "devices": devices,
            "default_device": os.environ.get(_DEFAULT_DEVICE_ENV) or _DEFAULT_DEVICE,
            "recording": _ACTIVE["recording"],
            "started_at": _ACTIVE["started_at"],
            "transcribe_engines_available": _engines_available(),
        })
