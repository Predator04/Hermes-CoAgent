"""Human-in-the-loop approval gate (issue #13).

API-level approval queue: the agent (or a wrapped endpoint) requests approval
for a proposed action; a human lists pending items and approves/rejects them.
Works headless and over a tunnel (unlike the win32 HUD overlay), so it is the
enforcement layer for irreversible actions.

Core queue logic is pure and unit-tested. ``require_approval`` can block a
programmatic caller until a decision or timeout.
"""
import logging
import threading
import time
import uuid

from flask import Blueprint, jsonify

from shared import _json_body

_LOGGER = logging.getLogger(__name__)
approvals_bp = Blueprint("approvals", __name__)


class ApprovalQueue:
    """Thread-safe pending-approval store with TTL expiry."""

    def __init__(self, default_ttl=300.0):
        self._items = {}
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self.default_ttl = default_ttl
        self.enabled = True

    def _expire_locked(self, now):
        for aid, item in list(self._items.items()):
            if item["status"] == "pending" and now >= item["expires_at"]:
                item["status"] = "expired"
                item["decided_at"] = now

    def request(self, action, detail=None, meta=None, ttl=None, now=None):
        now = time.time() if now is None else now
        ttl = self.default_ttl if ttl is None else float(ttl)
        aid = uuid.uuid4().hex
        item = {
            "id": aid,
            "action": str(action),
            "detail": detail,
            "meta": meta or {},
            "status": "pending",
            "created_at": now,
            "expires_at": now + ttl,
            "decided_at": None,
            "decided_by": None,
        }
        with self._lock:
            self._expire_locked(now)
            self._items[aid] = item
        return dict(item)

    def decide(self, aid, approve, by=None, now=None):
        now = time.time() if now is None else now
        with self._cv:
            self._expire_locked(now)
            item = self._items.get(aid)
            if not item:
                return None
            if item["status"] == "pending":
                item["status"] = "approved" if approve else "rejected"
                item["decided_at"] = now
                item["decided_by"] = by
                self._cv.notify_all()
            return dict(item)

    def get(self, aid, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._expire_locked(now)
            item = self._items.get(aid)
            return dict(item) if item else None

    def pending(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._expire_locked(now)
            return [dict(i) for i in self._items.values() if i["status"] == "pending"]

    def wait(self, aid, timeout):
        """Block until the item leaves 'pending' or timeout. Returns final dict."""
        deadline = time.time() + timeout
        with self._cv:
            while True:
                self._expire_locked(time.time())
                item = self._items.get(aid)
                if not item or item["status"] != "pending":
                    return dict(item) if item else None
                remaining = deadline - time.time()
                if remaining <= 0:
                    return dict(item)
                self._cv.wait(timeout=min(remaining, 0.5))


_QUEUE = ApprovalQueue()


def require_approval(action, detail=None, meta=None, timeout=120.0):
    """Gate a programmatic action. Returns (allowed: bool, item: dict).

    When the gate is disabled, auto-allows. Otherwise creates a pending item and
    blocks up to ``timeout`` for a human decision (fail-closed on timeout).
    """
    if not _QUEUE.enabled:
        return True, {"status": "auto_allowed", "action": action}
    item = _QUEUE.request(action, detail, meta)
    final = _QUEUE.wait(item["id"], timeout)
    return (bool(final) and final["status"] == "approved"), (final or item)


def register_routes(app, state, require_auth):
    @app.route("/approvals/config", methods=["GET", "POST"])
    @require_auth
    def route_approvals_config():
        body = _json_body() if _json_body() else {}
        if isinstance(body, dict) and "enabled" in body:
            _QUEUE.enabled = bool(body["enabled"])
        if isinstance(body, dict) and "default_ttl" in body:
            try:
                _QUEUE.default_ttl = max(1.0, float(body["default_ttl"]))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "default_ttl must be numeric"}), 400
        return jsonify({"ok": True, "enabled": _QUEUE.enabled,
                        "default_ttl": _QUEUE.default_ttl})

    @app.route("/approvals/request", methods=["POST"])
    @require_auth
    def route_approvals_request():
        body = _json_body()
        action = (body.get("action") or "").strip()
        if not action:
            return jsonify({"ok": False, "error": "Missing required field: action"}), 400
        item = _QUEUE.request(action, body.get("detail"), body.get("meta"),
                              ttl=body.get("ttl"))
        return jsonify({"ok": True, "approval": item}), 201

    @app.route("/approvals/pending", methods=["GET"])
    @require_auth
    def route_approvals_pending():
        items = _QUEUE.pending()
        return jsonify({"ok": True, "count": len(items), "pending": items})

    @app.route("/approvals/<aid>", methods=["GET"])
    @require_auth
    def route_approvals_get(aid):
        item = _QUEUE.get(aid)
        if not item:
            return jsonify({"ok": False, "error": "approval not found"}), 404
        return jsonify({"ok": True, "approval": item})

    @app.route("/approvals/<aid>/approve", methods=["POST"])
    @require_auth
    def route_approvals_approve(aid):
        body = _json_body() or {}
        item = _QUEUE.decide(aid, True, by=body.get("by") if isinstance(body, dict) else None)
        if not item:
            return jsonify({"ok": False, "error": "approval not found"}), 404
        return jsonify({"ok": True, "approval": item})

    @app.route("/approvals/<aid>/reject", methods=["POST"])
    @require_auth
    def route_approvals_reject(aid):
        body = _json_body() or {}
        item = _QUEUE.decide(aid, False, by=body.get("by") if isinstance(body, dict) else None)
        if not item:
            return jsonify({"ok": False, "error": "approval not found"}), 404
        return jsonify({"ok": True, "approval": item})

    _LOGGER.info("Approval gate routes registered")
