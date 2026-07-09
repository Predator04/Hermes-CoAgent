"""Animated GIF desktop session recorder routes."""

import threading
import time
import uuid

from flask import Blueprint, jsonify, send_file

from shared import COAGENT_DIR, _console, _json_body


RECORDINGS_DIR = COAGENT_DIR / "recordings"
MAX_RECORDINGS = 5

_LOCK = threading.RLock()
_STOP_EVENT = threading.Event()
_THREAD = None
_ACTIVE = None
_FRAMES = []
_LAST_RECORDING = None


def _new_recording_id():
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_region(region):
    if not region:
        return None
    if not isinstance(region, dict):
        raise ValueError("region must be an object with x, y, w, h")
    try:
        x = int(region.get("x", 0))
        y = int(region.get("y", 0))
        w = int(region.get("w", 0))
        h = int(region.get("h", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("region x, y, w, h must be integers") from exc
    if w <= 0 or h <= 0:
        raise ValueError("region w and h must be positive")
    return (x, y, x + w, y + h)


def _cleanup_old_recordings():
    try:
        paths = sorted(
            RECORDINGS_DIR.glob("rec_*.gif"),
            key=lambda p: p.stat().st_mtime,
        )
        for path in paths[:-MAX_RECORDINGS]:
            try:
                path.unlink()
                _console(f"[recorder_gif] deleted old recording: {path}")
            except OSError as exc:
                _console(f"[recorder_gif] cleanup failed for {path}: {exc}")
    except Exception as exc:
        _console(f"[recorder_gif] cleanup failed: {type(exc).__name__}: {exc}")


def _capture_loop(recording_id, fps, max_seconds, bbox):
    frame_interval = 1.0 / max(1, fps)
    start = time.perf_counter()
    next_capture = start
    try:
        from PIL import ImageGrab

        while not _STOP_EVENT.is_set():
            now = time.perf_counter()
            if now - start >= max_seconds:
                break
            if now < next_capture:
                _STOP_EVENT.wait(min(next_capture - now, 0.2))
                continue
            try:
                import mss as _mss_mod
                from PIL import Image as _PILImage
                with _mss_mod.mss() as _sct:
                    _mon = _sct.monitors[0]
                    _sct_img = _sct.grab(_mon)
                    image = _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb).crop(bbox).convert("RGB")
                with _LOCK:
                    if not _ACTIVE or _ACTIVE.get("recording_id") != recording_id:
                        break
                    _FRAMES.append(image.copy())
                    _ACTIVE["frames_captured"] = len(_FRAMES)
            except Exception as exc:
                _console(f"[recorder_gif] frame capture failed: {type(exc).__name__}: {exc}")
            next_capture += frame_interval
            if next_capture < time.perf_counter() - frame_interval:
                next_capture = time.perf_counter() + frame_interval
    except Exception as exc:
        _console(f"[recorder_gif] capture loop failed: {type(exc).__name__}: {exc}")
    finally:
        with _LOCK:
            if _ACTIVE and _ACTIVE.get("recording_id") == recording_id:
                _ACTIVE["is_recording"] = False
                _ACTIVE["stopped_at"] = time.time()


def _save_gif(recording_id, frames, fps):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECORDINGS_DIR / f"rec_{recording_id}.gif"
    duration_ms = max(1, int(1000 / max(1, fps)))
    first = frames[0]
    rest = frames[1:]
    first.save(
        path,
        save_all=True,
        append_images=rest,
        loop=0,
        duration=duration_ms,
        optimize=True,
    )
    _cleanup_old_recordings()
    return path


def _status_payload():
    with _LOCK:
        active = dict(_ACTIVE) if _ACTIVE else None
        latest = dict(_LAST_RECORDING) if _LAST_RECORDING else None
    if active:
        started_at = float(active.get("started_at") or time.time())
        return {
            "is_recording": bool(active.get("is_recording")),
            "recording_id": active.get("recording_id"),
            "frames_captured": int(active.get("frames_captured") or 0),
            "elapsed_seconds": round(time.time() - started_at, 2),
        }
    return {
        "is_recording": False,
        "recording_id": latest.get("recording_id") if latest else None,
        "frames_captured": 0,
        "elapsed_seconds": 0,
    }


def _latest_gif_path():
    with _LOCK:
        if _LAST_RECORDING and _LAST_RECORDING.get("gif_path"):
            path = COAGENT_DIR / _LAST_RECORDING["gif_path"] if not str(_LAST_RECORDING["gif_path"]).startswith(str(COAGENT_DIR)) else None
            direct = _LAST_RECORDING["gif_path"]
            candidate = path or direct
            try:
                from pathlib import Path

                candidate = Path(candidate)
                if candidate.exists():
                    return candidate
            except Exception:
                pass
    try:
        paths = sorted(RECORDINGS_DIR.glob("rec_*.gif"), key=lambda p: p.stat().st_mtime, reverse=True)
        return paths[0] if paths else None
    except Exception:
        return None


def register_routes(app, state, require_auth):
    bp = Blueprint("recorder_gif", __name__)

    @bp.route("/recorder/gif/start", methods=["POST"])
    @require_auth
    def route_recorder_gif_start():
        global _ACTIVE, _THREAD, _FRAMES
        data = _json_body()
        fps = _clamp_int(data.get("fps", 5), 5, 1, 30)
        max_seconds = _clamp_int(data.get("max_seconds", 30), 30, 1, 3600)
        try:
            bbox = _normalize_region(data.get("region"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        with _LOCK:
            if _ACTIVE and _ACTIVE.get("is_recording"):
                return jsonify({"error": "GIF recorder is already running", **_status_payload()}), 409
            if _ACTIVE and _FRAMES:
                return jsonify({
                    "error": "previous recording has stopped; call /recorder/gif/stop before starting another",
                    **_status_payload(),
                }), 409

            recording_id = _new_recording_id()
            _FRAMES = []
            _STOP_EVENT.clear()
            _ACTIVE = {
                "recording_id": recording_id,
                "is_recording": True,
                "frames_captured": 0,
                "started_at": time.time(),
                "fps": fps,
                "max_seconds": max_seconds,
                "region": data.get("region") or None,
            }
            _THREAD = threading.Thread(
                target=_capture_loop,
                args=(recording_id, fps, max_seconds, bbox),
                name=f"recorder-gif-{recording_id}",
                daemon=True,
            )
            _THREAD.start()
        _console(f"[recorder_gif] started recording_id={recording_id} fps={fps} max_seconds={max_seconds}")
        return jsonify({"recording_id": recording_id, "status": "recording"})

    @bp.route("/recorder/gif/stop", methods=["POST"])
    @require_auth
    def route_recorder_gif_stop():
        global _ACTIVE, _THREAD, _LAST_RECORDING
        with _LOCK:
            active = dict(_ACTIVE) if _ACTIVE else None
            thread = _THREAD
        if not active:
            return jsonify({"error": "GIF recorder is not active"}), 400

        _STOP_EVENT.set()
        if thread and thread.is_alive():
            thread.join(timeout=5.0)

        with _LOCK:
            active = dict(_ACTIVE) if _ACTIVE else active
            frames = list(_FRAMES)
            recording_id = active.get("recording_id")
            fps = int(active.get("fps") or 5)

        gif_path = ""
        gif_size = 0
        if frames:
            try:
                path = _save_gif(recording_id, frames, fps)
                gif_path = str(path)
                gif_size = path.stat().st_size
            except Exception as exc:
                _console(f"[recorder_gif] GIF save failed: {type(exc).__name__}: {exc}")
                return jsonify({"error": f"failed to save GIF: {exc}", "recording_id": recording_id}), 500

        payload = {
            "recording_id": recording_id,
            "status": "stopped",
            "frames": len(frames),
            "gif_path": gif_path,
            "gif_size_bytes": gif_size,
        }
        with _LOCK:
            _LAST_RECORDING = dict(payload)
            _ACTIVE = None
            _THREAD = None
            _FRAMES.clear()
        _console(f"[recorder_gif] stopped recording_id={recording_id} frames={len(frames)} path={gif_path}")
        return jsonify(payload)

    @bp.route("/recorder/gif/status", methods=["GET"])
    @require_auth
    def route_recorder_gif_status():
        return jsonify(_status_payload())

    @bp.route("/recorder/gif/latest", methods=["GET"])
    @require_auth
    def route_recorder_gif_latest():
        path = _latest_gif_path()
        if not path or not path.exists():
            return jsonify({"error": "No GIF recording found"}), 404
        return send_file(path, mimetype="image/gif", as_attachment=False)

    app.register_blueprint(bp)
