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
import uuid
from copy import deepcopy

from flask import Blueprint, jsonify, request

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
    # OS session-change events pushed by routes_session.py's WTS monitor.
    "session_lock",
    "session_unlock",
    "logon",
    "logoff",
    "console_connect",
    "console_disconnect",
    "remote_connect",
    "remote_disconnect",
    "session_test",
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
        # Build opener that does NOT follow redirects (SSRF prevention)
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirectHandler)
        request = urllib.request.Request(
            record["url"],
            data=body,
            headers=headers,
            method="POST",
        )
        with opener.open(request, timeout=15) as response:
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


# ---------------------------------------------------------------- inbound webhooks
# Receive-side webhooks: an external service (GitHub, Stripe, n8n, Zapier, IFTTT,
# monitoring) POSTs to /webhooks/incoming/<hook_id> to trigger a recipe or
# workflow. Each hook carries an optional HMAC secret; the receive endpoint is
# public (no Bearer auth) and authenticated via the X-Webhook-Signature header,
# mirroring the outbound signing in _dispatch_one.
_INBOUND_HOOKS = {}
_INBOUND_LOCK = threading.Lock()
_INBOUND_RECENT_LIMIT = 20


def _inbound_public(hook_id, record, include_secret=False):
    out = {
        "id": hook_id,
        "target_type": record.get("target_type"),
        "target_id": record.get("target_id"),
        "url_path": f"/webhooks/incoming/{hook_id}",
        "created_at": record.get("created_at"),
        "last_received": record.get("last_received"),
        "last_run": record.get("last_run"),
        "secret_set": bool(record.get("secret")),
    }
    if include_secret:
        out["secret"] = record.get("secret")
    return out


def _verify_inbound_signature(raw_body, secret, signature_header):
    """Constant-time HMAC check. A hook without a secret accepts any payload."""
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _resolve_inbound_steps(hook):
    """Resolve the mapped recipe/workflow to a list of steps (or an error)."""
    target_type = hook.get("target_type")
    target_id = str(hook.get("target_id") or "")
    if target_type == "recipe":
        try:
            import routes_recipes
            with routes_recipes._RECIPES_LOCK:
                recipe = dict(routes_recipes._RECIPES.get(target_id) or {})
            if not recipe:
                return None, f"recipe '{target_id}' not found"
            steps = recipe.get("steps")
            if not isinstance(steps, list) or not steps:
                return None, f"recipe '{target_id}' has no steps"
            return steps, None
        except Exception as exc:
            return None, f"recipes engine unavailable: {type(exc).__name__}: {exc}"
    if target_type == "workflow":
        try:
            import routes_workflows
            workflow = routes_workflows._load_workflow(target_id)
            if not workflow:
                return None, f"workflow '{target_id}' not found"
            recipe = routes_workflows._compile_workflow(workflow)
            steps = recipe.get("steps") if isinstance(recipe, dict) else None
            if not isinstance(steps, list) or not steps:
                return None, f"workflow '{target_id}' compiled to zero steps"
            return steps, None
        except Exception as exc:
            return None, f"workflows engine unavailable: {type(exc).__name__}: {exc}"
    return None, "target_type must be 'recipe' or 'workflow'"


