"""Companion browser extension relay.

Bridges the CoAgent server to a Chrome/Brave/Edge MV3 companion extension
running inside the user's REAL browser (with real logged-in sessions). The
extension is a polling client: it pulls commands from CoAgent over long-poll
HTTP, executes them in the active tab, and posts the result back.

Command lifecycle:
    1. Agent POSTs /browser/companion/command with a command object.
       CoAgent assigns command_id, queues it, blocks on a Condition.
    2. Extension GETs /browser/companion/poll (long-poll, ~20s).
    3. Extension executes the command, POSTs /browser/companion/result.
    4. The blocked /command call wakes and returns the result to the agent.
"""
import time
import uuid
import threading
from collections import deque

from flask import jsonify, request

from shared import COAGENT_DIR, _log  # noqa: F401


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_COMMAND_TYPES = {
    "navigate",
    "click",
    "type",
    "read",
    "extract",
    "evaluate",
    "scroll",
    "screenshot",
    "tabs",
}

DEFAULT_COMMAND_TIMEOUT = 60.0
MAX_COMMAND_TIMEOUT = 300.0
POLL_HOLD_SECONDS = 20.0
MAX_PENDING_QUEUE = 100
MAX_INFLIGHT_COMMANDS = 16
CONNECTED_WINDOW_SECONDS = 60.0
RESULT_RETENTION_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Shared relay state (module-level; guarded by _lock via Condition)
# ---------------------------------------------------------------------------

_cond = threading.Condition()

# Number of /command calls currently blocked waiting for a result. Capped to
# avoid exhausting Waitress worker threads (each waiter holds a worker for up
# to MAX_COMMAND_TIMEOUT seconds).
_inflight = 0

# Pending commands not yet claimed by a /poll call.
# Each entry: {"command_id": str, "command": dict, "enqueued_at": float}
_pending = deque()

# Results keyed by command_id.
# Each entry: {"result": <payload or None>,
#              "delivered": bool,
#              "posted_at": float or None,
#              "created_at": float}
_results = {}

# Last time the extension successfully polled or posted a result.
_last_seen = {"ts": None}

# Most recent tab metadata reported by the extension (best-effort).
_active_tab = {"info": None}


# ---------------------------------------------------------------------------
# Helpers (must be called while holding _cond)
# ---------------------------------------------------------------------------


def _now():
    return time.time()


def _gc_results_locked():
    """Drop delivered result records older than RESULT_RETENTION_SECONDS."""
    if not _results:
        return
    cutoff = _now() - RESULT_RETENTION_SECONDS
    stale = [
        cid
        for cid, rec in _results.items()
        if rec.get("delivered")
        and rec.get("posted_at") is not None
        and rec["posted_at"] < cutoff
    ]
    for cid in stale:
        _results.pop(cid, None)


def _connected_locked():
    ts = _last_seen["ts"]
    return ts is not None and (_now() - ts) <= CONNECTED_WINDOW_SECONDS


