"""Narrated screen-recording → evidence-backed bug report pipeline.

Ties together the existing /video/* (screen+mic capture), Whisper transcription
(/voice/*), and OCR primitives into a persistent, locally-indexed recording:
timestamped transcript segments, scene keyframes with per-frame OCR, wall-clock
anchoring, and a ready-to-file GitHub issue draft.

Endpoints:
  POST /recordings/start        — begin a screen+mic recording (wraps /video/start)
  POST /recordings/stop         — stop the active recording (wraps /video/stop)
  POST /recordings/index/<id>   — build the local index (transcript + keyframes + OCR)
  GET  /recordings/index/<id>   — return the built index
  GET  /recordings/transcript   — return transcript segments (?id=)
  GET  /recordings/frames       — return keyframes (?id=)
  POST /recordings/issue-draft  — build a GitHub issue body (optionally file it)
"""

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _json_body, _self_port, _wrap_registered_blueprint_routes


recordings_bp = Blueprint("recordings", __name__)

RECORDINGS_DIR = COAGENT_DIR / "recordings"
INDEX_DIR = RECORDINGS_DIR / "index"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _auth_header():
    token_file = COAGENT_DIR / ".token"
    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token and "\n" not in token and "\r" not in token:
                return f"Bearer {token}"
    except Exception:
        pass
    try:
        return request.headers.get("Authorization", "")
    except RuntimeError:
        return ""


def _coagent_request(method, path, data=None, timeout=60):
    headers = {"Accept": "application/json"}
    body = None
    if method.upper() != "GET":
        headers["Content-Type"] = "application/json"
        body = json.dumps(data or {}).encode("utf-8")
    token = _auth_header()
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{_self_port()}{path}",
        data=body,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            if not text:
                return {"status": "ok", "status_code": getattr(response, "status", 200)}
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"text": text}
            if isinstance(payload, dict):
                payload.setdefault("status_code", getattr(response, "status", 200))
            return payload
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"error": text or str(exc)}
        if isinstance(payload, dict):
            payload.setdefault("error", payload.get("error") or f"HTTP {exc.code}")
            payload["status_code"] = exc.code
        return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "status_code": 0}


def _safe_id(recording_id):
    rid = str(recording_id or "").strip()
    if not _ID_RE.match(rid):
        raise ValueError("invalid recording id")
    return rid


def _index_dir(recording_id):
    return INDEX_DIR / _safe_id(recording_id)


def _find_ffmpeg():
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _run(cmd, timeout=300):
    """Run a subprocess quietly, returning (returncode, stdout, stderr)."""
    kwargs = {"capture_output": True, "text": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, **kwargs)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _get_recording_info(recording_id):
    """Fetch the recording's path/state from the /video/status endpoint."""
    resp = _coagent_request("GET", f"/video/status?recording_id={recording_id}")
    if isinstance(resp, dict) and resp.get("recording"):
        return resp["recording"]
    return resp if isinstance(resp, dict) else {}


def _transcribe_with_segments(audio_path, language):
    try:
        from routes_voice import (
            _faster_whisper_available,
            _get_whisper_model,
            _speech_recognition_available,
        )
    except Exception as exc:
        return [], "none", f"voice helpers unavailable: {type(exc).__name__}: {exc}"

    if _faster_whisper_available():
        try:
            model = _get_whisper_model()
            segments, _info = model.transcribe(str(audio_path), language=language or None)
            segs = []
            for seg in segments:
                start = round(float(getattr(seg, "start", 0.0)), 2)
                end = round(float(getattr(seg, "end", 0.0)), 2)
                text = (getattr(seg, "text", "") or "").strip()
                if text:
                    segs.append({"start": start, "end": end, "text": text})
            return segs, "faster-whisper", None
        except Exception as exc:
            _console(f"[recordings] faster-whisper failed: {type(exc).__name__}: {exc}")

    if _speech_recognition_available():
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(str(audio_path)) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language=(language or "en-US"))
            segs = [{"start": 0.0, "end": None, "text": str(text or "").strip()}] if text else []
            return segs, "google", None
        except Exception as exc:
            return [], "google", f"{type(exc).__name__}: {exc}"

    return [], "none", "no transcription engine installed (pip install faster-whisper)"


def _ocr_image(path):
    try:
        from PIL import Image
        with Image.open(str(path)) as src:
            img = src.convert("RGB")
    except Exception as exc:
        return "", f"image open failed: {type(exc).__name__}: {exc}"
    try:
        import pytesseract
        return pytesseract.image_to_string(img).strip(), None
    except Exception:
        pass
    try:
        from routes_ocr import _windows_ocr
        text = _windows_ocr(img)
        if text:
            return str(text).strip(), None
    except Exception as exc:
        return "", f"windows ocr failed: {type(exc).__name__}: {exc}"
    return "", "no OCR engine"


