"""Desktop video recording routes.

Records the Windows desktop to mp4 via ffmpeg using gdigrab for video and
dshow for optional system-audio loopback capture. All ffmpeg argv values
are pure ASCII and validated against tight regexes; user input is never
shell-interpolated (subprocess is invoked with a list, never shell=True).

Endpoints:
  POST /video/start        - begin a new recording
  POST /video/stop         - stop the active (or named) recording
  GET  /video/status       - report state of active + recent recordings
  GET  /video/list         - list recording files on disk
  GET  /video/devices      - list dshow audio input devices (helper)

On non-Windows hosts the endpoints return HTTP 501 rather than failing at
import time so the Linux syntax-check CI stays green.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from flask import jsonify, request

from shared import COAGENT_DIR, _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VIDEO_DIR = COAGENT_DIR / "recordings" / "video"

# Filenames: ASCII only, no path separators, no dot-prefix, .mp4 optional.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
# dshow device names: allow a permissive but ASCII-only subset. ffmpeg
# quotes the value with audio="..." so we forbid the double-quote itself.
_DEVICE_NAME_RE = re.compile(r"^[A-Za-z0-9 _.,:()\-+/]{1,120}$")
# Video codecs shipped with ffmpeg builds we might see in the wild.
_ALLOWED_VIDEO_CODECS = {
    "libx264", "libx265", "h264_nvenc", "hevc_nvenc",
    "h264_qsv", "h264_amf", "mpeg4",
}
_ALLOWED_AUDIO_CODECS = {"aac", "libmp3lame", "libopus", "pcm_s16le"}
_ALLOWED_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster",
    "fast", "medium", "slow", "slower", "veryslow",
}

_STATE_LOCK = threading.RLock()
# recording_id -> dict(pid, path, started_at, stopped_at, args, ...)
_RECORDINGS = {}
_ACTIVE_ID = None
_ID_COUNTER = 0

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

_MAX_STDERR_LINES = 200


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_ffmpeg():
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _clean_stderr(text):
    if not text:
        return ""
    stripped = _ANSI_RE.sub("", text)
    return stripped.strip()[-4000:]


def _ensure_dir():
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def _next_id():
    global _ID_COUNTER
    _ID_COUNTER += 1
    return f"rec_{int(time.time())}_{_ID_COUNTER}"


def _validate_filename(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        return False
    name = raw.strip()
    if not name:
        return None
    if name.lower().endswith(".mp4"):
        name = name[:-4]
    if not _SAFE_NAME_RE.fullmatch(name):
        return False
    return name + ".mp4"


def _validate_int(raw, lo, hi, default):
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    if val < lo or val > hi:
        return None
    return val


def _validate_choice(raw, allowed, default):
    if raw is None:
        return default
    if not isinstance(raw, str):
        return None
    if raw not in allowed:
        return None
    return raw


def _validate_region(raw):
    """Return (x, y, w, h) tuple or None if unset; False on invalid."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return False
    try:
        x = int(raw.get("x", 0))
        y = int(raw.get("y", 0))
        w = int(raw.get("w", raw.get("width", 0)))
        h = int(raw.get("h", raw.get("height", 0)))
    except (TypeError, ValueError):
        return False
    if w <= 0 or h <= 0 or w > 16384 or h > 16384:
        return False
    if abs(x) > 32768 or abs(y) > 32768:
        return False
    return (x, y, w, h)


def _validate_device(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        return False
    name = raw.strip()
    if not name:
        return None
    if not _DEVICE_NAME_RE.fullmatch(name):
        return False
    return name


def _build_ffmpeg_argv(ffmpeg, out_path, fps, region, video_codec, preset,
                       crf, audio_device, audio_codec, audio_bitrate):
    """Return an ffmpeg argv list. All strings are pure ASCII."""
    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]

    # gdigrab video input.
    argv += ["-f", "gdigrab", "-framerate", str(int(fps))]
    if region:
        x, y, w, h = region
        argv += [
            "-offset_x", str(x),
            "-offset_y", str(y),
            "-video_size", f"{w}x{h}",
            "-i", "desktop",
        ]
    else:
        argv += ["-i", "desktop"]

    # Optional dshow audio input (system-audio loopback via Stereo Mix or
    # a WASAPI loopback capturer registered as a dshow device).
    if audio_device:
        argv += [
            "-f", "dshow",
            "-i", f"audio={audio_device}",
        ]

    # Encoding.
    argv += ["-c:v", video_codec]
    if video_codec in ("libx264", "libx265"):
        argv += ["-preset", preset, "-crf", str(int(crf))]
    argv += ["-pix_fmt", "yuv420p"]

    if audio_device:
        argv += ["-c:a", audio_codec]
        if audio_codec != "pcm_s16le":
            argv += ["-b:a", f"{int(audio_bitrate)}k"]

    argv += ["-movflags", "+faststart", str(out_path)]
    return argv


