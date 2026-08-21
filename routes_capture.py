"""Semantic Run Capture & Deterministic Replay (issue #726).

Turns a successful one-off run into a durable, human-readable, LLM-free
automation. Each captured step stores UIA-anchored target identity
(automation_id, name, control_type, window title/handle) plus the action
and typed text — never raw screen coordinates. Replay resolves targets
via UIA first, then OCR/SOM, so the automation survives window moves and
resolution changes.

Endpoints:
    POST /capture/start        — begin capture (resets buffer)
    POST /capture/stop         — end capture, return sequence
    POST /capture/action       — record (and optionally execute) a step
    GET  /capture/status       — recording state + buffered step count
    POST /capture/save         — persist current buffer under a name
    GET  /capture/list         — list saved captures
    GET  /capture/get/<name>   — read a saved capture
    POST /capture/delete/<n>   — delete a saved capture
    GET  /capture/export       — export last or named capture as recipe|script
    POST /capture/replay       — run captured steps deterministically
    POST /capture/from-goal-run — save a completed /agent/plan-and-execute
                                  result as a named recipe/capture in one call
"""

import json
import re
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field

CAPTURES_DIR = COAGENT_DIR / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_STATE = {
    "recording": False,
    "started_at": 0.0,
    "steps": [],
    "session_id": "",
}
_STATE_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# UIA / OCR helpers — imported lazily so this module remains importable
# in environments where uia_engine is unavailable (linux CI, unit-test hosts).
# ---------------------------------------------------------------------------

def _get_uia_engine():
    try:
        import sys
        if str(COAGENT_DIR) not in sys.path:
            sys.path.insert(0, str(COAGENT_DIR))
        import uia_engine as ue
        return ue
    except Exception as exc:
        _log(f"[capture] uia_engine unavailable: {type(exc).__name__}: {exc}")
        return None


def _hybrid_find(text, control_type=None, fallback_to_ocr=True):
    """Resolve a semantic target to on-screen coordinates.

    UIA identity first, then OCR/SOM fallback. Returns a dict with
    center/x/y/method/element_info, or {"found": False, ...} on miss.
    """
    ue = _get_uia_engine()
    if ue is None:
        return {"found": False, "error": "uia_engine unavailable"}
    try:
        from routes_uia import _find_hybrid_element
    except Exception as exc:
        return {"found": False, "error": f"routes_uia unavailable: {exc}"}
    try:
        return _find_hybrid_element(ue, text, control_type or "", fallback_to_ocr=fallback_to_ocr)
    except Exception as exc:
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}


def _capture_identity(text=None, automation_id=None, name=None,
                      control_type=None, window_title=None):
    """Snapshot the UIA identity of a target at record time.

    Fills in the automation_id / control_type / class_name / window we
    matched so replay can look for the *same* element, not just any
    element with the same visible text.
    """
    query = automation_id or name or text
    if not query:
        return {
            "text": text or "",
            "automation_id": automation_id or "",
            "name": name or "",
            "control_type": control_type or "",
            "window_title": window_title or "",
            "resolved": False,
        }
    payload = _hybrid_find(query, control_type=control_type)
    info = payload.get("element_info") if isinstance(payload, dict) else {}
    if not isinstance(info, dict):
        info = {}
    return {
        "text": text or info.get("name") or query,
        "automation_id": automation_id or info.get("automation_id", "") or "",
        "name": name or info.get("name", "") or "",
        "control_type": control_type or info.get("control_type", "") or "",
        "class_name": info.get("class_name", "") or "",
        "window_title": window_title or info.get("window_title", "") or "",
        "resolved": bool(payload and payload.get("found")),
        "method": payload.get("method") if isinstance(payload, dict) else None,
        "rect_hint": info.get("rect") if isinstance(info, dict) else None,
    }


# ---------------------------------------------------------------------------
# Capture buffer
# ---------------------------------------------------------------------------

def _append_step(step):
    with _STATE_LOCK:
        if not _STATE["recording"]:
            return False
        step["t"] = round(time.time() - _STATE["started_at"], 3)
        _STATE["steps"].append(step)
        return True


def record_semantic_step(action, target=None, typed_text=None, intent=None,
                         params=None):
    """Public hook: other modules can push a semantic step into the buffer.

    No-op when no capture session is active. Returns True if recorded.
    """
    action = str(action or "").strip().lower()
    if not action:
        return False
    entry = {
        "action": action,
        "intent": (intent or "").strip(),
    }
    if isinstance(target, dict):
        entry["target"] = target
    if typed_text is not None:
        entry["typed_text"] = str(typed_text)
    if isinstance(params, dict):
        entry["params"] = params
    return _append_step(entry)