def _build_index(recording_id, info, frame_interval, language, force):
    """Build transcript + keyframes + OCR index for a finished recording."""
    rid = _safe_id(recording_id)
    workdir = _index_dir(rid)
    workdir.mkdir(parents=True, exist_ok=True)

    video_path = info.get("path") or ""
    if not video_path or not os.path.isfile(video_path):
        return None, f"recording file not found: {video_path or '(unknown path)'}"

    state = info.get("state") or ""
    if state == "recording":
        return None, "recording still in progress — stop it before indexing"

    index_file = workdir / "index.json"
    if index_file.exists() and not force:
        return json.loads(index_file.read_text(encoding="utf-8")), None

    ffmpeg = _find_ffmpeg()
    interval = None
    transcript_segments = []
    transcript_engine = None
    transcript_error = None

    # 1. extract audio + transcribe
    if ffmpeg:
        audio_path = workdir / "audio.wav"
        rc, _out, err = _run([
            ffmpeg, "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000", str(audio_path),
        ])
        if rc == 0 and audio_path.exists() and audio_path.stat().st_size > 0:
            transcript_segments, transcript_engine, transcript_error = _transcribe_with_segments(audio_path, language)
        else:
            transcript_error = f"audio extraction failed (rc={rc}): {err[-300:]}"
    else:
        transcript_error = "ffmpeg not found — cannot extract audio"

    # 2. keyframes + OCR
    frames = []
    if ffmpeg:
        try:
            interval = max(1, int(frame_interval))
        except (TypeError, ValueError):
            interval = 4
        frames_dir = workdir / "frames"
        shutil.rmtree(frames_dir, ignore_errors=True)
        frames_dir.mkdir(parents=True, exist_ok=True)
        rc, _out, err = _run([
            ffmpeg, "-y", "-i", video_path,
            "-vf", f"fps=1/{interval}",
            str(frames_dir / "frame_%04d.jpg"),
        ])
        if rc == 0:
            for jpg in sorted(frames_dir.glob("frame_*.jpg")):
                try:
                    idx = int(jpg.stem.split("_")[-1])
                except ValueError:
                    idx = 1
                t = (idx - 1) * interval
                ocr_text, ocr_err = _ocr_image(jpg)
                frames.append({
                    "time": t,
                    "path": str(jpg),
                    "ocr_text": ocr_text or "",
                    "ocr_error": ocr_err,
                })
        else:
            transcript_error = transcript_error or f"keyframe extraction failed (rc={rc}): {err[-300:]}"

    index = {
        "recording_id": rid,
        "video_path": video_path,
        "created_at": _now_iso(),
        "frame_interval": interval,
        "transcript": {
            "engine": transcript_engine,
            "error": transcript_error,
            "segments": transcript_segments,
            "full_text": " ".join(s.get("text", "") for s in transcript_segments).strip(),
        },
        "frames": frames,
    }
    tmp = workdir / "index.tmp.json"
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    tmp.replace(index_file)
    return index, None


def _load_index(recording_id):
    index_file = _index_dir(recording_id) / "index.json"
    if not index_file.exists():
        return None
    try:
        return json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_issue_body(index, title, labels):
    title = (title or "").strip() or f"Recording evidence: {index.get('recording_id', '')}"
    lines = [
        "## Summary",
        "",
        f"Recording: `{index.get('recording_id', '')}`",
        f"Captured: {index.get('created_at', '')}",
        "",
    ]
    full_text = index.get("transcript", {}).get("full_text", "")
    if full_text:
        lines += ["## Narration transcript", "", "```text", full_text[:4000], "```", ""]
    frames = index.get("frames", [])
    if frames:
        lines += ["## Timeline (frames with OCR)", ""]
        for frame in frames[:40]:
            ocr = (frame.get("ocr_text") or "").replace("\n", " ")[:200]
            lines.append(f"- `{frame.get('time')}s`: {ocr or '(no text)'}")
        lines.append("")
    lines += ["## Frame files", ""]
    for frame in frames[:40]:
        lines.append(f"- {frame.get('path', '')}")
    lines.append("")
    return {
        "title": title,
        "body": "\n".join(lines),
        "labels": labels or ["enhancement"],
    }


