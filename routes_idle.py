"""Idle/lock-aware automation gating for Hermes CoAgent.

Holds queued/background automation until the human is idle (or the session is
locked), then releases it — the "when" half of CoAgent's "work alongside the
user" mission. Reuses the GetLastInputInfo approach already wired in
``routes_agent_tools.py`` and adds session-lock detection via
``OpenInputDesktop``.

Endpoints (all ``@require_auth``):

* ``GET  /idle/status``                  — idle time, lock state, gate decision
* ``POST /idle/gate``                    — evaluate a gate decision (priority/threshold)
* ``POST /idle/config``                  — set threshold / enable / bypass priority
* ``GET  /idle/queue``                   — list deferred automation items
* ``POST /idle/queue``                   — submit an item (held until idle/lock/priority)
* ``POST /idle/queue/<item_id>/release`` — force-release an item
* ``POST /idle/queue/<item_id>/cancel``  — remove an item

Exposes ``state.idle_gate`` — a reusable helper other modules (recipes, triggers,
scheduled jobs) can call to defer their own automation:

    should_run(priority=0, threshold=None)          -> bool
    submit(name, fn, priority=0, threshold=None)    -> item_id  (fn() runs when released)
    status()                                        -> dict
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from shared import _log

try:
    import ctypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    _HAS_CTYPES = True
except Exception:  # noqa: BLE001
    _HAS_CTYPES = False

DEFAULT_THRESHOLD_SECONDS = 60
DEFAULT_BYPASS_PRIORITY = 100
MAX_QUEUE_ITEMS = 100
WATCH_INTERVAL = 1.0


def _parse_bool(value):
    """Coerce client-supplied booleans strictly; 'false'/'0'/'no' must be False."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


# ---------------------------------------------------------------------------
# System state probes
# ---------------------------------------------------------------------------

def get_idle_ms():
    """System idle time in milliseconds via GetLastInputInfo (Windows)."""
    if not _HAS_CTYPES:
        return None
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = kernel32.GetTickCount() & 0xFFFFFFFF
            return int((tick - lii.dwTime) & 0xFFFFFFFF)
    except Exception:  # noqa: BLE001
        pass
    return None


