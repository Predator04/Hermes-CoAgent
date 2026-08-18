"""Windows notification listener routes.

Endpoints:
  GET/POST /notify/list        - list recently observed toast/app notifications
  POST     /notify/subscribe   - register a webhook URL, POSTed on each new notif
  POST     /notify/unsubscribe - remove a previously registered webhook URL

Uses the Windows Runtime UserNotificationListener (winsdk/WinRT) when available
to enumerate notifications currently in Action Center. On first use it requests
user consent - if consent is denied or the WinRT bindings are missing, the
endpoints fall back to a periodic polling model that still tracks whatever the
listener can return, or degrade to HTTP 501 on non-Windows hosts.

Windows-only imports are wrapped in try/except so the Linux syntax-check CI
stays green. All URL / subprocess strings are pure ASCII.
"""

import json as _json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid

from flask import jsonify

from shared import _json_body, _log, _missing_field


# ---------------------------------------------------------------------------
# Optional Windows-only imports (winsdk exposes the WinRT projections).
# ---------------------------------------------------------------------------
try:
    from winsdk.windows.ui.notifications.management import (  # type: ignore
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )
    from winsdk.windows.ui.notifications import (  # type: ignore
        NotificationKinds,
        KnownNotificationBindings,
    )
    _WINSDK_IMPORT_ERROR = None
except Exception as _exc:  # ImportError on Linux, RuntimeError on old Windows
    UserNotificationListener = None
    NotificationKinds = None
    UserNotificationListenerAccessStatus = None
    KnownNotificationBindings = None
    _WINSDK_IMPORT_ERROR = str(_exc)


# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
_MAX_HISTORY = 200
_POLL_INTERVAL = 3.0
_WEBHOOK_TIMEOUT = 5.0

_STATE_LOCK = threading.Lock()
_HISTORY = []                 # list[dict]  most recent last
_SEEN_IDS = set()             # notification ids already emitted
_SUBSCRIBERS = {}             # sub_id -> {"url": str, "created": float}
_ACCESS_STATUS = None         # cached access-request result string
_POLLER_STARTED = False
_POLLER_LOCK = threading.Lock()


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (UserNotificationListener unavailable)"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _winrt_available():
    return os.name == "nt" and UserNotificationListener is not None


def _await(async_op, timeout=5.0):
    """Block on a WinRT IAsyncOperation and return its result."""
    done = threading.Event()
    result = {"value": None, "error": None}

    def _cb(op, _status):
        try:
            result["value"] = op.get_results()
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            done.set()

    async_op.completed = _cb
    if not done.wait(timeout):
        raise TimeoutError("WinRT async operation timed out")
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


def _request_access():
    """Request UserNotificationListener access. Returns access-status string."""
    global _ACCESS_STATUS
    if _ACCESS_STATUS is not None:
        return _ACCESS_STATUS
    if not _winrt_available():
        _ACCESS_STATUS = "unavailable"
        return _ACCESS_STATUS
    try:
        listener = UserNotificationListener.current
        status = _await(listener.request_access_async(), timeout=10.0)
        # WinRT enum -> name
        name = getattr(status, "name", None) or str(status)
        _ACCESS_STATUS = name.lower()
    except Exception as exc:  # noqa: BLE001
        _log(f"notify: request_access failed: {exc}")
        _ACCESS_STATUS = f"error: {exc}"
    return _ACCESS_STATUS


def _has_access():
    status = _request_access()
    return status in ("allowed",)


def _read_text_from_binding(binding):
    """Extract title + body text from a NotificationBinding."""
    title = ""
    body_parts = []
    try:
        elements = binding.get_text_elements()
    except Exception:
        return title, ""
    lines = []
    for element in elements:
        try:
            lines.append(element.text or "")
        except Exception:
            continue
    if lines:
        title = lines[0]
        body_parts = lines[1:]
    return title, "\n".join(p for p in body_parts if p)


def _normalize_notification(user_notification):
    """Convert a WinRT UserNotification into a JSON-safe dict."""
    entry = {
        "id": None,
        "app_id": "",
        "app_name": "",
        "title": "",
        "body": "",
        "creation_time": None,
    }
    try:
        entry["id"] = int(user_notification.id)
    except Exception:
        pass
    try:
        app_info = user_notification.app_info
        entry["app_id"] = app_info.app_user_model_id or ""
        try:
            entry["app_name"] = app_info.display_info.display_name or ""
        except Exception:
            entry["app_name"] = ""
    except Exception:
        pass
    try:
        # Timestamp is a Windows DateTime -> convert to unix seconds via UTC.
        dt = user_notification.creation_time
        # winsdk exposes .utc_date_time on datetime.datetime already, but be defensive.
        if hasattr(dt, "timestamp"):
            entry["creation_time"] = dt.timestamp()
        else:
            entry["creation_time"] = time.time()
    except Exception:
        entry["creation_time"] = time.time()
    try:
        toast = user_notification.notification
        visual = toast.visual
        binding = visual.get_binding(KnownNotificationBindings.get_toast_generic())
        if binding is not None:
            title, body = _read_text_from_binding(binding)
            entry["title"] = title
            entry["body"] = body
    except Exception:
        pass
    return entry