def register_routes(app, state, require_auth):
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_available = bool(_find_ffmpeg())

    @recordings_bp.route("/recordings/start", methods=["POST"])
    def route_recordings_start():
        body = _json_body() or {}
        payload = dict(body)
        payload.setdefault("audio_device", body.get("audio_device") or "Microphone")
        result = _coagent_request("POST", "/video/start", payload)
        status = result.get("status_code", 200) if isinstance(result, dict) else 502
        return jsonify(result), int(status) if status else 502

    @recordings_bp.route("/recordings/stop", methods=["POST"])
    def route_recordings_stop():
        body = _json_body() or {}
        result = _coagent_request("POST", "/video/stop", body)
        status = result.get("status_code", 200) if isinstance(result, dict) else 502
        return jsonify(result), int(status) if status else 502

    @recordings_bp.route("/recordings/index/<recording_id>", methods=["POST"])
    def route_recordings_index(recording_id):
        try:
            rid = _safe_id(recording_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        body = _json_body() or {}
        info = _get_recording_info(rid)
        if not info or not info.get("path"):
            return jsonify({"error": "recording not found", "recording_id": rid}), 404
        frame_interval = body.get("frame_interval", 4)
        language = body.get("language") or "en"
        force = bool(body.get("force", False))
        index, error = _build_index(rid, info, frame_interval, language, force)
        if error:
            return jsonify({"error": error, "recording_id": rid}), 400
        return jsonify({"status": "indexed", "recording_id": rid, "index": index})

    @recordings_bp.route("/recordings/index/<recording_id>", methods=["GET"])
    def route_recordings_index_get(recording_id):
        try:
            rid = _safe_id(recording_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        index = _load_index(rid)
        if not index:
            return jsonify({"error": "no index built yet", "recording_id": rid,
                            "hint": "POST /recordings/index/<id> first"}), 404
        return jsonify(index)

    @recordings_bp.route("/recordings/transcript", methods=["GET"])
    def route_recordings_transcript():
        rid = request.args.get("id") or request.args.get("recording_id") or ""
        try:
            rid = _safe_id(rid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        index = _load_index(rid)
        if not index:
            return jsonify({"error": "no index built yet", "recording_id": rid}), 404
        return jsonify(index.get("transcript", {}))

    @recordings_bp.route("/recordings/frames", methods=["GET"])
    def route_recordings_frames():
        rid = request.args.get("id") or request.args.get("recording_id") or ""
        try:
            rid = _safe_id(rid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        index = _load_index(rid)
        if not index:
            return jsonify({"error": "no index built yet", "recording_id": rid}), 404
        frames = index.get("frames", [])
        return jsonify({"recording_id": rid, "count": len(frames), "frames": frames})

    @recordings_bp.route("/recordings/issue-draft", methods=["POST"])
    def route_recordings_issue_draft():
        body = _json_body() or {}
        rid = body.get("id") or body.get("recording_id") or ""
        try:
            rid = _safe_id(rid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        index = _load_index(rid)
        if not index:
            return jsonify({"error": "no index built yet", "recording_id": rid,
                            "hint": "POST /recordings/index/<id> first"}), 404
        title = body.get("title") or ""
        labels = body.get("labels") if isinstance(body.get("labels"), list) else None
        draft = _build_issue_body(index, title, labels)

        filed = None
        if body.get("file"):
            repo = str(body.get("repo") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                return jsonify({"error": "repo must be 'owner/name'"}), 400
            if draft["title"].startswith("-"):
                return jsonify({"error": "title must not start with '-'"}), 400
            for label in (draft.get("labels") or []):
                if str(label).startswith("-"):
                    return jsonify({"error": "labels must not start with '-'"}), 400
            gh_cmd = [
                "gh", "issue", "create",
                "--repo", repo,
                "--title", draft["title"],
                "--body", draft["body"],
            ]
            for label in (draft.get("labels") or []):
                gh_cmd += ["--label", label]
            rc, out, err = _run(gh_cmd, timeout=60)
            if rc == 0:
                filed = out.strip()
            else:
                return jsonify({"error": f"gh issue create failed (rc={rc})",
                                "stderr": err[-500:], "draft": draft}), 502

        return jsonify({
            "recording_id": rid,
            "draft": draft,
            "filed_issue": filed,
        })

    app.register_blueprint(recordings_bp)
    _wrap_registered_blueprint_routes(app, recordings_bp.name, require_auth)
    state.recordings = {
        "dir": str(RECORDINGS_DIR),
        "index_dir": str(INDEX_DIR),
        "ffmpeg_available": ffmpeg_available,
    }