def is_session_locked():
    """True when the secure desktop (lock screen / UAC) is active."""
    if not _HAS_CTYPES:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        hdesk = user32.OpenInputDesktop(0, False, 0)
        locked = not bool(hdesk)
        if hdesk:
            user32.CloseDesktop(hdesk)
        return locked
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class IdleGate:
    """Deferred-automation gate: hold items until idle/locked or priority bypass."""

    def __init__(self, threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS):
        self._lock = threading.RLock()
        self._config = {
            "threshold_seconds": float(threshold_seconds),
            "enabled": True,
            "bypass_priority": DEFAULT_BYPASS_PRIORITY,
        }
        self._items: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- config ------------------------------------------------------------

    def configure(self, threshold_seconds=None, enabled=None, bypass_priority=None) -> Dict[str, Any]:
        with self._lock:
            if threshold_seconds is not None:
                self._config["threshold_seconds"] = max(0.0, float(threshold_seconds))
            if enabled is not None:
                self._config["enabled"] = _parse_bool(enabled)
            if bypass_priority is not None:
                self._config["bypass_priority"] = int(bypass_priority)
            return dict(self._config)

    def get_config(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._config)

    # -- decision ----------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        idle_ms = get_idle_ms()
        locked = is_session_locked()
        with self._lock:
            threshold = self._config["threshold_seconds"]
            enabled = self._config["enabled"]
        threshold_ms = threshold * 1000
        is_idle = bool(idle_ms is not None and idle_ms >= threshold_ms)
        allowed = (not enabled) or locked or is_idle
        reason = (
            "gate disabled" if not enabled
            else "session locked" if locked
            else "idle" if is_idle
            else "user active"
        )
        return {
            "idle_ms": idle_ms,
            "idle_seconds": round(idle_ms / 1000.0, 1) if idle_ms is not None else None,
            "threshold_seconds": threshold,
            "is_idle": is_idle,
            "is_locked": locked,
            "gate_enabled": enabled,
            "automation_allowed": allowed,
            "reason": reason,
        }

    def should_run(self, priority: int = 0, threshold: Optional[float] = None) -> bool:
        with self._lock:
            cfg = dict(self._config)
        if not cfg["enabled"]:
            return True
        if priority >= cfg["bypass_priority"]:
            return True
        if is_session_locked():
            return True
        idle_ms = get_idle_ms()
        threshold_ms = (cfg["threshold_seconds"] if threshold is None else threshold) * 1000
        return bool(idle_ms is not None and idle_ms >= threshold_ms)

    # -- queue -------------------------------------------------------------

    def submit(
        self,
        name: str,
        fn: Optional[Callable[[], Any]] = None,
        priority: int = 0,
        threshold: Optional[float] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        item_id = uuid.uuid4().hex[:12]
        item = {
            "id": item_id,
            "name": str(name),
            "fn": fn,
            "priority": int(priority),
            "threshold": threshold,
            "payload": payload or {},
            "status": "queued",
            "created_at": time.time(),
            "released_at": None,
            "result": None,
        }
        with self._lock:
            queued_count = sum(1 for it in self._items.values() if it.get("status") == "queued")
            if queued_count >= MAX_QUEUE_ITEMS:
                raise RuntimeError("idle gate queue is full")
            self._items[item_id] = item
            self._order.append(item_id)
        self._ensure_thread()
        return item_id

    def _release_locked(self, item_id: str, reason: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item["status"] != "queued":
                return None
            item["status"] = "released"
            item["released_at"] = time.time()
            item["release_reason"] = reason
            fn = item["fn"]
        if fn is not None:
            threading.Thread(target=self._safe_invoke, args=(item_id, fn), daemon=True).start()
        return item

    def _safe_invoke(self, item_id: str, fn: Callable[[], Any]) -> None:
        try:
            result = fn()
            with self._lock:
                item = self._items.get(item_id)
                if item is not None:
                    item["result"] = result
                    item["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            _log(f"idle gate: callback failed for {item_id}: {exc}")
            with self._lock:
                item = self._items.get(item_id)
                if item is not None:
                    item["result"] = {"error": str(exc)}
                    item["status"] = "error"

    def release(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._release_locked(item_id, "manual")

    def cancel(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item["status"] != "queued":
                return False
            item["status"] = "cancelled"
            return True

    def list_items(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [_public(item) for item in (self._items[i] for i in self._order)]

    # -- watcher -----------------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._watch_loop, name="idle-gate", daemon=True)
            self._thread.start()

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                queued = [i for i in self._order if self._items.get(i, {}).get("status") == "queued"]
            for item_id in queued:
                with self._lock:
                    item = self._items.get(item_id)
                    if item is None or item["status"] != "queued":
                        continue
                    priority = item["priority"]
                    threshold = item["threshold"]
                if self.should_run(priority=priority, threshold=threshold):
                    self._release_locked(item_id, self.status()["reason"])
            self._stop.wait(WATCH_INTERVAL)

    def shutdown(self) -> None:
        self._stop.set()


def _public(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in item.items() if k != "fn"}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):
    gate = IdleGate()

    @app.route("/idle/status", methods=["GET"])
    @require_auth
    def route_idle_status():
        return jsonify({"ok": True, **gate.status(), "config": gate.get_config(), "queued": len([i for i in gate.list_items() if i["status"] == "queued"])})

    @app.route("/idle/gate", methods=["POST"])
    @require_auth
    def route_idle_gate():
        data = request.get_json(silent=True) or {}
        try:
            priority = int(data.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0
        threshold = data.get("threshold_seconds")
        try:
            threshold = float(threshold) if threshold is not None else None
        except (TypeError, ValueError):
            threshold = None
        st = gate.status()
        allowed = gate.should_run(priority=priority, threshold=threshold)
        resp = {
            "ok": True,
            "allow": allowed,
            "priority": priority,
            **st,
        }
        if not allowed:
            threshold_ms = (threshold if threshold is not None else gate.get_config()["threshold_seconds"]) * 1000
            idle_ms = st.get("idle_ms") or 0
            resp["wait_hint_seconds"] = round(max(0, int(threshold_ms - idle_ms)) / 1000.0, 1)
        return jsonify(resp)

    @app.route("/idle/config", methods=["POST"])
    @require_auth
    def route_idle_config():
        data = request.get_json(silent=True) or {}
        try:
            cfg = gate.configure(
                threshold_seconds=data.get("threshold_seconds"),
                enabled=data.get("enabled"),
                bypass_priority=data.get("bypass_priority"),
            )
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "threshold_seconds and bypass_priority must be numeric"}), 400
        return jsonify({"ok": True, "config": cfg})

    @app.route("/idle/queue", methods=["GET"])
    @require_auth
    def route_idle_queue_list():
        items = gate.list_items()
        return jsonify({"ok": True, "count": len(items), "items": items})

    @app.route("/idle/queue", methods=["POST"])
    @require_auth
    def route_idle_queue_submit():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "unnamed")
        try:
            priority = int(data.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0
        threshold = data.get("threshold_seconds")
        try:
            threshold = float(threshold) if threshold is not None else None
        except (TypeError, ValueError):
            threshold = None
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        try:
            item_id = gate.submit(name, fn=None, priority=priority, threshold=threshold, payload=payload)
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 429
        item = gate.list_items()
        item = next((i for i in item if i["id"] == item_id), None)
        return jsonify({"ok": True, "item": item, "gate": gate.status()}), 202

    @app.route("/idle/queue/<item_id>/release", methods=["POST"])
    @require_auth
    def route_idle_queue_release(item_id):
        item = gate.release(item_id)
        if item is None:
            return jsonify({"ok": False, "error": "item not found or already released"}), 404
        return jsonify({"ok": True, "item": _public(item)})

    @app.route("/idle/queue/<item_id>/cancel", methods=["POST"])
    @require_auth
    def route_idle_queue_cancel(item_id):
        if not gate.cancel(item_id):
            return jsonify({"ok": False, "error": "item not found or already released"}), 404
        return jsonify({"ok": True, "cancelled": item_id})

    state.idle_gate = gate
