"""Screen streaming routes for WebSocket, SSE, and MJPEG clients."""
import base64, json, queue, threading, time
from flask import Response, jsonify, request
from shared import _log

try:
    from flask_sock import Sock
    HAS_FLASK_SOCK = True
except ImportError:
    Sock = None
    HAS_FLASK_SOCK = False

_STREAMS = {}
_STREAM_LOCK = threading.Lock()
_FRAME_INTERVAL = 0.2

# Latest frame cache — written by broadcast loop, read by /snapshot
_LATEST_FRAMES = {}
_LATEST_FRAMES_LOCK = threading.Lock()


def _stream_params():
    from routes_ocr import _coerce_monitor_index
    monitor_index = _coerce_monitor_index(request.args.get("monitor", 0))
    try:
        quality = int(request.args.get("quality", 75))
    except (TypeError, ValueError):
        quality = 75
    quality = max(20, min(95, quality))
    return monitor_index, quality


def _stream_key(monitor_index, quality):
    return f"{monitor_index}:{quality}"


def _put_latest(client_queue, frame):
    try:
        client_queue.put_nowait(frame)
    except queue.Full:
        try:
            client_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            client_queue.put_nowait(frame)
        except queue.Full:
            pass


def _broadcast_loop(key, monitor_index, quality):
    from routes_ocr import _capture_jpeg
    _log(f"Screen stream started monitor={monitor_index} quality={quality}")
    consecutive_errors = 0
    try:
        while True:
            with _STREAM_LOCK:
                entry = _STREAMS.get(key)
                if not entry or not entry["clients"]:
                    _STREAMS.pop(key, None)
                    return
                clients = list(entry["clients"])
            started = time.time()
            try:
                frame = _capture_jpeg(force=True, quality=quality, monitor_index=monitor_index)
            except Exception as exc:
                consecutive_errors += 1
                _log(f"Screen stream capture error ({consecutive_errors}): {type(exc).__name__}: {exc}")
                if consecutive_errors > 30:
                    _log(f"Screen stream aborting after {consecutive_errors} consecutive capture failures")
                    with _STREAM_LOCK:
                        _STREAMS.pop(key, None)
                    return
                time.sleep(1.0)
                continue
            consecutive_errors = 0
            if frame:
                payload = {
                    "jpeg": frame,
                    "timestamp": started,
                    "monitor_index": monitor_index,
                    "quality": quality,
                }
                with _LATEST_FRAMES_LOCK:
                    _LATEST_FRAMES[key] = payload
                for client_queue in clients:
                    _put_latest(client_queue, payload)
            elapsed = time.time() - started
            time.sleep(max(0.01, _FRAME_INTERVAL - elapsed))
    finally:
        with _STREAM_LOCK:
            _STREAMS.pop(key, None)
        _log(f"Screen stream stopped monitor={monitor_index} quality={quality}")


def _subscribe(monitor_index, quality):
    key = _stream_key(monitor_index, quality)
    client_queue = queue.Queue(maxsize=2)
    with _STREAM_LOCK:
        entry = _STREAMS.get(key)
        if not entry:
            entry = {"clients": set(), "thread": None}
            _STREAMS[key] = entry
        entry["clients"].add(client_queue)
        thread = entry.get("thread")
        if not thread or not thread.is_alive():
            thread = threading.Thread(target=_broadcast_loop,
                                      args=(key, monitor_index, quality),
                                      daemon=True)
            entry["thread"] = thread
            thread.start()
    return key, client_queue


def _unsubscribe(key, client_queue):
    with _STREAM_LOCK:
        entry = _STREAMS.get(key)
        if not entry:
            return
        entry["clients"].discard(client_queue)


def _active_stream_count():
    with _STREAM_LOCK:
        return sum(len(entry["clients"]) for entry in _STREAMS.values())


