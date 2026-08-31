"""Fail-State Recovery Daemon.

Background thread: periodically OCR the screen looking for unexpected modal dialogs
(error popups, trial expired, update dialogs). Dismisses them automatically.
"""
import copy
import logging
import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from shared import _self_port, _wrap_registered_blueprint_routes

_LOGGER = logging.getLogger(__name__)
recovery_bp = Blueprint("recovery_daemon", __name__)

_RECOVERY_STATE = {
    "running": False,
    "check_interval_secs": 5,
    "triggers": 0,
    "dismissals": 0,
    "failures": 0,
    "last_popup": None,
    "last_seen_at": None,
    "recent_events": [],
    "popup_keywords": [
        "error", "trial expired", "would you like to", "are you sure",
        "remind me", "update available", "unexpected error",
        "do you want to", "please wait", "loading", "not responding",
    ],
    "dismiss_keywords": ["no", "cancel", "don't save", "remind me later",
                         "close", "ok", "dismiss"],
}
_RECOVERY_LOCK = threading.Lock()
_RECOVERY_THREAD = None
_RECOVERY_STOP = threading.Event()
_MAX_EVENTS = 50


def _debug_failure(context, exc):
    _LOGGER.debug("recovery %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _ocr_screen():
    """Take screenshot and run OCR, return list of found text."""
    try:
        from routes_ocr import ocr_find_text
        # Use OCR directly on a fresh screenshot
        results = []
        for keyword in _RECOVERY_STATE.get("popup_keywords", []):
            matches = ocr_find_text(keyword)
            if matches:
                results.append({"keyword": keyword, "matches": matches})
        return results
    except Exception as exc:
        _debug_failure("ocr_screen", exc)
        return []


def _dismiss_popup(match):
    """Click the actual dismiss button for a detected popup, or do nothing.

    Clicking a blind pixel offset from the popup keyword's text match can land
    on a destructive button (e.g. "Delete", "Confirm"). Instead we OCR the
    screen for the configured dismiss_keywords and click the center of that
    match; if none is found we fail safe and click nothing.
    """
    try:
        import json
        import urllib.request
        from routes_ocr import _fullpage_auth_headers, ocr_find_text
        with _RECOVERY_LOCK:
            dismiss_keywords = list(_RECOVERY_STATE.get("dismiss_keywords", []))
        x = y = None
        for keyword in dismiss_keywords:
            found = ocr_find_text(keyword)
            if not found:
                continue
            first = found[0]
            center = first.get("center", {}) if isinstance(first, dict) else {}
            x, y = center.get("x"), center.get("y")
            if x is not None and y is not None:
                break
        if x is None or y is None:
            _LOGGER.debug("recovery: no dismiss button located; skipping click to avoid misclick")
            return False
        url = f"http://127.0.0.1:{_self_port()}/mouse/click"
        data = json.dumps({"x": x, "y": y}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        # Attach the same auth token the rest of the service uses so the click
        # is authorized even when auth is enabled (otherwise it silently 401s).
        try:
            headers.update(_fullpage_auth_headers() or {})
        except Exception:
            pass
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read(256)
        return True
    except Exception as exc:
        _debug_failure("dismiss_popup", exc)
    return False


def _recovery_loop():
    _LOGGER.info("Recovery daemon started")
    while not _RECOVERY_STOP.is_set():
        try:
            popups = _ocr_screen()
            if popups:
                with _RECOVERY_LOCK:
                    _RECOVERY_STATE["triggers"] += 1
                    _RECOVERY_STATE["last_seen_at"] = datetime.now(timezone.utc).isoformat()
                    _RECOVERY_STATE["last_popup"] = popups[0].get("keyword", "unknown")
                for popup in popups:
                    for match in popup.get("matches", []):
                        if _dismiss_popup(match):
                            with _RECOVERY_LOCK:
                                _RECOVERY_STATE["dismissals"] += 1
                                event = {
                                    "time": datetime.now(timezone.utc).isoformat(),
                                    "keyword": popup["keyword"],
                                    "dismissed": True,
                                }
                                _RECOVERY_STATE["recent_events"].append(event)
                                _RECOVERY_STATE["recent_events"] = \
                                    _RECOVERY_STATE["recent_events"][-_MAX_EVENTS:]
                        else:
                            with _RECOVERY_LOCK:
                                _RECOVERY_STATE["failures"] += 1
        except Exception as exc:
            _debug_failure("recovery_loop", exc)
        _RECOVERY_STOP.wait(_RECOVERY_STATE.get("check_interval_secs", 5))
    _LOGGER.info("Recovery daemon stopped")


@recovery_bp.route("/recovery/start", methods=["POST"])
def _recovery_start():
    global _RECOVERY_THREAD
    # The check-and-start sequence must be atomic. Previously the first lock
    # block was released before the second, so two concurrent /recovery/start
    # calls (or a start racing a stop) could observe running=False, signal the
    # shared stop event, and kill the freshly-started thread — leaving the
    # daemon dead while "running" stayed True. Holding the lock for the whole
    # sequence (and checking thread liveness rather than just the boolean)
    # closes that race.
    with _RECOVERY_LOCK:
        if _RECOVERY_THREAD is not None and _RECOVERY_THREAD.is_alive():
            # A live worker already exists (even if a stop was just requested and
            # it is still winding down) — never start a second OCR/click loop.
            return jsonify({"ok": True, "already_running": True})
        _RECOVERY_STOP.clear()
        _RECOVERY_THREAD = threading.Thread(target=_recovery_loop, daemon=True)
        _RECOVERY_THREAD.start()
        _RECOVERY_STATE["running"] = True
    return jsonify({"ok": True, "started": True})


@recovery_bp.route("/recovery/stop", methods=["POST"])
def _recovery_stop():
    _RECOVERY_STOP.set()
    with _RECOVERY_LOCK:
        _RECOVERY_STATE["running"] = False
    return jsonify({"ok": True, "stopped": True})


@recovery_bp.route("/recovery/status", methods=["GET"])
def _recovery_status():
    with _RECOVERY_LOCK:
        return jsonify({"ok": True, **copy.deepcopy(_RECOVERY_STATE)})


@recovery_bp.route("/recovery/dismissals", methods=["GET"])
def _recovery_dismissals():
    with _RECOVERY_LOCK:
        return jsonify({"ok": True, "events": list(_RECOVERY_STATE["recent_events"])})


@recovery_bp.route("/recovery/configure", methods=["POST"])
def _recovery_configure():
    body = request.get_json(force=True, silent=True) or {}
    new_interval = None
    if "check_interval_secs" in body:
        try:
            new_interval = int(body["check_interval_secs"])
        except (TypeError, ValueError):
            return jsonify({"error": "check_interval_secs must be an integer"}), 400
        if new_interval <= 0:
            return jsonify({"error": "check_interval_secs must be positive"}), 400
        if new_interval > 3600:
            return jsonify({"error": "check_interval_secs must be <= 3600"}), 400
    for key in ("popup_keywords", "dismiss_keywords"):
        if key in body:
            val = body[key]
            if not isinstance(val, list) or not all(isinstance(k, str) and k.strip() for k in val):
                return jsonify({"error": f"{key} must be a list of non-empty strings"}), 400
            if len(val) > 64:
                return jsonify({"error": f"{key} must have at most 64 entries"}), 400
    with _RECOVERY_LOCK:
        if new_interval is not None:
            _RECOVERY_STATE["check_interval_secs"] = new_interval
        for key in ("popup_keywords", "dismiss_keywords"):
            if key in body:
                _RECOVERY_STATE[key] = body[key]
    return jsonify({"ok": True, **copy.deepcopy(_RECOVERY_STATE)})


def register_routes(app, state, require_auth):
    app.register_blueprint(recovery_bp)
    _wrap_registered_blueprint_routes(app, recovery_bp.name, require_auth)
    _LOGGER.info("Recovery daemon routes registered")