def _spawn_ffmpeg(argv):
    """Launch ffmpeg detached from any console.

    Returns (proc, stderr_buffer, drain_thread). A background daemon thread
    continuously drains ffmpeg's stderr pipe into ``stderr_buffer`` so the OS
    pipe never fills (~64KB) and deadlocks the recording.
    """
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NO_WINDOW,
        close_fds=True,
    )
    stderr_buffer = []
    buf_lock = threading.Lock()

    def _drain():
        try:
            for line in proc.stderr:
                with buf_lock:
                    stderr_buffer.append(line.decode("utf-8", "replace"))
                    if len(stderr_buffer) > _MAX_STDERR_LINES:
                        del stderr_buffer[:-_MAX_STDERR_LINES]
        except Exception:
            pass

    drain_thread = threading.Thread(
        target=_drain, name="ffmpeg-stderr-drain", daemon=True,
    )
    try:
        drain_thread.start()
    except Exception:
        # If the drain thread can't start, no one empties ffmpeg's stderr pipe;
        # the ~64KB buffer fills and deadlocks the recording. Kill the proc
        # instead of leaking a wedged ffmpeg.
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass
        raise RuntimeError("failed to start ffmpeg stderr drain thread")
    return proc, stderr_buffer, drain_thread, buf_lock


def _proc_status(entry):
    global _ACTIVE_ID
    proc = entry.get("proc")
    if proc is None:
        return entry.get("state", "unknown")
    rc = proc.poll()
    if rc is None:
        return "recording"
    entry["returncode"] = rc
    if not entry.get("stopped_at"):
        entry["stopped_at"] = time.time()
    state = "finished" if rc == 0 else "error"
    # If the active recording died on its own, clear the stale active pointer
    # so /video/status and /video/stop don't keep reporting a dead recording.
    if _ACTIVE_ID is not None:
        active = _RECORDINGS.get(_ACTIVE_ID)
        if active is entry:
            _ACTIVE_ID = None
    return state


def _snapshot_entry(rec_id, entry):
    state = _proc_status(entry)
    started = entry.get("started_at")
    stopped = entry.get("stopped_at")
    duration = None
    if started:
        end = stopped or time.time()
        duration = round(end - started, 3)
    path = entry.get("path")
    size = None
    if path and os.path.isfile(path):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
    return {
        "recording_id": rec_id,
        "state": state,
        "path": path,
        "size": size,
        "started_at": started,
        "stopped_at": stopped,
        "duration_seconds": duration,
        "returncode": entry.get("returncode"),
        "pid": entry.get("pid"),
        "audio_device": entry.get("audio_device"),
        "video_codec": entry.get("video_codec"),
        "fps": entry.get("fps"),
        "region": entry.get("region"),
        "stderr_tail": _clean_stderr(entry.get("stderr", "")),
    }


def _drain_stderr(entry):
    """Join the background-drained stderr buffer into entry['stderr']."""
    drain_thread = entry.get("drain_thread")
    if drain_thread is not None and drain_thread.is_alive():
        drain_thread.join(timeout=2.0)
    buf = entry.get("stderr_buffer") or []
    if buf:
        lock = entry.get("stderr_lock")
        if lock is not None:
            with lock:
                entry["stderr"] = "".join(list(buf))
        else:
            entry["stderr"] = "".join(list(buf))


def _stop_recording(rec_id, timeout=8.0):
    global _ACTIVE_ID
    entry = _RECORDINGS.get(rec_id)
    if not entry:
        return None, "unknown recording_id"
    proc = entry.get("proc")
    if proc is None:
        return _snapshot_entry(rec_id, entry), None
    if proc.poll() is None:
        # ffmpeg listens for 'q' on stdin as a clean shutdown signal.
        try:
            if proc.stdin:
                proc.stdin.write(b"q")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=3.0)
                except Exception:
                    pass
    _drain_stderr(entry)
    entry["returncode"] = proc.returncode
    if not entry.get("stopped_at"):
        entry["stopped_at"] = time.time()
    if _ACTIVE_ID == rec_id:
        _ACTIVE_ID = None
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        if proc.stderr:
            proc.stderr.close()
    except Exception:
        pass
    return _snapshot_entry(rec_id, entry), None