def _snapshot_status_locked():
    return {
        "connected": _connected_locked(),
        "last_seen": _last_seen["ts"],
        "pending": len(_pending),
        "active_tab": _active_tab["info"],
    }


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_routes(app, state, require_auth):
    @app.route("/browser/companion/command", methods=["POST"])
    @require_auth
    def route_companion_command():
        global _inflight
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        cmd_type = body.get("type")
        if not cmd_type or not isinstance(cmd_type, str):
            return jsonify({"ok": False, "error": "missing 'type'"}), 400
        if cmd_type not in KNOWN_COMMAND_TYPES:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"unknown command type: {cmd_type}",
                        "known": sorted(KNOWN_COMMAND_TYPES),
                    }
                ),
                400,
            )

        # Timeout: default 60s, cap 300s.
        raw_timeout = body.get("timeout", DEFAULT_COMMAND_TIMEOUT)
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = DEFAULT_COMMAND_TIMEOUT
        if timeout <= 0:
            timeout = DEFAULT_COMMAND_TIMEOUT
        if timeout > MAX_COMMAND_TIMEOUT:
            timeout = MAX_COMMAND_TIMEOUT

        # Build the command payload for the extension (drop server-only keys).
        command = {k: v for k, v in body.items() if k != "timeout"}

        command_id = uuid.uuid4().hex

        # Cap concurrent in-flight waits so a burst of /command calls can't
        # exhaust Waitress worker threads (each waiter blocks a worker).
        with _cond:
            if _inflight >= MAX_INFLIGHT_COMMANDS:
                return (
                    jsonify({
                        "ok": False,
                        "error": "too many in-flight companion commands",
                        "inflight": _inflight,
                    }),
                    429,
                )
            _inflight += 1

        delivered = False
        payload = None
        try:
            with _cond:
                _gc_results_locked()
                if len(_pending) >= MAX_PENDING_QUEUE:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "companion command queue full",
                                "pending": len(_pending),
                            }
                        ),
                        429,
                    )

                _pending.append(
                    {
                        "command_id": command_id,
                        "command": command,
                        "enqueued_at": _now(),
                    }
                )
                _results[command_id] = {
                    "result": None,
                    "delivered": False,
                    "posted_at": None,
                    "created_at": _now(),
                }
                _cond.notify_all()

                deadline = _now() + timeout
                while True:
                    rec = _results.get(command_id)
                    if rec is not None and rec.get("delivered"):
                        break
                    remaining = deadline - _now()
                    if remaining <= 0:
                        break
                    _cond.wait(timeout=remaining)

                rec = _results.get(command_id)
                delivered = bool(rec and rec.get("delivered"))
                payload = rec.get("result") if rec else None

                if not delivered:
                    # Timed out. Remove from pending queue if still there so the
                    # extension won't try to run a command nobody is waiting on.
                    for i, entry in enumerate(_pending):
                        if entry["command_id"] == command_id:
                            del _pending[i]
                            break
                    _results.pop(command_id, None)
        finally:
            with _cond:
                _inflight -= 1
                _cond.notify_all()

        if not delivered:
            _log(f"[companion] timeout waiting for result: {command_id}")
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "timeout waiting for companion extension",
                        "timeout": True,
                        "command_id": command_id,
                    }
                ),
                503,
            )

        payload = payload or {}
        if payload.get("ok") is False:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": payload.get("error") or "companion extension error",
                        "command_id": command_id,
                    }
                ),
                502,
            )

        return jsonify(
            {
                "ok": True,
                "command_id": command_id,
                "result": payload.get("data"),
            }
        )

    @app.route("/browser/companion/poll", methods=["GET"])
    @require_auth
    def route_companion_poll():
        # Optional tab metadata piggybacked on the poll.
        try:
            tab_hint = request.args.get("tab")
        except Exception:
            tab_hint = None

        with _cond:
            _last_seen["ts"] = _now()
            if tab_hint:
                _active_tab["info"] = tab_hint
            _gc_results_locked()

            deadline = _now() + POLL_HOLD_SECONDS
            while not _pending:
                remaining = deadline - _now()
                if remaining <= 0:
                    break
                _cond.wait(timeout=remaining)

            if not _pending:
                # Still nothing after the hold window.
                _last_seen["ts"] = _now()
                return jsonify({"command": None})

            entry = _pending.popleft()
            _last_seen["ts"] = _now()

        return jsonify(
            {
                "command_id": entry["command_id"],
                "command": entry["command"],
            }
        )

    @app.route("/browser/companion/result", methods=["POST"])
    @require_auth
    def route_companion_result():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        command_id = body.get("command_id")
        if not command_id or not isinstance(command_id, str):
            return jsonify({"ok": False, "error": "missing 'command_id'"}), 400

        ok_flag = bool(body.get("ok"))
        payload = {
            "ok": ok_flag,
            "data": body.get("data"),
            "error": body.get("error"),
        }

        with _cond:
            _last_seen["ts"] = _now()
            rec = _results.get(command_id)
            if rec is None:
                # Unknown or already-cleaned-up id. This most often means the
                # /command call timed out and gave up before the extension
                # finished. Return 404 as specified.
                _gc_results_locked()
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "unknown command_id",
                            "command_id": command_id,
                        }
                    ),
                    404,
                )

            rec["result"] = payload
            rec["delivered"] = True
            rec["posted_at"] = _now()
            _cond.notify_all()
            _gc_results_locked()

        return jsonify({"ok": True})

    @app.route("/browser/companion/status", methods=["GET"])
    @require_auth
    def route_companion_status():
        with _cond:
            _gc_results_locked()
            snap = _snapshot_status_locked()
        return jsonify(snap)

    def _status_snapshot():
        with _cond:
            return _snapshot_status_locked()

    if not hasattr(state, "companion") or state.companion is None:
        state.companion = {}
    try:
        state.companion["status"] = _status_snapshot
    except TypeError:
        # state.companion may be a namespace object rather than a dict.
        setattr(state.companion, "status", _status_snapshot)

    _log("[companion] routes registered (/browser/companion/*)")
