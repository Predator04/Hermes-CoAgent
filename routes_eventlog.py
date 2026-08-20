"""Windows Event Log subscription routes.

Endpoints:
  GET/POST /eventlog/tail         - SSE stream of new events from a Windows log
  POST     /eventlog/subscribe    - register a webhook URL for new events
  POST     /eventlog/unsubscribe  - remove a previously registered subscription

Uses PowerShell Get-WinEvent with a FilterHashtable to fetch events newer than
the last poll timestamp. On non-Windows hosts the endpoints return HTTP 501
rather than failing at import time so the Linux syntax-check CI stays green.
All PowerShell / subprocess strings are pure ASCII.
"""

import json as _json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from flask import Response, jsonify, request

from shared import _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Windows event log channel names are ASCII with a fairly narrow character set.
_LOG_NAME_RE = re.compile(r"^[A-Za-z0-9 _/\-.]{1,128}$")

# Get-WinEvent Level field. 1=Critical 2=Error 3=Warning 4=Information 5=Verbose.
_LEVEL_MAP = {
    "critical": 1,
    "error": 2,
    "warning": 3,
    "warn": 3,
    "info": 4,
    "information": 4,
    "verbose": 5,
}

_MAX_SEEN_IDS = 1000
_DEFAULT_POLL_INTERVAL = 5.0
_MIN_POLL_INTERVAL = 1.0
_MAX_POLL_INTERVAL = 60.0
_WEBHOOK_TIMEOUT = 5.0

_SUB_LOCK = threading.Lock()
_SUBSCRIBERS = {}       # sub_id -> {"url", "log", "level", "poll_key", ...}

