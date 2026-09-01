"""Human-in-the-loop approval gate (issue #13).

API-level approval queue: the agent (or a wrapped endpoint) requests approval
for a proposed action; a human lists pending items and approves/rejects them.
Works headless and over a tunnel (unlike the win32 HUD overlay), so it is the
enforcement layer for irreversible actions.

Core queue logic is pure and unit-tested. ``require_approval`` can block a
programmatic caller until a decision or timeout.
"""
import json
import logging
import re
import threading
import time
import urllib.request
import uuid

from flask import Blueprint, jsonify

from shared import _json_body, _log

_LOGGER = logging.getLogger(__name__)
approvals_bp = Blueprint("approvals", __name__)


class ApprovalQueue:
    """Thread-safe pending-approval store with TTL expiry."""

    # Retain decided/expired items this long so callers can still fetch the
    # result; beyond this they are pruned to bound memory.
    DECIDED_RETENTION_SECONDS = 3600.0

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
            elif item["status"] != "pending" and item.get("decided_at") is not None:
                if now - item["decided_at"] > self.DECIDED_RETENTION_SECONDS:
                    del self._items[aid]

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
            "delivered": False,
            "delivered_channels": [],
            "delivered_at": None,
        }
        with self._lock:
            self._expire_locked(now)
            self._items[aid] = item
        return dict(item)

    def mark_delivered(self, aid, channels, now=None):
        now = time.time() if now is None else now
        with self._lock:
            item = self._items.get(aid)
            if item:
                item["delivered"] = True
                item["delivered_channels"] = list(channels or [])
                item["delivered_at"] = now
            return dict(item) if item else None

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


# ---------------------------------------------------------------- delivery & replies
# Async push path (issue #1084): when a gate is hit, notify the operator over the
# channels CoAgent already ships (Telegram, Windows toast) instead of requiring
# them to poll the dashboard. Replies ("approve <id>" / "reject <id>") are read
# back via a lightweight Telegram getUpdates poller and mapped onto the existing
# approve/reject decision handlers.
_DELIVERY = {"enabled": True, "telegram": True, "toast": True}
_DELIVERY_LOCK = threading.Lock()

_TG_POLL_THREAD = None
_TG_POLL_LOCK = threading.Lock()
_TG_LAST_UPDATE_ID = 0
_TG_POLL_INTERVAL = 3.0