def register_routes(app, state, require_auth):
    if HAS_FLASK_SOCK:
        sock = Sock(app)

        @sock.route("/screen/stream")
        @require_auth
        def route_screen_stream(ws):
            monitor_index, quality = _stream_params()
            key, client_queue = _subscribe(monitor_index, quality)
            try:
                while True:
                    frame = client_queue.get(timeout=10)
                    jpeg = frame.get("jpeg", b"")
                    if jpeg:
                        ws.send(jpeg)
            except Exception as e:
                _log(f"WebSocket screen stream closed: {type(e).__name__}: {e}")
            finally:
                _unsubscribe(key, client_queue)
    else:
        @app.route("/screen/stream", methods=["GET"])
        @require_auth
        def route_screen_stream_unavailable():
            return jsonify({"error": "flask_sock not installed", "websocket": False}), 503

    @app.route("/events/screen", methods=["GET"])
    @require_auth
    def route_events_screen():
        monitor_index, quality = _stream_params()
        key, client_queue = _subscribe(monitor_index, quality)

        def generate():
            try:
                status = {"running": True, "monitor_index": monitor_index,
                          "quality": quality, "fps": 5}
                yield f"event: status\ndata: {json.dumps(status)}\n\n"
                while True:
                    try:
                        frame = client_queue.get(timeout=15)
                        jpeg = frame.get("jpeg", b"")
                        if not jpeg:
                            continue
                        payload = {
                            "format": "jpeg",
                            "data": base64.b64encode(jpeg).decode(),
                            "timestamp": frame.get("timestamp"),
                            "monitor_index": frame.get("monitor_index", monitor_index),
                            "quality": frame.get("quality", quality),
                        }
                        yield f"event: screen\ndata: {json.dumps(payload)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                _unsubscribe(key, client_queue)

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no",
                                 "X-Active-Screen-Streams": str(_active_stream_count())})

    @app.route("/screen/stream/mjpeg", methods=["GET"])
    @require_auth
    def route_screen_stream_mjpeg():
        """Low-latency MJPEG stream over multipart/x-mixed-replace.
        Query params: fps (1-30, default 5), quality (20-95, default 60), monitor (0-N)."""
        from routes_ocr import _coerce_monitor_index, _capture_jpeg
        monitor_index = _coerce_monitor_index(request.args.get("monitor", 0))
        try:
            fps = int(request.args.get("fps", 5))
        except (TypeError, ValueError):
            fps = 5
        fps = max(1, min(30, fps))
        try:
            quality = int(request.args.get("quality", 60))
        except (TypeError, ValueError):
            quality = 60
        quality = max(20, min(95, quality))

        frame_interval = 1.0 / fps

        def generate():
            consecutive_errors = 0
            while True:
                t0 = time.time()
                try:
                    jpeg = _capture_jpeg(force=True, quality=quality,
                                         monitor_index=monitor_index)
                    consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors += 1
                    _log(f"MJPEG capture error ({consecutive_errors}): {exc}")
                    if consecutive_errors > 30:
                        return
                    time.sleep(frame_interval)
                    continue
                if jpeg:
                    header = (
                        "--frame\r\n"
                        "Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n"
                        "\r\n"
                    ).encode()
                    yield header + jpeg + b"\r\n"
                elapsed = time.time() - t0
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                     "X-FPS": str(fps), "X-Quality": str(quality)},
        )

    @app.route("/screen/stream/snapshot", methods=["GET"])
    @require_auth
    def route_screen_stream_snapshot():
        """Return the latest JPEG frame — from the active broadcast loop if running,
        otherwise captured fresh. Useful for quick checks without opening a stream."""
        from routes_ocr import _coerce_monitor_index, _capture_jpeg
        monitor_index = _coerce_monitor_index(request.args.get("monitor", 0))
        try:
            quality = int(request.args.get("quality", 60))
        except (TypeError, ValueError):
            quality = 60
        quality = max(20, min(95, quality))
        key = _stream_key(monitor_index, quality)

        with _LATEST_FRAMES_LOCK:
            cached = _LATEST_FRAMES.get(key)

        if cached:
            jpeg = cached.get("jpeg", b"")
            if jpeg:
                return Response(
                    jpeg, mimetype="image/jpeg",
                    headers={"X-Timestamp": str(cached.get("timestamp", 0)),
                             "X-Monitor": str(monitor_index),
                             "X-Source": "stream-cache"},
                )

        try:
            jpeg = _capture_jpeg(force=True, quality=quality,
                                  monitor_index=monitor_index)
            if jpeg:
                return Response(
                    jpeg, mimetype="image/jpeg",
                    headers={"X-Monitor": str(monitor_index),
                             "X-Source": "direct"},
                )
        except Exception as exc:
            _log(f"Snapshot direct capture failed: {exc}")

        return jsonify({"error": "Snapshot unavailable — no active stream and direct capture failed"}), 503