_POLLERS_LOCK = threading.Lock()
_POLLERS = {}           # poll_key -> {"thread": Thread, "stop": Event}


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_powershell():
    return (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _run_ps(script, timeout=25):
    """Run a PowerShell script and return (stdout, stderr, returncode)."""
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return "", "powershell.exe not found", -1
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _parse_json_output(text):
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = _json.loads(text)
    except ValueError as exc:
        _log(f"eventlog: JSON parse failed: {exc}; raw={text[:200]!r}")
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _normalize_log(name, default="System"):
    if not isinstance(name, str) or not name.strip():
        return default
    value = name.strip()
    if not _LOG_NAME_RE.fullmatch(value):
        return default
    return value


def _normalize_level(level):
    if level is None or level == "":
        return None
    if isinstance(level, bool):
        return None
    if isinstance(level, int):
        return level if level in (1, 2, 3, 4, 5) else None
    if isinstance(level, str):
        s = level.strip().lower()
        if s.isdigit():
            n = int(s)
            return n if n in (1, 2, 3, 4, 5) else None
        return _LEVEL_MAP.get(s)
    return None


def _iso_local(ts):
    """Format a unix timestamp as ISO-8601 local time with no tz suffix."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _build_query_script(log_name, level, start_time_iso, max_events):
    """Build a pure-ASCII PowerShell one-liner that fetches events since start_time_iso."""
    filter_parts = [
        f"LogName='{log_name}'",
        f"StartTime=[datetime]'{start_time_iso}'",
    ]
    if level is not None:
        filter_parts.append(f"Level={int(level)}")
    filter_str = "; ".join(filter_parts)
    return (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"$events = Get-WinEvent -FilterHashtable @{{ {filter_str} }} "
        f"-MaxEvents {int(max_events)} -ErrorAction SilentlyContinue; "
        "if ($null -eq $events) { '[]' } else { "
        "$events | Sort-Object TimeCreated | Select-Object "
        "@{n='RecordId';e={$_.RecordId}}, "
        "@{n='TimeCreated';e={$_.TimeCreated.ToString('o')}}, "
        "@{n='LogName';e={$_.LogName}}, "
        "@{n='ProviderName';e={$_.ProviderName}}, "
        "@{n='Id';e={$_.Id}}, "
        "@{n='Level';e={$_.Level}}, "
        "@{n='LevelDisplayName';e={$_.LevelDisplayName}}, "
        "@{n='MachineName';e={$_.MachineName}}, "
        "@{n='UserId';e={ if ($_.UserId) { $_.UserId.Value } else { '' } }}, "
        "@{n='Message';e={$_.Message}} | "
        "ConvertTo-Json -Depth 4 -Compress }"
    )


def _fetch_events(log_name, level, start_ts, max_events=100):
    """Return (events_list_oldest_first, error_or_none)."""
    script = _build_query_script(log_name, level, _iso_local(start_ts), max_events)
    out, err, rc = _run_ps(script, timeout=25)
    if rc != 0:
        return [], (err.strip() or f"Get-WinEvent failed (rc={rc})")
    return _parse_json_output(out), None


def _poll_key(log_name, level):
    return f"{log_name}|{level if level is not None else '*'}"


def _valid_webhook_url(url):
    if not isinstance(url, str) or not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def _dispatch_webhooks(subscribers, events):
    def _worker():
        payload_bytes = _json.dumps({"events": events}).encode("utf-8")
        for sub in subscribers:
            url = sub.get("url")
            if not url:
                continue
            try:
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT):
                    pass
            except (urllib.error.URLError, OSError, ValueError) as exc:
                _log(f"eventlog: webhook {url} failed: {exc}")
    threading.Thread(target=_worker, name="eventlog-webhook", daemon=True).start()


def _poll_loop(key, log_name, level, interval, stop_evt):
    _log(f"eventlog poller start {key} interval={interval}")
    last_ts = time.time()
    seen_ids = {}
    consecutive_errors = 0
    while not stop_evt.is_set():
        try:
            events, err = _fetch_events(log_name, level, last_ts, max_events=200)
            if err:
                consecutive_errors += 1
                _log(f"eventlog poll error {key}: {err}")
                if consecutive_errors > 10:
                    break
            else:
                consecutive_errors = 0
                new_events = []
                for ev in events:
                    rid = ev.get("RecordId")
                    if rid is None or rid in seen_ids:
                        continue
                    seen_ids[rid] = True
                    new_events.append(ev)
                while len(seen_ids) > _MAX_SEEN_IDS:
                    seen_ids.pop(next(iter(seen_ids)))
                if new_events:
                    with _SUB_LOCK:
                        subs = [s for s in _SUBSCRIBERS.values()
                                if s.get("poll_key") == key]
                    if subs:
                        _dispatch_webhooks(subs, new_events)
                last_ts = time.time()
        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            _log(f"eventlog poll fatal {key}: {exc}")
            if consecutive_errors > 10:
                break
        if stop_evt.wait(interval):
            break
    with _POLLERS_LOCK:
        _POLLERS.pop(key, None)
    _log(f"eventlog poller stop {key}")


def _ensure_poller(key, log_name, level, interval):
    with _POLLERS_LOCK:
        existing = _POLLERS.get(key)
        if existing and existing["thread"].is_alive():
            return
        stop_evt = threading.Event()
        thread = threading.Thread(
            target=_poll_loop,
            args=(key, log_name, level, interval, stop_evt),
            name=f"eventlog-poller-{key}",
            daemon=True,
        )
        _POLLERS[key] = {"thread": thread, "stop": stop_evt}
        thread.start()


def register_routes(app, state, require_auth):
    ps_exe = _find_powershell()
    ps_available = bool(ps_exe and os.path.isfile(ps_exe))

    @app.route("/eventlog/tail", methods=["GET", "POST"])
    @require_auth
    def route_eventlog_tail():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body() if request.method == "POST" else {}
        args = request.args

        def _pick(name):
            if isinstance(body, dict) and body.get(name) not in (None, ""):
                return body.get(name)
            return args.get(name)

        log_name = _normalize_log(_pick("log"), default="System")
        level = _normalize_level(_pick("level"))
        try:
            interval = float(_pick("interval") or _DEFAULT_POLL_INTERVAL)
        except (TypeError, ValueError):
            interval = _DEFAULT_POLL_INTERVAL
        interval = max(_MIN_POLL_INTERVAL, min(_MAX_POLL_INTERVAL, interval))
        try:
            max_events = int(_pick("max_events") or 100)
        except (TypeError, ValueError):
            max_events = 100
        max_events = max(1, min(500, max_events))

        def generate():
            status = {
                "log": log_name,
                "level": level,
                "interval_seconds": interval,
                "max_events": max_events,
            }
            yield f"event: status\ndata: {_json.dumps(status)}\n\n"
            last_ts = time.time()
            seen_ids = {}
            consecutive_errors = 0
            try:
                while True:
                    events, err = _fetch_events(
                        log_name, level, last_ts, max_events=max_events
                    )
                    if err:
                        consecutive_errors += 1
                        yield (
                            "event: error\n"
                            f"data: {_json.dumps({'error': err})}\n\n"
                        )
                        if consecutive_errors > 5:
                            return
                    else:
                        consecutive_errors = 0
                        emitted = False
                        for ev in events:
                            rid = ev.get("RecordId")
                            if rid is None or rid in seen_ids:
                                continue
                            seen_ids[rid] = True
                            emitted = True
                            yield (
                                "event: eventlog\n"
                                f"data: {_json.dumps(ev)}\n\n"
                            )
                        while len(seen_ids) > _MAX_SEEN_IDS:
                            seen_ids.pop(next(iter(seen_ids)))
                        last_ts = time.time()
                        if not emitted:
                            yield ": keepalive\n\n"
                    time.sleep(interval)
            except GeneratorExit:
                return

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/eventlog/subscribe", methods=["POST"])
    @require_auth
    def route_eventlog_subscribe():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        url = body.get("url") or body.get("webhook")
        if not url:
            return _missing_field("url")
        if not _valid_webhook_url(url):
            return jsonify({"error": "url must be http:// or https://"}), 400

        log_name = _normalize_log(body.get("log"), default="System")
        level = _normalize_level(body.get("level"))
        try:
            interval = float(body.get("interval", _DEFAULT_POLL_INTERVAL))
        except (TypeError, ValueError):
            interval = _DEFAULT_POLL_INTERVAL
        interval = max(_MIN_POLL_INTERVAL, min(_MAX_POLL_INTERVAL, interval))

        key = _poll_key(log_name, level)
        sub_id = uuid.uuid4().hex
        with _SUB_LOCK:
            _SUBSCRIBERS[sub_id] = {
                "url": url,
                "log": log_name,
                "level": level,
                "poll_key": key,
                "interval": interval,
                "created": time.time(),
            }
            total = len(_SUBSCRIBERS)

        _ensure_poller(key, log_name, level, interval)
        _log(f"eventlog/subscribe id={sub_id} log={log_name} url={url}")
        return jsonify({
            "status": "ok",
            "subscription_id": sub_id,
            "url": url,
            "log": log_name,
            "level": level,
            "poll_interval_seconds": interval,
            "subscriber_count": total,
        })

    @app.route("/eventlog/unsubscribe", methods=["POST"])
    @require_auth
    def route_eventlog_unsubscribe():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        if not isinstance(body, dict):
            body = {}
        sub_id = body.get("subscription_id") or body.get("id")
        if not sub_id:
            return _missing_field("subscription_id")

        with _SUB_LOCK:
            removed = _SUBSCRIBERS.pop(sub_id, None)
            total = len(_SUBSCRIBERS)
            remaining_keys = {s.get("poll_key") for s in _SUBSCRIBERS.values()}

        if removed is None:
            return jsonify({"error": "unknown subscription_id"}), 404

        stopped_key = removed.get("poll_key")
        if stopped_key and stopped_key not in remaining_keys:
            with _POLLERS_LOCK:
                entry = _POLLERS.get(stopped_key)
                if entry:
                    stop_evt = entry.get("stop")
                    if stop_evt:
                        stop_evt.set()

        _log(f"eventlog/unsubscribe id={sub_id}")
        return jsonify({
            "status": "ok",
            "subscription_id": sub_id,
            "subscriber_count": total,
        })