def _fetch_current_notifications():
    """Return a list of normalized dicts; raises on WinRT failure."""
    listener = UserNotificationListener.current
    kinds = NotificationKinds.toast
    raw = _await(listener.get_notifications_async(kinds), timeout=10.0)
    out = []
    if raw is None:
        return out
    for item in raw:
        try:
            out.append(_normalize_notification(item))
        except Exception as exc:  # noqa: BLE001
            _log(f"notify: normalize failed: {exc}")
    return out


def _record_and_dispatch(entries):
    """Insert new entries into history and fire webhooks. Returns new-entry list."""
    new_entries = []
    with _STATE_LOCK:
        for entry in entries:
            nid = entry.get("id")
            if nid is None or nid in _SEEN_IDS:
                continue
            _SEEN_IDS.add(nid)
            _HISTORY.append(entry)
            new_entries.append(entry)
        # Bound history size
        overflow = len(_HISTORY) - _MAX_HISTORY
        if overflow > 0:
            del _HISTORY[:overflow]
        subscribers = list(_SUBSCRIBERS.values())
    if new_entries and subscribers:
        _dispatch_webhooks(subscribers, new_entries)
    return new_entries


def _dispatch_webhooks(subscribers, entries):
    """POST each new entry to every subscriber URL in a background thread."""
    def _worker():
        payload = _json.dumps({"notifications": entries}).encode("utf-8")
        for sub in subscribers:
            url = sub.get("url")
            if not url:
                continue
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT):
                    pass
            except (urllib.error.URLError, OSError, ValueError) as exc:
                _log(f"notify: webhook {url} failed: {exc}")
    threading.Thread(target=_worker, name="notify-webhook", daemon=True).start()


def _poll_loop():
    while True:
        try:
            if _has_access():
                entries = _fetch_current_notifications()
                _record_and_dispatch(entries)
        except Exception as exc:  # noqa: BLE001
            _log(f"notify: poll error: {exc}")
        time.sleep(_POLL_INTERVAL)


def _ensure_poller():
    global _POLLER_STARTED
    if _POLLER_STARTED or not _winrt_available():
        return
    with _POLLER_LOCK:
        if _POLLER_STARTED:
            return
        threading.Thread(target=_poll_loop, name="notify-poller", daemon=True).start()
        _POLLER_STARTED = True


def _valid_webhook_url(url):
    if not isinstance(url, str) or not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def register_routes(app, state, require_auth):

    @app.route("/notify/list", methods=["GET", "POST"])
    @require_auth
    def route_notify_list():
        if not _winrt_available():
            return _windows_only(_WINSDK_IMPORT_ERROR)

        body = _json_body()
        refresh = True
        if isinstance(body, dict):
            refresh = bool(body.get("refresh", True))

        access = _request_access()
        if not _has_access():
            return jsonify({
                "error": "notification listener access not granted",
                "access_status": access,
                "hint": "Enable in Windows Settings > Privacy > Notifications",
            }), 403

        _ensure_poller()

        error = None
        if refresh:
            try:
                entries = _fetch_current_notifications()
                _record_and_dispatch(entries)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

        with _STATE_LOCK:
            history = list(_HISTORY)

        payload = {
            "count": len(history),
            "access_status": access,
            "notifications": history,
        }
        if error:
            payload["refresh_error"] = error
        return jsonify(payload)

    @app.route("/notify/subscribe", methods=["POST"])
    @require_auth
    def route_notify_subscribe():
        if not _winrt_available():
            return _windows_only(_WINSDK_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        url = body.get("url") or body.get("webhook")
        if not url:
            return _missing_field("url")
        if not _valid_webhook_url(url):
            return jsonify({"error": "url must be http:// or https://"}), 400

        access = _request_access()
        if not _has_access():
            return jsonify({
                "error": "notification listener access not granted",
                "access_status": access,
            }), 403

        sub_id = uuid.uuid4().hex
        with _STATE_LOCK:
            _SUBSCRIBERS[sub_id] = {"url": url, "created": time.time()}
            total = len(_SUBSCRIBERS)

        _ensure_poller()
        _log(f"notify/subscribe id={sub_id} url={url}")
        return jsonify({
            "status": "ok",
            "subscription_id": sub_id,
            "url": url,
            "subscriber_count": total,
            "poll_interval_seconds": _POLL_INTERVAL,
        })

    @app.route("/notify/unsubscribe", methods=["POST"])
    @require_auth
    def route_notify_unsubscribe():
        if not _winrt_available():
            return _windows_only(_WINSDK_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}
        sub_id = body.get("subscription_id") or body.get("id")
        if not sub_id:
            return _missing_field("subscription_id")

        with _STATE_LOCK:
            removed = _SUBSCRIBERS.pop(sub_id, None)
            total = len(_SUBSCRIBERS)

        if removed is None:
            return jsonify({"error": "unknown subscription_id"}), 404

        _log(f"notify/unsubscribe id={sub_id}")
        return jsonify({
            "status": "ok",
            "subscription_id": sub_id,
            "subscriber_count": total,
        })