# ---------------------------------------------------------------------------
# Named capture storage
# ---------------------------------------------------------------------------

def _capture_path(name):
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("capture name must match [A-Za-z0-9_-]{1,64}")
    return CAPTURES_DIR / f"{name}.json"


def _write_capture(name, capture):
    path = _capture_path(name)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(capture, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _read_capture(name):
    path = _capture_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"capture {name!r} not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Recipe / script emission
# ---------------------------------------------------------------------------

def _capture_to_recipe(capture, name=None):
    """Convert a semantic capture to routes_recipes.py-compatible JSON."""
    steps = []
    for entry in capture.get("steps") or []:
        action = str(entry.get("action") or "").strip().lower()
        target = entry.get("target") or {}
        params = dict(entry.get("params") or {})
        recipe_target = {}
        for key in ("text", "name", "automation_id", "control_type",
                    "class_name", "window_title"):
            value = target.get(key) if isinstance(target, dict) else None
            if value:
                recipe_target[key] = value
        # Map control_type -> the "type" hint that /uia/click-hybrid uses.
        if "control_type" in recipe_target and "type" not in recipe_target:
            recipe_target["type"] = recipe_target["control_type"]
        recipe_target["fallback_to_ocr"] = True
        typed = entry.get("typed_text")
        if action in {"type", "type_text"} and typed is not None:
            params.setdefault("text", typed)
        step = {"action": action, "params": params}
        if recipe_target:
            step["target"] = recipe_target
        if entry.get("intent"):
            step["intent"] = entry["intent"]
        steps.append(step)
    return {
        "name": str(name or capture.get("name") or f"capture_{int(time.time())}"),
        "steps": steps,
        "created_at": capture.get("created_at") or int(time.time()),
        "source": "semantic_capture",
    }


def _capture_to_script(capture, name=None):
    """Emit a standalone Python script that replays via CoAgent HTTP API."""
    recipe = _capture_to_recipe(capture, name=name)
    body = {
        "name": recipe["name"],
        "steps": recipe["steps"],
    }
    steps_json = json.dumps(body, indent=2)
    return (
        "#!/usr/bin/env python3\n"
        '"""Auto-generated by CoAgent semantic capture (issue #726).\n\n'
        "Replays the captured session against a running CoAgent server.\n"
        "Set COAGENT_URL and COAGENT_TOKEN environment variables to point at\n"
        "your server. Requires only the Python stdlib.\n"
        '"""\n'
        "import json\n"
        "import os\n"
        "import urllib.request\n"
        "\n"
        f"CAPTURE = json.loads({json.dumps(steps_json)})\n"
        "\n"
        "def _post(path, body):\n"
        "    url = os.environ.get('COAGENT_URL', 'http://127.0.0.1:8765').rstrip('/') + path\n"
        "    token = os.environ.get('COAGENT_TOKEN', '')\n"
        "    headers = {'Content-Type': 'application/json'}\n"
        "    if token:\n"
        "        headers['Authorization'] = 'Bearer ' + token\n"
        "    data = json.dumps(body).encode('utf-8')\n"
        "    req = urllib.request.Request(url, data=data, headers=headers, method='POST')\n"
        "    with urllib.request.urlopen(req, timeout=60) as resp:\n"
        "        return json.loads(resp.read().decode('utf-8'))\n"
        "\n"
        "def main():\n"
        "    result = _post('/capture/replay', {'steps': CAPTURE['steps']})\n"
        "    print(json.dumps(result, indent=2))\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _click_at(x, y, button="left"):
    try:
        from uia_engine import send_mouse_click
        send_mouse_click(int(x), int(y), button=button)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _type_text_now(text):
    try:
        from uia_engine import send_input_background
        send_input_background(str(text))
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _scroll_now(delta):
    try:
        from uia_engine import send_scroll
        send_scroll(int(delta))
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _resolve_step_target(target):
    """UIA-first target resolution with OCR/SOM fallback.

    Returns a dict {ok, x, y, method, resolved_via} — 'method' is 'uia'
    or 'ocr' (the underlying resolver picks); 'resolved_via' is the field
    we queried on. Never uses raw record-time coordinates.
    """
    if not isinstance(target, dict):
        return {"ok": False, "error": "no target"}
    # Prefer the most specific identity first.
    for field in ("automation_id", "name", "text"):
        query = target.get(field)
        if not query:
            continue
        payload = _hybrid_find(query, control_type=target.get("control_type"))
        if payload and payload.get("found"):
            center = payload.get("center") or {}
            x = center.get("x", payload.get("x"))
            y = center.get("y", payload.get("y"))
            if x is None or y is None:
                continue
            return {
                "ok": True,
                "x": int(x),
                "y": int(y),
                "method": payload.get("method", "uia"),
                "resolved_via": field,
                "element": payload.get("element_info", {}),
            }
    return {"ok": False, "error": "target not found via UIA or OCR"}


def _replay_step(step):
    action = str(step.get("action") or "").strip().lower()
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    record = {"action": action, "ok": False}
    try:
        if action == "wait":
            seconds = max(0.0, min(float(params.get("seconds", 0.5)), 30.0))
            time.sleep(seconds)
            record["ok"] = True
            return record
        if action in {"type", "type_text"}:
            typed = step.get("typed_text")
            if typed is None:
                typed = params.get("text", "")
            if target and (target.get("text") or target.get("automation_id") or target.get("name")):
                resolved = _resolve_step_target(target)
                record["resolve"] = resolved
                if resolved.get("ok"):
                    _click_at(resolved["x"], resolved["y"])
                    time.sleep(0.15)
                else:
                    record["error"] = "target not found; refusing to type into unfocused window"
                    return record
            ok, err = _type_text_now(typed)
            record["ok"] = ok
            if err:
                record["error"] = err
            return record
        if action in {"key", "hotkey", "press"}:
            keys = params.get("keys") or params.get("key") or []
            if isinstance(keys, str):
                keys = [p for p in keys.replace("+", " ").split() if p]
            try:
                from uia_engine import send_input
                send_input(keys)
                record["ok"] = True
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            return record
        if action == "scroll":
            ok, err = _scroll_now(params.get("delta", -3))
            record["ok"] = ok
            if err:
                record["error"] = err
            return record
        if action in {"click", "double_click", "right_click"}:
            resolved = _resolve_step_target(target)
            record["resolve"] = resolved
            if not resolved.get("ok"):
                record["error"] = resolved.get("error", "target not resolvable")
                return record
            button = "right" if action == "right_click" else "left"
            clicks = 2 if action == "double_click" else 1
            try:
                from uia_engine import send_mouse_click
                for _ in range(clicks):
                    send_mouse_click(resolved["x"], resolved["y"], button=button)
                    if clicks > 1:
                        time.sleep(0.08)
                record["ok"] = True
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            return record
        record["error"] = f"unknown action: {action}"
        return record
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
        return record


def _replay_steps(steps, inter_step_delay=0.15):
    results = []
    ok_count = 0
    for index, step in enumerate(steps or []):
        started = time.time()
        outcome = _replay_step(step)
        outcome["step_index"] = index
        outcome["duration"] = round(time.time() - started, 3)
        results.append(outcome)
        if outcome.get("ok"):
            ok_count += 1
        else:
            break
        if inter_step_delay > 0 and index < len(steps) - 1:
            time.sleep(inter_step_delay)
    return {
        "ok": ok_count == len(steps or []),
        "completed": ok_count,
        "total": len(steps or []),
        "steps": results,
    }


# ---------------------------------------------------------------------------
# Goal-run -> capture bridge
# ---------------------------------------------------------------------------

def _goal_run_to_capture(results, name=None):
    """Convert a /agent/plan-and-execute results list to a capture."""
    steps = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or item.get("step_action") or "act").lower()
        target = item.get("target") or item.get("query") or item.get("text")
        payload = item.get("result") if isinstance(item.get("result"), dict) else {}
        info = payload.get("element_info") if isinstance(payload, dict) else {}
        target_dict = {}
        if isinstance(target, dict):
            target_dict.update(target)
        elif isinstance(target, str) and target:
            target_dict["text"] = target
        if isinstance(info, dict):
            for key in ("automation_id", "name", "control_type", "class_name"):
                if info.get(key) and key not in target_dict:
                    target_dict[key] = info[key]
        step = {"action": action, "intent": item.get("intent") or ""}
        if target_dict:
            step["target"] = target_dict
        typed = item.get("text") if action in {"type", "type_text"} else None
        if typed:
            step["typed_text"] = typed
        steps.append(step)
    return {
        "name": str(name or f"goalrun_{int(time.time())}"),
        "created_at": int(time.time()),
        "source": "goal_run",
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/capture/start", methods=["POST"])
    @require_auth
    def route_capture_start():
        body = _json_body() or {}
        with _STATE_LOCK:
            if _STATE["recording"]:
                return jsonify({"ok": False, "error": "already recording",
                                "session_id": _STATE["session_id"]}), 409
            _STATE["recording"] = True
            _STATE["steps"] = []
            _STATE["started_at"] = time.time()
            _STATE["session_id"] = uuid.uuid4().hex[:12]
            _STATE["intent"] = (body.get("intent") or body.get("goal") or "").strip()
        _log(f"[capture] started session={_STATE['session_id']}")
        return jsonify({
            "ok": True,
            "recording": True,
            "session_id": _STATE["session_id"],
            "intent": _STATE.get("intent", ""),
        })

    @app.route("/capture/stop", methods=["POST"])
    @require_auth
    def route_capture_stop():
        with _STATE_LOCK:
            if not _STATE["recording"]:
                return jsonify({"ok": False, "error": "not recording"}), 409
            _STATE["recording"] = False
            steps = list(_STATE["steps"])
            session_id = _STATE["session_id"]
            duration = round(time.time() - _STATE["started_at"], 3)
            intent = _STATE.get("intent", "")
        capture = {
            "session_id": session_id,
            "intent": intent,
            "created_at": int(time.time()),
            "duration": duration,
            "step_count": len(steps),
            "steps": steps,
        }
        _log(f"[capture] stopped session={session_id} steps={len(steps)}")
        return jsonify({"ok": True, "capture": capture})

    @app.route("/capture/status", methods=["GET"])
    @require_auth
    def route_capture_status():
        with _STATE_LOCK:
            return jsonify({
                "ok": True,
                "recording": _STATE["recording"],
                "session_id": _STATE["session_id"],
                "step_count": len(_STATE["steps"]),
                "intent": _STATE.get("intent", ""),
                "elapsed": round(time.time() - _STATE["started_at"], 2)
                          if _STATE["recording"] else 0.0,
            })

    @app.route("/capture/action", methods=["POST"])
    @require_auth
    def route_capture_action():
        body = _json_body() or {}
        action = str(body.get("action") or "").strip().lower()
        if not action:
            return _missing_field("action")
        with _STATE_LOCK:
            if not _STATE["recording"]:
                return jsonify({"ok": False, "error": "not recording"}), 409

        text = body.get("text") or body.get("target")
        automation_id = body.get("automation_id")
        name = body.get("name")
        control_type = body.get("control_type") or body.get("type")
        window_title = body.get("window_title") or body.get("window")
        typed_text = body.get("typed_text")
        if typed_text is None and action in {"type", "type_text"}:
            typed_text = body.get("text", "")

        # Snapshot the UIA identity at record time so replay can find the
        # same element even if the visible label changes.
        target = None
        needs_target = action in {"click", "double_click", "right_click",
                                   "type", "type_text", "scroll"}
        if needs_target and (text or automation_id or name):
            try:
                target = _capture_identity(
                    text=text if isinstance(text, str) else None,
                    automation_id=automation_id,
                    name=name,
                    control_type=control_type,
                    window_title=window_title,
                )
            except Exception as exc:
                _log(f"[capture] identity snapshot failed: {exc}")
                target = {"text": text or "", "automation_id": automation_id or "",
                          "name": name or "", "control_type": control_type or "",
                          "window_title": window_title or "", "resolved": False}

        entry = {
            "action": action,
            "intent": (body.get("intent") or "").strip(),
        }
        if target:
            entry["target"] = target
        if typed_text is not None:
            entry["typed_text"] = str(typed_text)
        params = body.get("params")
        if isinstance(params, dict):
            entry["params"] = params

        _append_step(entry)

        # Optional: execute the action right now so the operator can drive
        # the workflow through /capture/action calls directly.
        execution = None
        if bool(body.get("execute", False)):
            execution = _replay_step(dict(entry))
        return jsonify({"ok": True, "step": entry, "executed": execution})

    @app.route("/capture/save", methods=["POST"])
    @require_auth
    def route_capture_save():
        body = _json_body() or {}
        name = body.get("name") or f"capture_{int(time.time())}"
        try:
            path = _capture_path(name)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        with _STATE_LOCK:
            steps = list(_STATE["steps"])
            session_id = _STATE["session_id"]
            duration = round(time.time() - _STATE["started_at"], 3) if _STATE["started_at"] else 0.0
            intent = _STATE.get("intent", "")
        if not steps:
            return jsonify({"ok": False, "error": "no steps to save"}), 400
        capture = {
            "name": name,
            "session_id": session_id,
            "intent": intent,
            "created_at": int(time.time()),
            "duration": duration,
            "step_count": len(steps),
            "steps": steps,
        }
        try:
            _write_capture(name, capture)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({"ok": True, "name": name, "path": str(path),
                        "step_count": len(steps)})

    @app.route("/capture/list", methods=["GET"])
    @require_auth
    def route_capture_list():
        items = []
        for path in sorted(CAPTURES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "name": data.get("name") or path.stem,
                    "intent": data.get("intent", ""),
                    "step_count": data.get("step_count", len(data.get("steps") or [])),
                    "created_at": data.get("created_at"),
                    "duration": data.get("duration"),
                    "source": data.get("source", "semantic_capture"),
                })
            except Exception as exc:
                _log(f"[capture] skip {path.name}: {exc}")
        return jsonify({"ok": True, "captures": items, "count": len(items)})

    @app.route("/capture/get/<name>", methods=["GET"])
    @require_auth
    def route_capture_get(name):
        try:
            capture = _read_capture(name)
        except FileNotFoundError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "capture": capture})

    @app.route("/capture/delete/<name>", methods=["POST"])
    @require_auth
    def route_capture_delete(name):
        try:
            path = _capture_path(name)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if not path.is_file():
            return jsonify({"ok": False, "error": "capture not found"}), 404
        try:
            path.unlink()
        except OSError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True, "deleted": name})

    @app.route("/capture/export", methods=["GET"])
    @require_auth
    def route_capture_export():
        from flask import request
        fmt = (request.args.get("format") or "recipe").strip().lower()
        name = (request.args.get("name") or "").strip()
        if name:
            try:
                capture = _read_capture(name)
            except FileNotFoundError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 404
            except ValueError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        else:
            with _STATE_LOCK:
                steps = list(_STATE["steps"])
                capture = {
                    "name": name or f"capture_{int(time.time())}",
                    "session_id": _STATE.get("session_id", ""),
                    "intent": _STATE.get("intent", ""),
                    "created_at": int(time.time()),
                    "step_count": len(steps),
                    "steps": steps,
                }
            if not steps:
                return jsonify({"ok": False, "error": "no capture buffered"}), 400
        if fmt == "script":
            script = _capture_to_script(capture, name=name or capture.get("name"))
            return jsonify({"ok": True, "format": "script", "script": script,
                            "name": capture.get("name")})
        recipe = _capture_to_recipe(capture, name=name or capture.get("name"))
        return jsonify({"ok": True, "format": "recipe", "recipe": recipe,
                        "name": capture.get("name")})

    @app.route("/capture/replay", methods=["POST"])
    @require_auth
    def route_capture_replay():
        body = _json_body() or {}
        steps = None
        capture_name = (body.get("name") or "").strip()
        if capture_name:
            try:
                capture = _read_capture(capture_name)
            except FileNotFoundError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 404
            except ValueError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
            steps = capture.get("steps") or []
        elif isinstance(body.get("steps"), list):
            steps = body["steps"]
        else:
            with _STATE_LOCK:
                if not _STATE["steps"]:
                    return jsonify({"ok": False,
                                    "error": "no steps: pass 'name' or 'steps' or capture first"}), 400
                steps = list(_STATE["steps"])
        try:
            inter_delay = max(0.0, min(float(body.get("delay", 0.15)), 5.0))
        except (TypeError, ValueError):
            inter_delay = 0.15
        result = _replay_steps(steps, inter_step_delay=inter_delay)
        result["source"] = capture_name or ("buffer" if not body.get("steps") else "steps")
        status = 200 if result.get("ok") else 409
        return jsonify(result), status

    @app.route("/recipe/run", methods=["POST"])
    @require_auth
    def route_recipe_run_alias():
        # Alias for /capture/replay when the caller wants recipe-style semantics.
        return route_capture_replay()

    @app.route("/capture/from-goal-run", methods=["POST"])
    @require_auth
    def route_capture_from_goal_run():
        body = _json_body() or {}
        results = body.get("results") or body.get("steps") or body.get("run")
        if not isinstance(results, list) or not results:
            return _missing_field("results (list of goal-run step records)")
        name = (body.get("name") or f"goalrun_{int(time.time())}").strip()
        try:
            _capture_path(name)  # validate
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        capture = _goal_run_to_capture(results, name=name)
        capture["intent"] = (body.get("intent") or "").strip()
        try:
            path = _write_capture(name, capture)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({
            "ok": True,
            "name": name,
            "path": str(path),
            "step_count": len(capture.get("steps") or []),
            "capture": capture,
        })
