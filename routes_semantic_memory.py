"""Semantic Memory & Vector State Tracking.

Local persistent memory that observes user patterns (apps, times, sequences)
and provides proactive suggestions based on discovered routines.
Stored in COAGENT_DIR/semantic_memory.json.
"""
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
memory_bp = Blueprint("semantic_memory", __name__)

_MEMORY_LOCK = threading.Lock()
_COAGENT_DIR = None
_MEMORY_FILE = None
_MEMORY_CACHE = {
    "events": [],
    "patterns": [],
}
_MAX_EVENTS = 10000


def _debug_failure(context, exc):
    _LOGGER.debug("semantic_memory %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _set_coagent_dir(path):
    global _COAGENT_DIR, _MEMORY_FILE
    _COAGENT_DIR = Path(path) if path else None
    if _COAGENT_DIR:
        _MEMORY_FILE = _COAGENT_DIR / "semantic_memory.json"
        _load()


def _load():
    global _MEMORY_CACHE
    if _MEMORY_FILE and _MEMORY_FILE.exists():
        try:
            data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _MEMORY_CACHE["events"] = data.get("events", [])[-_MAX_EVENTS:]
                _MEMORY_CACHE["patterns"] = data.get("patterns", [])
        except Exception as exc:
            _debug_failure("load", exc)


def _save():
    if _MEMORY_FILE:
        try:
            _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _MEMORY_FILE.write_text(
                json.dumps(_MEMORY_CACHE, indent=2, default=str),
                encoding="utf-8"
            )
        except Exception as exc:
            _debug_failure("save", exc)


def _detect_patterns():
    """Scan events for recurring time-based patterns."""
    events = _MEMORY_CACHE.get("events", [])
    if len(events) < 3:
        return

    # Group by app + hour
    app_hour_counts = defaultdict(lambda: {"count": 0, "days": set(), "last_seen": None})
    for ev in events:
        app = ev.get("app", "")
        ts = ev.get("timestamp", "")
        if not app or not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.fromtimestamp(ts)
            hour = dt.hour
            day = dt.weekday()
            key = (app, hour)
            app_hour_counts[key]["count"] += 1
            app_hour_counts[key]["days"].add(day)
            app_hour_counts[key]["last_seen"] = ts
        except (ValueError, TypeError):
            continue

    new_patterns = []
    for (app, hour), info in app_hour_counts.items():
        if info["count"] >= 3 and len(info["days"]) >= 2:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            days_str = ", ".join(day_names[d] for d in sorted(info["days"]))
            pattern = {
                "name": f"Open {app} at {hour}:00",
                "trigger": {"app": app, "hour": hour},
                "frequency": info["count"],
                "days": days_str,
                "last_triggered": info["last_seen"],
                "confidence": min(1.0, info["count"] / 10),
            }
            new_patterns.append(pattern)

    _MEMORY_CACHE["patterns"] = sorted(new_patterns, key=lambda p: -p["frequency"])[:20]


@memory_bp.route("/memory/observe", methods=["POST"])
def _memory_observe():
    body = request.get_json(force=True, silent=True) or {}
    event = {
        "timestamp": datetime.now().isoformat(),
        "type": body.get("type", "app_open"),
        "app": body.get("app", ""),
        "title": body.get("title", ""),
        "window_class": body.get("window_class", ""),
        "duration_secs": body.get("duration_secs", 0),
    }
    with _MEMORY_LOCK:
        _MEMORY_CACHE["events"].append(event)
        if len(_MEMORY_CACHE["events"]) > _MAX_EVENTS:
            _MEMORY_CACHE["events"] = _MEMORY_CACHE["events"][-_MAX_EVENTS:]
        _detect_patterns()
        _save()
    return jsonify({"ok": True, "event_count": len(_MEMORY_CACHE["events"])})


@memory_bp.route("/memory/query", methods=["POST"])
def _memory_query():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip().lower()
    with _MEMORY_LOCK:
        events = _MEMORY_CACHE.get("events", [])
        if query:
            matches = [
                ev for ev in events
                if query in ev.get("app", "").lower()
                or query in ev.get("title", "").lower()
                or query in ev.get("type", "").lower()
            ]
        else:
            matches = events[-20:]
    return jsonify({"ok": True, "query": query, "matches": matches[-50:], "total": len(events)})


@memory_bp.route("/memory/patterns", methods=["GET"])
def _memory_patterns():
    with _MEMORY_LOCK:
        return jsonify({"ok": True, "patterns": _MEMORY_CACHE.get("patterns", []),
                        "total_events": len(_MEMORY_CACHE.get("events", []))})


@memory_bp.route("/memory/recent", methods=["GET"])
def _memory_recent():
    with _MEMORY_LOCK:
        return jsonify({"ok": True, "events": _MEMORY_CACHE.get("events", [])[-50:]})


@memory_bp.route("/memory/clear", methods=["DELETE"])
def _memory_clear():
    with _MEMORY_LOCK:
        _MEMORY_CACHE["events"] = []
        _MEMORY_CACHE["patterns"] = []
        _save()
    return jsonify({"ok": True, "cleared": True})


def register_routes(app, state, require_auth):
    try:
        from shared import COAGENT_DIR
        _set_coagent_dir(str(COAGENT_DIR))
    except (ImportError, AttributeError):
        pass
    app.register_blueprint(memory_bp)
    if require_auth:
        from shared import _wrap_registered_blueprint_routes
        _wrap_registered_blueprint_routes(app, memory_bp.name, require_auth)
    _LOGGER.info("Semantic memory routes registered")