def _list_files():
    _ensure_dir()
    items = []
    try:
        for p in sorted(VIDEO_DIR.iterdir()):
            if not p.is_file() or p.suffix.lower() != ".mp4":
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            items.append({
                "filename": p.name,
                "path": str(p),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    except FileNotFoundError:
        pass
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _list_dshow_audio_devices(ffmpeg, timeout=8):
    """Parse ffmpeg -list_devices output for audio device names."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "dshow",
             "-list_devices", "true", "-i", "dummy"],
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return [], str(exc)
    text = (proc.stderr or b"").decode("utf-8", "replace")
    devices = []
    in_audio = False
    for line in text.splitlines():
        low = line.lower()
        if "directshow audio devices" in low:
            in_audio = True
            continue
        if "directshow video devices" in low:
            in_audio = False
            continue
        if not in_audio:
            continue
        m = re.search(r'"([^"]+)"', line)
        if m and "alternative name" not in low:
            devices.append(m.group(1))
    # De-duplicate preserving order.
    seen = set()
    unique = []
    for d in devices:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique, None


def register_routes(app, state, require_auth):
    ffmpeg = _find_ffmpeg()
    ffmpeg_available = bool(ffmpeg and os.path.isfile(ffmpeg))
    _log(f"routes_video registered (ffmpeg={'yes' if ffmpeg_available else 'no'})")

    @app.route("/video/start", methods=["POST"])
    @require_auth
    def route_video_start():
        global _ACTIVE_ID
        if os.name != "nt":
            return _windows_only()
        if not ffmpeg_available:
            return jsonify({"error": "ffmpeg not found on PATH"}), 501

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        with _STATE_LOCK:
            if _ACTIVE_ID is not None:
                active = _RECORDINGS.get(_ACTIVE_ID)
                if active and _proc_status(active) == "recording":
                    return jsonify({
                        "error": "a recording is already active",
                        "recording_id": _ACTIVE_ID,
                    }), 409

            filename = _validate_filename(body.get("filename"))
            if filename is False:
                return jsonify({"error": "invalid filename"}), 400
            if filename is None:
                filename = time.strftime("desktop_%Y%m%d_%H%M%S.mp4")

            fps = _validate_int(body.get("fps"), 1, 120, 30)
            if fps is None:
                return jsonify({"error": "invalid fps (1-120)"}), 400

            crf = _validate_int(body.get("crf"), 0, 51, 23)
            if crf is None:
                return jsonify({"error": "invalid crf (0-51)"}), 400

            audio_bitrate = _validate_int(
                body.get("audio_bitrate"), 32, 512, 160,
            )
            if audio_bitrate is None:
                return jsonify({"error": "invalid audio_bitrate (32-512)"}), 400

            video_codec = _validate_choice(
                body.get("video_codec"), _ALLOWED_VIDEO_CODECS, "libx264",
            )
            if video_codec is None:
                return jsonify({
                    "error": "invalid video_codec",
                    "allowed": sorted(_ALLOWED_VIDEO_CODECS),
                }), 400

            audio_codec = _validate_choice(
                body.get("audio_codec"), _ALLOWED_AUDIO_CODECS, "aac",
            )
            if audio_codec is None:
                return jsonify({
                    "error": "invalid audio_codec",
                    "allowed": sorted(_ALLOWED_AUDIO_CODECS),
                }), 400

            preset = _validate_choice(
                body.get("preset"), _ALLOWED_PRESETS, "veryfast",
            )
            if preset is None:
                return jsonify({
                    "error": "invalid preset",
                    "allowed": sorted(_ALLOWED_PRESETS),
                }), 400

            region = _validate_region(body.get("region"))
            if region is False:
                return jsonify({"error": "invalid region"}), 400

            audio_device_raw = body.get("audio_device")
            if audio_device_raw is None and body.get("system_audio"):
                # Best-effort default for Realtek loopback.
                audio_device_raw = "Stereo Mix"
            audio_device = _validate_device(audio_device_raw)
            if audio_device is False:
                return jsonify({"error": "invalid audio_device"}), 400

            _ensure_dir()
            out_path = VIDEO_DIR / filename

            argv = _build_ffmpeg_argv(
                ffmpeg, out_path, fps, region, video_codec, preset, crf,
                audio_device, audio_codec, audio_bitrate,
            )

            try:
                proc, stderr_buffer, drain_thread, buf_lock = _spawn_ffmpeg(argv)
            except (OSError, RuntimeError) as exc:
                return jsonify({"error": f"spawn failed: {exc}"}), 500

            # ffmpeg exits almost immediately on bad args; give it a moment
            # then surface stderr rather than reporting a phantom recording.
            time.sleep(0.4)
            if proc.poll() is not None:
                err = ""
                try:
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
                    if drain_thread is not None and drain_thread.is_alive():
                        drain_thread.join(timeout=1.0)
                    with buf_lock:
                        err = "".join(list(stderr_buffer))
                finally:
                    try:
                        if proc.stdin:
                            proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        if proc.stderr:
                            proc.stderr.close()
                    except Exception:
                        pass
                return jsonify({
                    "error": "ffmpeg exited immediately",
                    "returncode": proc.returncode,
                    "stderr": _clean_stderr(err),
                    "argv": argv,
                }), 500

            rec_id = _next_id()
            entry = {
                "proc": proc,
                "pid": proc.pid,
                "path": str(out_path),
                "started_at": time.time(),
                "stopped_at": None,
                "returncode": None,
                "stderr": "",
                "stderr_buffer": stderr_buffer,
                "stderr_lock": buf_lock,
                "drain_thread": drain_thread,
                "argv": argv,
                "fps": fps,
                "region": list(region) if region else None,
                "video_codec": video_codec,
                "audio_device": audio_device,
                "audio_codec": audio_codec if audio_device else None,
            }
            _RECORDINGS[rec_id] = entry
            _ACTIVE_ID = rec_id

        _log(
            f"video/start id={rec_id} pid={entry['pid']} audio={audio_device} "
            f"codec={video_codec} fps={fps}"
        )
        return jsonify({
            "status": "ok",
            **_snapshot_entry(rec_id, entry),
        })

    @app.route("/video/stop", methods=["POST"])
    @require_auth
    def route_video_stop():
        if os.name != "nt":
            return _windows_only()
        if not ffmpeg_available:
            return jsonify({"error": "ffmpeg not found on PATH"}), 501

        body = _json_body()
        rec_id = None
        if isinstance(body, dict):
            raw = body.get("recording_id")
            if isinstance(raw, str) and raw.strip():
                rec_id = raw.strip()

        with _STATE_LOCK:
            if rec_id is None:
                rec_id = _ACTIVE_ID
            if rec_id is None:
                return jsonify({"error": "no active recording"}), 404
            if rec_id not in _RECORDINGS:
                return jsonify({"error": "unknown recording_id"}), 404
            snap, err = _stop_recording(rec_id)

        if err:
            return jsonify({"error": err}), 400
        _log(f"video/stop id={rec_id} state={snap['state']} size={snap['size']}")
        return jsonify({"status": "ok", **snap})

    @app.route("/video/status", methods=["GET", "POST"])
    @require_auth
    def route_video_status():
        if os.name != "nt":
            return _windows_only()
        rec_id = None
        if request.method == "POST":
            body = _json_body()
            if isinstance(body, dict):
                raw = body.get("recording_id")
                if isinstance(raw, str) and raw.strip():
                    rec_id = raw.strip()
        if rec_id is None:
            rec_id = request.args.get("recording_id") or None

        with _STATE_LOCK:
            if rec_id:
                entry = _RECORDINGS.get(rec_id)
                if not entry:
                    return jsonify({"error": "unknown recording_id"}), 404
                return jsonify({
                    "active_id": _ACTIVE_ID,
                    "recording": _snapshot_entry(rec_id, entry),
                })
            recordings = [
                _snapshot_entry(rid, e) for rid, e in _RECORDINGS.items()
            ]

        return jsonify({
            "active_id": _ACTIVE_ID,
            "count": len(recordings),
            "recordings": recordings,
            "ffmpeg_available": ffmpeg_available,
        })

    @app.route("/video/list", methods=["GET", "POST"])
    @require_auth
    def route_video_list():
        files = _list_files()
        return jsonify({
            "dir": str(VIDEO_DIR),
            "count": len(files),
            "files": files,
        })

    @app.route("/video/devices", methods=["GET", "POST"])
    @require_auth
    def route_video_devices():
        if os.name != "nt":
            return _windows_only()
        if not ffmpeg_available:
            return jsonify({"error": "ffmpeg not found on PATH"}), 501
        devices, err = _list_dshow_audio_devices(ffmpeg)
        payload = {
            "audio_devices": devices,
            "count": len(devices),
        }
        if err:
            payload["error"] = err
        return jsonify(payload)
