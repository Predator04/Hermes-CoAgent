"""Fail-State Recovery Daemon.

Background thread: periodically OCR the screen looking for unexpected modal dialogs
(error popups, trial expired, update dialogs). Dismisses them automatically.
"""
import logging
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request
from shared import _self_port

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
    """Click the dismiss button for a detected popup."""
    try:
        import urllib.request, json
        center = match.get("center", {})
        x, y = center.get("x", 0), center.get("y", 0)
        if x and y:
            # Click dismiss location (usually bottom-right of popup)
            dismiss_x = x + 50
            dismiss_y = y + 50
            url = f"http://127.0.0.1:{_self_port()}/mouse/click"
            data = json.dumps({"x": dismiss_x, "y": dismiss_y}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                pass
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
                    _RECOVERY_STATE["last_seen_at"] = datetime.now().isoformat()
                    _RECOVERY_STATE["last_popup"] = popups[0].get("keyword", "unknown")
                for popup in popups:
                    for match in popup.get("matches", []):
                        if _dismiss_popup(match):
                            with _RECOVERY_LOCK:
                                _RECOVERY_STATE["dismissals"] += 1
                                event = {
                                    "time": datetime.now().isoformat(),
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
    with _RECOVERY_LOCK:
        if _RECOVERY_STATE["running"]:
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
        return jsonify({"ok": True, **_RECOVERY_STATE})


@recovery_bp.route("/recovery/dismissals", methods=["GET"])
def _recovery_dismissals():
    with _RECOVERY_LOCK:
        return jsonify({"ok": True, "events": list(_RECOVERY_STATE["recent_events"])})


@recovery_bp.route("/recovery/configure", methods=["POST"])
def _recovery_configure():
    body = request.get_json(force=True, silent=True) or {}
    with _RECOVERY_LOCK:
        for key in ("check_interval_secs", "popup_keywords", "dismiss_keywords"):
            if key in body:
                _RECOVERY_STATE[key] = body[key]
    return jsonify({"ok": True, **_RECOVERY_STATE})


def register_routes(app, state, require_auth):
    app.register_blueprint(recovery_bp)
    _LOGGER.info("Recovery daemon routes registered")