def _run_inbound_target(hook_id, hook, payload, run_id):
    """Run the mapped target in a background thread and record the result."""
    started = time.time()
    steps, error = _resolve_inbound_steps(hook)
    if error:
        result = {"run_id": run_id, "hook_id": hook_id, "status": "error", "error": error}
    else:
        try:
            import routes_recipes
            # Seed the webhook payload as $prev.input / $prev.webhook so steps
            # can template in the received JSON body.
            results = routes_recipes._execute_steps(
                steps,
                auth_header=None,
                initial_context={"input": payload, "webhook": payload},
            )
            failed = [r for r in results if r.get("status") != "ok"]
            result = {
                "run_id": run_id,
                "hook_id": hook_id,
                "status": "failed" if failed else "completed",
                "completed": sum(1 for r in results if r.get("status") == "ok"),
                "failed": len(failed),
                "steps": results,
            }
        except Exception as exc:
            result = {
                "run_id": run_id,
                "hook_id": hook_id,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
    result["trigger"] = "inbound_webhook"
    result["duration_seconds"] = round(time.time() - started, 3)
    with _INBOUND_LOCK:
        current = _INBOUND_HOOKS.get(hook_id)
        if current:
            current["last_received"] = _now()
            current["last_run"] = result
            recent = list(current.get("recent_runs") or [])
            recent.insert(0, result)
            current["recent_runs"] = recent[:_INBOUND_RECENT_LIMIT]
    _log(
        f"[webhooks] inbound {hook_id} -> {result.get('status')} "
        f"({result.get('completed', 0)} ok / {result.get('failed', 0)} failed)"
    )
    return result


@webhooks_bp.route("/webhooks/incoming/register", methods=["POST"])
def route_webhooks_incoming_register():
    data = _json_body() or {}
    target_type = str(data.get("target_type") or "").strip().lower()
    target_id = str(data.get("target_id") or "").strip()
    secret = str(data.get("secret") or "").strip()
    if target_type not in {"recipe", "workflow"}:
        return jsonify({"error": "target_type must be 'recipe' or 'workflow'"}), 400
    if not target_id:
        return jsonify({"error": "target_id is required"}), 400
    # Resolve the target now so a hook pointing at a missing recipe/workflow is rejected.
    steps, error = _resolve_inbound_steps({"target_type": target_type, "target_id": target_id})
    if error:
        return jsonify({"error": error}), 400
    hook_id = secrets.token_urlsafe(18)
    if not secret:
        secret = secrets.token_urlsafe(32)
    record = {
        "target_type": target_type,
        "target_id": target_id,
        "secret": secret,
        "created_at": _now(),
        "last_received": None,
        "last_run": None,
        "recent_runs": [],
    }
    with _INBOUND_LOCK:
        _INBOUND_HOOKS[hook_id] = record
    return jsonify(_inbound_public(hook_id, record, include_secret=True)), 201


@webhooks_bp.route("/webhooks/incoming/list", methods=["GET"])
def route_webhooks_incoming_list():
    with _INBOUND_LOCK:
        hooks = [
            _inbound_public(hook_id, record)
            for hook_id, record in sorted(_INBOUND_HOOKS.items())
        ]
    return jsonify({"inbound_webhooks": hooks, "count": len(hooks)})


@webhooks_bp.route("/webhooks/incoming/test/<hook_id>", methods=["POST"])
def route_webhooks_incoming_test(hook_id):
    with _INBOUND_LOCK:
        record = dict(_INBOUND_HOOKS.get(hook_id) or {})
    if not record:
        return jsonify({"error": "inbound hook not found", "id": hook_id}), 404
    data = _json_body() or {}
    run_id = uuid.uuid4().hex
    threading.Thread(
        target=_run_inbound_target,
        args=(hook_id, record, data, run_id),
        name=f"inbound-test-{hook_id[:8]}",
        daemon=True,
    ).start()
    return jsonify({"status": "queued", "run_id": run_id, "hook_id": hook_id})


@webhooks_bp.route("/webhooks/incoming/<hook_id>", methods=["POST"])
def route_webhooks_incoming_receive(hook_id):
    with _INBOUND_LOCK:
        record = dict(_INBOUND_HOOKS.get(hook_id) or {})
    if not record:
        return jsonify({"error": "inbound hook not found", "id": hook_id}), 404
    raw_body = request.get_data()
    signature = request.headers.get("X-Webhook-Signature", "")
    if not _verify_inbound_signature(raw_body, record.get("secret"), signature):
        return jsonify({"error": "invalid signature"}), 401
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        payload = {"raw": raw_body.decode("utf-8", errors="replace")}
    run_id = uuid.uuid4().hex
    threading.Thread(
        target=_run_inbound_target,
        args=(hook_id, record, payload, run_id),
        name=f"inbound-{hook_id[:8]}",
        daemon=True,
    ).start()
    return jsonify({"status": "accepted", "run_id": run_id, "hook_id": hook_id}), 202


# The receive endpoint is public (no Bearer token): external callers authenticate
# via the per-hook HMAC secret instead. The global auth gate and the wrapper
# below both skip any view function carrying this flag.
route_webhooks_incoming_receive._hermes_public = True


@webhooks_bp.route("/webhooks/incoming/<hook_id>", methods=["DELETE"])
def route_webhooks_incoming_delete(hook_id):
    with _INBOUND_LOCK:
        removed = _INBOUND_HOOKS.pop(hook_id, None)
    if not removed:
        return jsonify({"error": "inbound hook not found", "id": hook_id}), 404
    return jsonify({"status": "deleted", "id": hook_id})


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
    response = _public_webhook(webhook_id, record)
    response["secret"] = record["secret"]  # one-time reveal
    return jsonify(response), 201


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
        try:
            _dispatch_one(webhook_id, record, "test", {"ok": True}, timestamp)
        except Exception as exc:
            _log(f"[webhooks] test dispatch failed for {webhook_id}: {exc}")

    threading.Thread(target=_worker, name=f"webhook-test-{webhook_id}", daemon=True).start()
    return jsonify({"status": "queued", "id": webhook_id, "event": "test"})


def register_routes(app, state, require_auth):
    for endpoint, view_func in list(webhooks_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        if getattr(view_func, "_hermes_public", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        webhooks_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(webhooks_bp)