def _coerce_bool(value):
    """Coerce a JSON value to bool without the str-truthiness trap
    (``bool("false")`` is True). Accepts real booleans, 0/1 numerics, and
    the strings true/false/1/0/yes/no/on/off (case-insensitive)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _delivery_config():
    with _DELIVERY_LOCK:
        return dict(_DELIVERY)


def _set_delivery_config(data):
    with _DELIVERY_LOCK:
        for key in ("enabled", "telegram", "toast"):
            if key in data:
                _DELIVERY[key] = _coerce_bool(data[key])


def _format_approval_summary(item):
    action = str(item.get("action") or "")
    aid = str(item.get("id") or "")
    detail = item.get("detail")
    detail_str = ""
    if isinstance(detail, str) and detail.strip():
        detail_str = detail.strip()[:200]
    elif isinstance(detail, dict):
        try:
            detail_str = json.dumps(detail)[:200]
        except Exception:
            detail_str = str(detail)[:200]
    summary = f"Action: {action}\nID: {aid[:8]}"
    if detail_str:
        summary += f"\nDetail: {detail_str}"
    return summary


def _deliver_approval(item):
    """Push a pending approval to configured channels. Returns updated item."""
    if not _delivery_config().get("enabled", True):
        return item
    channels = []
    summary = _format_approval_summary(item)
    aid = str(item.get("id") or "")
    cfg = _delivery_config()

    if cfg.get("telegram", True):
        try:
            import routes_telegram
            config = routes_telegram._load_config()
            if config and config.get("bot_token") and config.get("chat_id"):
                chat_id = routes_telegram._resolve_target_chat(config)
                ok, _ = routes_telegram._send_telegram(
                    config["bot_token"],
                    chat_id,
                    f"CoAgent approval required\n\n{summary}\n\n"
                    f"Reply: approve {aid[:8]} / reject {aid[:8]}",
                    parse_mode="",
                )
                if ok:
                    channels.append("telegram")
        except Exception as exc:
            _log(f"[approvals] telegram delivery failed: {type(exc).__name__}: {exc}")

    if cfg.get("toast", True):
        try:
            import routes_toast
            toast_fn = getattr(routes_toast, "_win11_toast", None)
            if toast_fn is not None and getattr(routes_toast, "HAS_WIN11TOAST", False):
                toast_fn("CoAgent approval required", summary)
                channels.append("toast")
        except Exception as exc:
            _log(f"[approvals] toast delivery failed: {type(exc).__name__}: {exc}")

    return _QUEUE.mark_delivered(item.get("id"), channels) or item


def _telegram_get_updates(token, offset, timeout=25):
    url = "https://api.telegram.org/bot{token}/getUpdates".format(token=token)
    payload = json.dumps({"offset": offset, "timeout": timeout,
                          "allowed_updates": ["message"]}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def _handle_telegram_command(token, chat_id, text):
    stripped = text.strip()
    match = re.match(r"^(approve|reject)\s+([A-Za-z0-9_-]{1,40})$",
                     stripped, re.IGNORECASE)
    if not match:
        # Refuse bare "approve"/"reject" (no id) — implicitly deciding the first
        # pending approval is dangerous, especially in a group chat.
        if re.match(r"^(approve|reject)$", stripped, re.IGNORECASE):
            _ack_telegram(token, chat_id,
                          f"Specify an approval id: {stripped} <id>.")
        return
    decision = match.group(1).lower()
    explicit_id = match.group(2)
    item = _QUEUE.get(explicit_id) or _find_pending_by_prefix(explicit_id)
    if not item:
        _ack_telegram(token, chat_id, f"Approval '{explicit_id}' not found.")
        return
    aid = item["id"]
    result = _QUEUE.decide(aid, decision == "approve", by=f"telegram:{chat_id}")
    if result:
        _ack_telegram(token, chat_id,
                      f"Approval {aid[:8]} -> {result.get('status')}.")
    else:
        _ack_telegram(token, chat_id, f"Approval '{aid[:8]}' not found.")


def _find_pending_by_prefix(prefix):
    prefix = str(prefix or "").lower()
    if not prefix:
        return None
    for item in _QUEUE.pending():
        if str(item.get("id") or "").startswith(prefix):
            return item
    return None


def _ack_telegram(token, chat_id, text):
    try:
        import routes_telegram
        routes_telegram._send_telegram(token, chat_id, text, parse_mode="")
    except Exception as exc:
        _log(f"[approvals] telegram ack failed: {type(exc).__name__}: {exc}")


def _telegram_poller_loop():
    global _TG_LAST_UPDATE_ID
    first = True
    while True:
        try:
            cfg = _delivery_config()
            if not cfg.get("enabled", True) or not cfg.get("telegram", True):
                time.sleep(_TG_POLL_INTERVAL * 5)
                first = True
                continue
            import routes_telegram
            config = routes_telegram._load_config()
            if not config or not config.get("bot_token") or not config.get("chat_id"):
                time.sleep(_TG_POLL_INTERVAL * 5)
                first = True
                continue
            token = config["bot_token"]
            chat_id = str(routes_telegram._resolve_target_chat(config))
            if first:
                # Seed from the latest update so we don't replay history on startup.
                result = _telegram_get_updates(token, offset=-1, timeout=0)
                updates = result.get("result") or []
                if updates:
                    _TG_LAST_UPDATE_ID = max(int(u.get("update_id", 0)) for u in updates)
                first = False
                continue
            result = _telegram_get_updates(token, offset=_TG_LAST_UPDATE_ID + 1,
                                           timeout=25)
            for update in result.get("result") or []:
                _TG_LAST_UPDATE_ID = max(_TG_LAST_UPDATE_ID,
                                         int(update.get("update_id", 0)))
                message = update.get("message") or {}
                if str((message.get("chat") or {}).get("id")) != chat_id:
                    continue
                text = (message.get("text") or "").strip()
                if text:
                    _handle_telegram_command(token, chat_id, text)
        except Exception as exc:
            _log(f"[approvals] telegram poller: {type(exc).__name__}: {exc}")
            time.sleep(_TG_POLL_INTERVAL * 2)
        time.sleep(_TG_POLL_INTERVAL)


def _start_telegram_poller():
    global _TG_POLL_THREAD
    with _TG_POLL_LOCK:
        if _TG_POLL_THREAD and _TG_POLL_THREAD.is_alive():
            return
        _TG_POLL_THREAD = threading.Thread(target=_telegram_poller_loop,
                                           name="approvals-telegram-poller",
                                           daemon=True)
        _TG_POLL_THREAD.start()


def register_routes(app, state, require_auth):
    @app.route("/approvals/config", methods=["GET", "POST"])
    @require_auth
    def route_approvals_config():
        body = _json_body() or {}
        if isinstance(body, dict) and "enabled" in body:
            _QUEUE.enabled = _coerce_bool(body["enabled"])
        if isinstance(body, dict) and "default_ttl" in body:
            try:
                _QUEUE.default_ttl = max(1.0, float(body["default_ttl"]))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "default_ttl must be numeric"}), 400
        if isinstance(body, dict) and any(k in body for k in ("delivery_enabled", "delivery_telegram", "delivery_toast")):
            delivery_updates = {}
            if "delivery_enabled" in body:
                delivery_updates["enabled"] = body["delivery_enabled"]
            if "delivery_telegram" in body:
                delivery_updates["telegram"] = body["delivery_telegram"]
            if "delivery_toast" in body:
                delivery_updates["toast"] = body["delivery_toast"]
            _set_delivery_config(delivery_updates)
        return jsonify({"ok": True, "enabled": _QUEUE.enabled,
                        "default_ttl": _QUEUE.default_ttl,
                        "delivery": _delivery_config()})

    @app.route("/approvals/request", methods=["POST"])
    @require_auth
    def route_approvals_request():
        body = _json_body() or {}
        action = (body.get("action") or "").strip()
        if not action:
            return jsonify({"ok": False, "error": "Missing required field: action"}), 400
        item = _QUEUE.request(action, body.get("detail"), body.get("meta"),
                              ttl=body.get("ttl"))
        # Push the gate to Telegram/toast in the background so an unattended
        # agent doesn't stall silently waiting for a decision.
        threading.Thread(target=_deliver_approval, args=(item,),
                         name=f"approval-deliver-{item['id'][:8]}",
                         daemon=True).start()
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

    _start_telegram_poller()
    _LOGGER.info("Approval gate routes registered")
