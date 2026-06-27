"""Webhook registration and async dispatch routes."""

import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy

from flask import Blueprint, jsonify

from shared import _is_private_url, _json_body, _log


webhooks_bp = Blueprint("webhooks", __name__)

_WEBHOOKS = {}
_WEBHOOK_LOCK = threading.Lock()
_ALLOWED_EVENTS = {
    "screenshot_taken",
    "screenshot_saved",
    "error",
    "agent_completed",
    "user_login",
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _public_webhook(webhook_id, record):
    return {
        "id": webhook_id,
        "url": record.get("url"),
        "events": list(record.get("events") or []),
        "created_at": record.get("created_at"),
        "last_triggered": record.get("last_triggered"),
        "last_response": record.get("last_response"),
    }


def _valid_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_events(events):
    if not isinstance(events, list):
        return []
    normalized = []
    for event in events:
        if isinstance(event, str):
            clean = event.strip()
            if clean and clean not in normalized:
                normalized.append(clean)
    return normalized


def _dispatch_one(webhook_id, record, event_type, data, timestamp):
    body = json.dumps(
        {
            "event": event_type,
            "data": data,
            "timestamp": timestamp,
            "webhook_id": webhook_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    secret = str(record.get("secret") or "")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Hermes-CoAgent-Webhook/1.0",
        "X-Webhook-Signature": signature,
    }
    response_info = {"ok": False, "status": None, "body": "", "error": None}
    try:
        if _is_private_url(record["url"]):
            raise ValueError("webhook URL resolves to a blocked private or internal address")
        request = urllib.request.Request(
            record["url"],
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read(4096).decode("utf-8", errors="replace")
            response_info.update(
                {
                    "ok": 200 <= response.status < 300,
                    "status": int(response.status),
                    "body": response_body,
                }
            )
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        response_info.update(
            {
                "status": int(getattr(exc, "code", 0) or 0),
                "body": error_body,
                "error": f"HTTPError: {exc}",
            }
        )
    except Exception as exc:
        response_info["error"] = f"{type(exc).__name__}: {exc}"

    with _WEBHOOK_LOCK:
        current = _WEBHOOKS.get(webhook_id)
        if current:
            current["last_triggered"] = timestamp
            current["last_response"] = response_info


def fire_webhook(event_type, data):
    """Dispatch event_type to matching webhooks in the background."""
    timestamp = _now()
    payload = data if isinstance(data, dict) else {"value": data}
    with _WEBHOOK_LOCK:
        targets = [
            (webhook_id, deepcopy(record))
            for webhook_id, record in _WEBHOOKS.items()
            if event_type in set(record.get("events") or [])
        ]

    if not targets:
        return 0

    def _worker():
        for webhook_id, record in targets:
            try:
                _dispatch_one(webhook_id, record, event_type, payload, timestamp)
            except Exception as exc:
                _log(f"[webhooks] dispatch failed for {webhook_id}: {exc}")

    thread = threading.Thread(target=_worker, name=f"webhook-{event_type}", daemon=True)
    thread.start()
    return len(targets)


@webhooks_bp.route("/webhooks/list", methods=["GET"])
def route_webhooks_list():
    with _WEBHOOK_LOCK:
        webhooks = [
            _public_webhook(webhook_id, record)
            for webhook_id, record in sorted(_WEBHOOKS.items())
        ]
    return jsonify({"webhooks": webhooks, "count": len(webhooks)})


@webhooks_bp.route("/webhooks/register", methods=["POST"])
def route_webhooks_register():
    data = _json_body()
    url = str(data.get("url") or "").strip()
    events = _normalize_events(data.get("events"))
    if not url:
        return jsonify({"error": "url is required"}), 400
    if not _valid_url(url):
        return jsonify({"error": "url must be an http or https URL"}), 400
    if _is_private_url(url):
        return jsonify({"error": "url resolves to a blocked private or internal address"}), 400
    if not events:
        return jsonify({"error": "events must contain at least one event name"}), 400

    unknown_events = [event for event in events if event not in _ALLOWED_EVENTS]
    if unknown_events:
        return jsonify(
            {
                "error": "unsupported event",
                "unsupported": unknown_events,
                "allowed": sorted(_ALLOWED_EVENTS),
            }
        ), 400

    webhook_id = secrets.token_urlsafe(12)
    record = {
        "url": url,
        "events": events,
        "secret": secrets.token_urlsafe(32),
        "created_at": _now(),
        "last_triggered": None,
        "last_response": None,
    }
    with _WEBHOOK_LOCK:
        _WEBHOOKS[webhook_id] = record
    return jsonify(_public_webhook(webhook_id, record)), 201


@webhooks_bp.route("/webhooks/<webhook_id>", methods=["DELETE"])
def route_webhooks_delete(webhook_id):
    with _WEBHOOK_LOCK:
        removed = _WEBHOOKS.pop(webhook_id, None)
    if not removed:
        return jsonify({"error": "webhook not found", "id": webhook_id}), 404
    return jsonify({"status": "deleted", "id": webhook_id})


@webhooks_bp.route("/webhooks/test/<webhook_id>", methods=["POST"])
def route_webhooks_test(webhook_id):
    with _WEBHOOK_LOCK:
        record = deepcopy(_WEBHOOKS.get(webhook_id))
    if not record:
        return jsonify({"error": "webhook not found", "id": webhook_id}), 404

    timestamp = _now()

    def _worker():
        _dispatch_one(webhook_id, record, "test", {"ok": True}, timestamp)

    threading.Thread(target=_worker, name=f"webhook-test-{webhook_id}", daemon=True).start()
    return jsonify({"status": "queued", "id": webhook_id, "event": "test"})


def register_routes(app, state, require_auth):
    for endpoint, view_func in list(webhooks_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        webhooks_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(webhooks_bp)
