"""Ember Desktop Buddy — CoAgent integration routes."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime

from flask import jsonify

# Flag populated by register_routes
EMBER_AUTH = None

COAGENT_DIR = Path(__file__).resolve().parent
EMBER_DIR = COAGENT_DIR.parent / "Ember"


def register_routes(app, state, require_auth):
    """Register /buddy routes for Ember control."""

    EMBER_STATE = {
        "enabled": False,
        "pid": None,
        "proc": None,
        "started_at": None,
        "last_error": None,
        "smart_mode": True,
        "size": "medium",
        "speed": "normal",
    }
    # Re-entrant: buddy_toggle calls buddy_stop()/buddy_start() which each
    # acquire this lock, and the running-check + spawn must be atomic to avoid
    # a TOCTOU double-spawn.
    _ember_lock = threading.RLock()

    def _find_ember_py() -> Path | None:
        """Find ember.py — check Ember/ dir next to CoAgent, then Desktop."""
        candidates = [
            COAGENT_DIR.parent / "Ember" / "ember.py",
            Path.home() / "Desktop" / "Ember" / "ember.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _is_running() -> bool:
        # Track the live Popen object instead of querying tasklist by PID:
        # a PID can be reused by the OS after Ember dies, which would make
        # tasklist/taskkill target an unrelated process.
        proc = EMBER_STATE.get("proc")
        if proc is None:
            return False
        return proc.poll() is None

    @app.route("/buddy/status", methods=["GET"])
    @require_auth
    def buddy_status():
        running = _is_running()
        EMBER_STATE["enabled"] = running
        ember_py = _find_ember_py()
        return jsonify({
            "running": running,
            "pid": EMBER_STATE.get("pid"),
            "started_at": EMBER_STATE.get("started_at"),
            "smart_mode": EMBER_STATE.get("smart_mode", True),
            "size": EMBER_STATE.get("size", "medium"),
            "speed": EMBER_STATE.get("speed", "normal"),
            "ember_py": str(ember_py) if ember_py else None,
            "last_error": EMBER_STATE.get("last_error"),
        })

    @app.route("/buddy/start", methods=["POST"])
    @require_auth
    def buddy_start():
        with _ember_lock:
            if _is_running():
                return jsonify({"status": "already_running", "pid": EMBER_STATE.get("pid")})

            ember_py = _find_ember_py()
            if not ember_py:
                EMBER_STATE["last_error"] = "ember.py not found"
                return jsonify({"error": "ember.py not found in Ember/ directory"}), 404

            try:
                create_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                proc = subprocess.Popen(
                    [sys.executable, str(ember_py)],
                    cwd=str(ember_py.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=create_flags,
                )
                EMBER_STATE["enabled"] = True
                EMBER_STATE["pid"] = proc.pid
                EMBER_STATE["proc"] = proc
                EMBER_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
                EMBER_STATE["last_error"] = None
                # Wait a moment to catch immediate crash
                time.sleep(0.5)
                if proc.poll() is not None:
                    EMBER_STATE["enabled"] = False
                    EMBER_STATE["pid"] = None
                    EMBER_STATE["proc"] = None
                    EMBER_STATE["last_error"] = f"Ember exited immediately (code {proc.returncode})"
                    return jsonify({
                        "error": "Ember exited immediately",
                        "returncode": proc.returncode,
                    }), 500
                return jsonify({"status": "started", "pid": proc.pid})
            except Exception as e:
                EMBER_STATE["last_error"] = f"{type(e).__name__}: {e}"
                return jsonify({"error": str(e)}), 500

    @app.route("/buddy/stop", methods=["POST"])
    @require_auth
    def buddy_stop():
        with _ember_lock:
            proc = EMBER_STATE.get("proc")
            pid = EMBER_STATE.get("pid")
            if proc is None:
                return jsonify({"status": "not_running"})
            # Only clear state after the process is confirmed dead — don't
            # report "stopped" when termination actually failed.
            if proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                except Exception as e:
                    EMBER_STATE["last_error"] = f"{type(e).__name__}: {e}"
                    return jsonify({"error": str(e)}), 500
            EMBER_STATE["enabled"] = False
            EMBER_STATE["pid"] = None
            EMBER_STATE["proc"] = None
            return jsonify({"status": "stopped", "pid": pid})

    @app.route("/buddy/toggle", methods=["POST"])
    @require_auth
    def buddy_toggle():
        if _is_running():
            return buddy_stop()
        else:
            return buddy_start()

    @app.route("/buddy/set", methods=["POST"])
    @require_auth
    def buddy_set():
        from flask import request
        data = request.get_json(silent=True) or {}
        with _ember_lock:
            smart_mode = data.get("smart_mode")
            size = data.get("size")
            speed = data.get("speed")

            if smart_mode is not None:
                if isinstance(smart_mode, bool):
                    EMBER_STATE["smart_mode"] = smart_mode
                elif isinstance(smart_mode, str):
                    s = smart_mode.strip().lower()
                    if s in ("true", "1", "yes", "on"):
                        EMBER_STATE["smart_mode"] = True
                    elif s in ("false", "0", "no", "off"):
                        EMBER_STATE["smart_mode"] = False
                    else:
                        return jsonify({"error": "smart_mode must be a boolean"}), 400
                else:
                    return jsonify({"error": "smart_mode must be a boolean"}), 400
            if size in ("small", "medium", "large"):
                EMBER_STATE["size"] = size
            if speed in ("calm", "normal", "hyper"):
                EMBER_STATE["speed"] = speed

            return jsonify({
                "status": "updated",
                "smart_mode": EMBER_STATE["smart_mode"],
                "size": EMBER_STATE["size"],
                "speed": EMBER_STATE["speed"],
            })

    return EMBER_STATE
