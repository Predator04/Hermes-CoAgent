"""Android phone sequence memory — controller-side self-learning.

CoAgent drives the Hermes CoAgent Android phone through the relay (the phone
dials OUT to relay/relay.py; the controller POSTs /command and polls /result).
This module adds the controller half of self-learning:

  - A relay config store (relay URL + device_id + token) — no hardcoded secrets.
  - Named action-sequence memory: save a successful multi-step run, replay it
    later instead of re-discovering the UI every time.
  - A proxy to the phone's on-device `telemetry` action (per-app find strategy),
    so the controller can learn which apps are accessibility-opaque.

Endpoints:
  POST /phone/relay/config    — set relay_url + device_id + token
  GET  /phone/relay/config    — show config (token masked)
  POST /phone/sequence/save   — save a named sequence {name, app, steps}
  POST /phone/sequence/play   — replay a sequence through the relay
  GET  /phone/sequence/list   — list saved sequences
  POST /phone/sequence/delete — delete a sequence
  POST /phone/telemetry       — proxy to the phone's telemetry action
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes


phone_memory_bp = Blueprint("phone_memory", __name__)

CONFIG_FILE = COAGENT_DIR / "phone_relay.json"
SEQUENCES_DIR = COAGENT_DIR / "phone_sequences"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_LOCK = threading.RLock()


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _safe_name(name):
    n = str(name or "").strip()
    if not _ID_RE.match(n):
        raise ValueError("invalid sequence name (A-Za-z0-9_.- only)")
    return n


def _load_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    # flush+fsync before os.replace so a crash/power loss can't leave the
    # file truncated (os.replace alone can persist a zero-length temp).
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _save_config(cfg):
    _atomic_write_text(CONFIG_FILE, json.dumps(cfg, indent=2))


def _seq_path(name):
    return SEQUENCES_DIR / f"{_safe_name(name)}.json"


def _load_sequence(name):
    p = _seq_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _http_json(method, url, data=None, timeout=15, extra_headers=None):
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = None
    if method.upper() != "GET":
        headers["Content-Type"] = "application/json"
        body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            return {"error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _relay_request(action, timeout=60):
    """Send one action through the relay and wait for its result."""
    cfg = _load_config()
    if not cfg.get("device_id") or not cfg.get("token"):
        return {"error": "phone relay not configured — POST /phone/relay/config first"}
    relay_url = (cfg.get("relay_url") or "http://localhost:8787").rstrip("/")
    token = cfg["token"]

    posted = _http_json("POST", f"{relay_url}/command",
                        {"device_id": cfg["device_id"], "token": token, "action": action},
                        timeout=10)
    cid = posted.get("command_id") if isinstance(posted, dict) else None
    if not cid:
        return {"error": f"relay did not return command_id: {posted}"}

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 60
    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        res = _http_json("GET",
                         f"{relay_url}/result?command_id={urllib.parse.quote(str(cid))}",
                         timeout=10,
                         extra_headers={"X-Hermes-Token": token})
        if isinstance(res, dict) and res.get("status") == "done":
            result = res.get("result")
            return result if result is not None else {"ok": True}
        time.sleep(0.7)
    return {"error": "relay result timeout", "command_id": cid}


def register_routes(app, state, require_auth):
    SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)

    @phone_memory_bp.route("/phone/relay/config", methods=["POST"])
    def route_phone_config_set():
        data = _json_body() or {}
        cfg = _load_config()
        if data.get("relay_url") is not None:
            cfg["relay_url"] = str(data["relay_url"]).strip().rstrip("/")
        if data.get("device_id") is not None:
            cfg["device_id"] = str(data["device_id"]).strip()
        if data.get("token") is not None:
            cfg["token"] = str(data["token"]).strip()
        with _LOCK:
            _save_config(cfg)
        return jsonify({"ok": True, "relay_url": cfg.get("relay_url", ""),
                        "device_id": cfg.get("device_id", ""),
                        "token_preview": _mask(cfg.get("token", ""))})

    @phone_memory_bp.route("/phone/relay/config", methods=["GET"])
    def route_phone_config_get():
        cfg = _load_config()
        return jsonify({"relay_url": cfg.get("relay_url", ""),
                        "device_id": cfg.get("device_id", ""),
                        "token_preview": _mask(cfg.get("token", ""))})

    @phone_memory_bp.route("/phone/sequence/save", methods=["POST"])
    def route_phone_seq_save():
        data = _json_body() or {}
        try:
            name = _safe_name(data.get("name"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            return jsonify({"error": "steps must be a non-empty list"}), 400
        if len(steps) > 200:
            return jsonify({"error": "too many steps (max 200)"}), 400
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("action"), str) \
                    or not step["action"]:
                return jsonify({"error": "each step must be an object with a non-empty string 'action'"}), 400
        existing = _load_sequence(name)
        seq = {
            "name": name,
            "app": str(data.get("app") or "").strip(),
            "steps": steps,
            "created_at": (existing or {}).get("created_at", _now_iso()),
            "updated_at": _now_iso(),
            "last_play": (existing or {}).get("last_play"),
            "last_success": (existing or {}).get("last_success", None),
        }
        with _LOCK:
            SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(_seq_path(name), json.dumps(seq, indent=2))
        return jsonify({"ok": True, "name": name, "step_count": len(steps)})

    @phone_memory_bp.route("/phone/sequence/play", methods=["POST"])
    def route_phone_seq_play():
        data = _json_body() or {}
        try:
            name = _safe_name(data.get("name"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        seq = _load_sequence(name)
        if not seq:
            return jsonify({"error": "sequence not found", "name": name}), 404
        timeout = data.get("timeout", 60)
        results = []
        failed = False
        for index, step in enumerate(seq.get("steps", [])):
            res = _relay_request(step, timeout=timeout)
            record = {"step": index, "action": step.get("action"),
                      "ok": isinstance(res, dict) and not res.get("error"), "result": res}
            results.append(record)
            if not record["ok"]:
                failed = True
                break
        with _LOCK:
            # Reload under the lock so a concurrent /phone/sequence/save during
            # the (potentially long) play loop isn't clobbered by our stale copy
            # of `steps`. Only the play metadata is updated here.
            current = _load_sequence(name)
            if current is None:
                current = seq
            current["last_play"] = _now_iso()
            current["last_success"] = not failed
            _atomic_write_text(_seq_path(name), json.dumps(current, indent=2))
        return jsonify({"name": name, "completed": not failed,
                        "steps_total": len(seq.get("steps", [])),
                        "steps_run": len(results), "results": results})

    @phone_memory_bp.route("/phone/sequence/list", methods=["GET"])
    def route_phone_seq_list():
        items = []
        for p in sorted(SEQUENCES_DIR.glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
                items.append({"name": s.get("name", p.stem), "app": s.get("app", ""),
                              "step_count": len(s.get("steps", [])),
                              "last_play": s.get("last_play"), "last_success": s.get("last_success"),
                              "updated_at": s.get("updated_at")})
            except Exception:
                continue
        return jsonify({"sequences": items, "count": len(items)})

    @phone_memory_bp.route("/phone/sequence/delete", methods=["POST"])
    def route_phone_seq_delete():
        data = _json_body() or {}
        try:
            name = _safe_name(data.get("name"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        p = _seq_path(name)
        if not p.exists():
            return jsonify({"error": "sequence not found", "name": name}), 404
        with _LOCK:
            p.unlink(missing_ok=True)
        return jsonify({"ok": True, "deleted": name})

    @phone_memory_bp.route("/phone/telemetry", methods=["POST"])
    def route_phone_telemetry():
        data = _json_body() or {}
        action = {"action": "telemetry"}
        pkg = str(data.get("package") or "").strip()
        if pkg:
            action["package"] = pkg
        result = _relay_request(action, timeout=30)
        return jsonify({"package": pkg or None, "telemetry": result})

    app.register_blueprint(phone_memory_bp)
    _wrap_registered_blueprint_routes(app, phone_memory_bp.name, require_auth)
    state.phone_memory = {"config_file": str(CONFIG_FILE), "sequences_dir": str(SEQUENCES_DIR)}


def _mask(token):
    t = str(token or "")
    if len(t) <= 6:
        return "***" if t else ""
    return t[:3] + "***" + t[-3:]
