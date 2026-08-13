"""Enhanced multi-step AI copilot goal execution routes."""

import json
import os
import queue
import re
import secrets
import threading
import time
import uuid
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

from flask import Blueprint, jsonify, request, stream_with_context

from shared import _self_port, COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes
from shared import sse_pack, sse_stream_response


copilot_enhanced_bp = Blueprint("copilot_enhanced", __name__)

MAX_CONCURRENT_GOALS = 3
MAX_STORED_GOALS = 50
DEFAULT_TIMEOUT_SECONDS = 300
MAX_GOAL_LOG_ENTRIES = 250
MAX_GOAL_EVENTS = 500
MAX_STEER_QUEUE = 20
MAX_STEER_HISTORY = 50
MAX_COMPLETED_RING = 10

_GOALS = {}
_GOAL_ORDER = []
_GOALS_LOCK = threading.RLock()
_TERMINAL_GOAL_STATUSES = {"completed", "failed", "stopped"}


def _now():
    return time.time()


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or _now()))


def _clock(ts=None):
    return time.strftime("%H:%M:%S", time.localtime(ts or _now()))


_LOG_ICONS = {
    "info": "\U0001F7E2",
    "planning": "\U0001F7E1",
    "action": "\U0001F680",
    "success": "\u2705",
    "warn": "\U0001F7E1",
    "error": "\u274C",
    "running": "\U0001F535",
}

_STATUS_ICONS = {
    "queued": "\U0001F7E2",
    "idle": "\U0001F7E2",
    "planning": "\U0001F7E1",
    "running": "\U0001F535",
    "completed": "\u2705",
    "failed": "\U0001F534",
    "stopped": "\U0001F534",
    "stopping": "\U0001F7E1",
}

_ACTION_ICONS = {
    "launch": "\U0001F680",
    "type": "\u2328\ufe0f",
    "key": "\u2328\ufe0f",
    "hotkey": "\u2328\ufe0f",
    "press": "\u2328\ufe0f",
    "click": "\U0001F5B1\ufe0f",
    "mouse_move": "\U0001F5B1\ufe0f",
    "mouse_scroll": "\U0001F5B1\ufe0f",
    "mouse_drag": "\U0001F5B1\ufe0f",
    "ocr_find": "\U0001F441\ufe0f",
    "screenshot": "\U0001F441\ufe0f",
    "wait": "\u23F3",
    "telegram_send": "\U0001F680",
    "finder_click": "\U0001F5B1\ufe0f",
    "finder_type": "\u2328\ufe0f",
}


def _auth_header(preferred=None):
    token_file = COAGENT_DIR / ".token"
    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return f"Bearer {token}"
    except Exception:
        pass
    if preferred:
        return preferred
    try:
        return request.headers.get("Authorization", "")
    except RuntimeError:
        return ""


def _short_text(value, limit=72, fallback=""):
    text = str(value if value is not None else fallback).strip()
    if not text:
        text = str(fallback or "").strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def _title_target(value, fallback="Target"):
    text = _short_text(value, 48, fallback)
    if not text:
        return fallback
    if len(text) <= 24 and re.match(r"^[A-Za-z0-9_. -]+$", text):
        return text.title()
    return text


def _seconds_label(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 1.0
    if seconds.is_integer():
        amount = int(seconds)
        return f"{amount} second" if amount == 1 else f"{amount} seconds"
    return f"{seconds:.1f} seconds"


def _quoted(value, limit=48):
    text = _short_text(value, limit, "")
    return f"'{text}'" if text else "text"


def _keys_label(value):
    keys = value
    if isinstance(keys, str):
        keys = [part for part in keys.replace("+", " ").split() if part]
    if not isinstance(keys, list):
        keys = []
    cleaned = [str(key).strip() for key in keys if str(key).strip()]
    return "+".join(cleaned) if cleaned else "key"


def _step_error_text(step):
    error = step.get("error")
    if error:
        return _short_text(error, 160)
    result = step.get("result")
    if isinstance(result, dict):
        error = result.get("error") or result.get("message")
        if error:
            return _short_text(error, 160)
    if step.get("status") == "error" and result:
        return _short_text(result, 160)
    return ""


def _step_duration_ms(step):
    value = step.get("duration_ms")
    if value is None:
        value = step.get("duration_seconds")
    if value is None:
        value = step.get("duration")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 1000 and step.get("duration_ms") is None:
        number *= 1000
    return max(0, int(round(number)))


def _step_icon(step):
    return _ACTION_ICONS.get(str(step.get("action") or "").lower(), "\u23F3")


def _step_label(step):
    action = str(step.get("action") or "").lower()
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    if action == "launch":
        target = params.get("query") or params.get("path") or params.get("command") or params.get("app")
        return f"Launch {_title_target(target, 'Application')}"
    if action == "wait":
        return f"Wait {_seconds_label(params.get('seconds', 1))}"
    if action == "type":
        return f"Type {_quoted(params.get('text', ''))}"
    if action in {"key", "hotkey", "press"}:
        return f"Press {_keys_label(params.get('keys', params.get('key', [])))}"
    if action == "click":
        if params.get("x") is not None and params.get("y") is not None:
            return f"Click {params.get('x')}, {params.get('y')}"
        return "Click"
    if action == "mouse_move":
        if params.get("x") is not None and params.get("y") is not None:
            return f"Move mouse to {params.get('x')}, {params.get('y')}"
        return "Move mouse"
    if action == "mouse_scroll":
        amount = params.get("amount", params.get("clicks", params.get("dy", "")))
        return f"Scroll {amount}" if amount != "" else "Scroll"
    if action == "mouse_drag":
        return "Drag mouse"
    if action == "ocr_find":
        text = params.get("text") or params.get("query") or params.get("needle")
        return f"Find text {_quoted(text)}" if text else "Find text on screen"
    if action == "screenshot":
        return "Capture screenshot"
    if action == "telegram_send":
        return "Send Telegram message"
    if action == "finder_click":
        text = params.get("text") or params.get("query") or params.get("target")
        return f"Smart click {_quoted(text)}" if text else "Smart click"
    if action == "finder_type":
        return f"Smart type {_quoted(params.get('text', ''))}"
    return _title_target(action.replace("_", " "), "Step")


def _step_detail_lines(step):
    action = str(step.get("action") or "").lower()
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    lines = []
    if action:
        lines.append(f"Action: {action}")
    if step.get("attempt"):
        lines.append(f"Attempt: {step.get('attempt')}")
    if action == "launch":
        target = params.get("query") or params.get("path") or params.get("command") or params.get("app")
        if target:
            lines.append(f"Target: {_short_text(target, 96)}")
    elif action == "wait":
        lines.append(f"Duration: {_seconds_label(params.get('seconds', 1))}")
    elif action in {"type", "finder_type"}:
        if params.get("text"):
            lines.append(f"Text: {_short_text(params.get('text'), 96)}")
    elif action in {"key", "hotkey", "press"}:
        lines.append(f"Keys: {_keys_label(params.get('keys', params.get('key', [])))}")
    elif action in {"click", "mouse_move"} and params.get("x") is not None and params.get("y") is not None:
        lines.append(f"Coordinates: {params.get('x')}, {params.get('y')}")
    elif action == "ocr_find":
        text = params.get("text") or params.get("query") or params.get("needle")
        if text:
            lines.append(f"Search text: {_short_text(text, 96)}")
    elif action == "telegram_send":
        text = params.get("message") or params.get("text")
        if text:
            lines.append(f"Message: {_short_text(text, 96)}")
    error = _step_error_text(step)
    if error:
        lines.append(f"Error: {error}")
    result = step.get("result")
    if isinstance(result, dict) and not error:
        status = result.get("status") or result.get("message")
        if status:
            lines.append(f"Result: {_short_text(status, 96)}")
    if not lines:
        lines.append("No additional details.")
    return lines


def _ui_step_status(step):
    status = str(step.get("status") or "pending").lower()
    if status == "ok":
        return "done"
    if status in {"running", "error", "pending", "stopped"}:
        return status
    if status in {"queued", "planning"}:
        return "pending"
    return status or "pending"


def _timeline_step(step):
    item = {
        "index": int(step.get("index", 0)),
        "icon": _step_icon(step),
        "label": _step_label(step),
        "status": _ui_step_status(step),
        "raw_status": step.get("status") or "pending",
        "details": _step_detail_lines(step),
    }
    duration_ms = _step_duration_ms(step)
    if duration_ms is not None:
        item["duration_ms"] = duration_ms
    error = _step_error_text(step)
    if error:
        item["error"] = error
    return item


def _goal_progress(steps):
    total = len(steps)
    running = next((step for step in steps if step.get("status") == "running"), None)
    if running:
        current = int(running.get("index", 0)) + 1
    else:
        current = sum(1 for step in steps if step.get("status") in {"done", "error", "stopped"})
    return {"current": min(current, total), "total": total}


def _current_step_label(steps):
    for step in steps:
        if step.get("status") == "running":
            return step.get("label", "")
    for step in steps:
        if step.get("status") == "pending":
            return step.get("label", "")
    return steps[-1].get("label", "") if steps else ""


def _status_text(status, progress):
    total = progress.get("total", 0)
    current = progress.get("current", 0)
    if status == "queued":
        return "Queued"
    if status == "planning":
        return "Planning"
    if status == "running":
        return f"Running step {current}/{total}" if total else "Running"
    if status == "failed":
        return f"Failed at step {current}/{total}" if total else "Failed"
    if status == "completed":
        return f"Completed {total}/{total}" if total else "Completed"
    if status == "stopped":
        return f"Stopped at step {current}/{total}" if total else "Stopped"
    if status == "stopping":
        return "Stopping"
    return "Idle"


def _timeline_from_goal(goal):
    steps = [_timeline_step(step) for step in goal.get("steps", [])]
    progress = _goal_progress(steps)
    started_at = goal.get("started_at")
    finished_at = goal.get("finished_at")
    duration_seconds = 0
    if started_at:
        duration_seconds = round((finished_at or _now()) - started_at, 2)
    status = goal.get("status", "idle")
    return {
        "goal_id": goal.get("goal_id") or goal.get("id"),
        "goal": goal.get("goal", ""),
        "status": status,
        "status_icon": _STATUS_ICONS.get(status, "\U0001F7E2"),
        "status_text": _status_text(status, progress),
        "progress": progress,
        "current_step": _current_step_label(steps),
        "duration_seconds": duration_seconds,
        "completed": sum(1 for step in steps if step.get("status") == "done"),
        "failed": sum(1 for step in steps if step.get("status") == "error"),
        "steps": steps,
        "log": list(goal.get("log") or []),
        "steers": list(goal.get("steering_history") or []),
        "steer_pending": len(goal.get("steering_queue") or []),
        "error": goal.get("error"),
        "created_at": goal.get("created_at"),
        "started_at": goal.get("started_at"),
        "finished_at": goal.get("finished_at"),
    }


def _goal_complete_payload(goal):
    timeline = _timeline_from_goal(goal)
    return {
        "status": timeline["status"],
        "completed": timeline["completed"],
        "failed": timeline["failed"],
        "total": timeline["progress"]["total"],
        "duration": timeline["duration_seconds"],
    }


def _put_goal_event(client_queue, event):
    try:
        client_queue.put_nowait(event)
        return True
    except queue.Full:
        try:
            client_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            client_queue.put_nowait(event)
            return True
        except queue.Full:
            return False


def _emit_goal_event(goal_id, event_type, data):
    dead = []
    event = None
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None
        sequence = int(goal.get("event_seq") or 0) + 1
        goal["event_seq"] = sequence
        event = {
            "id": sequence,
            "event": event_type,
            "data": data,
            "created_at": _now(),
        }
        events = goal.setdefault("events", [])
        events.append(event)
        if len(events) > MAX_GOAL_EVENTS:
            del events[:-MAX_GOAL_EVENTS]
        subscribers = list(goal.setdefault("subscribers", set()))
    for client_queue in subscribers:
        if not _put_goal_event(client_queue, event):
            dead.append(client_queue)
    if dead:
        with _GOALS_LOCK:
            goal = _GOALS.get(goal_id)
            if goal:
                subscribers = goal.setdefault("subscribers", set())
                for client_queue in dead:
                    subscribers.discard(client_queue)
    return event


def _emit_goal_timeline(goal_id):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None
        payload = _timeline_from_goal(goal)
    return _emit_goal_event(goal_id, "timeline", payload)


def _log_entry(goal_id, level, message, icon=None):
    ts = _now()
    entry = {
        "time": _clock(ts),
        "timestamp": ts,
        "level": str(level or "info"),
        "icon": icon or _LOG_ICONS.get(str(level or "info"), "\U0001F7E2"),
        "message": _short_text(message, 260),
    }
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return entry
        log = goal.setdefault("log", [])
        log.append(entry)
        if len(log) > MAX_GOAL_LOG_ENTRIES:
            del log[:-MAX_GOAL_LOG_ENTRIES]
        goal["updated_at"] = ts
    _emit_goal_event(goal_id, "log", entry)
    return entry


def _eventsource_authorized():
    try:
        import auth as auth_module
    except Exception:
        auth_module = None
    auth_enabled = bool(getattr(auth_module, "AUTH_ENABLED", False))
    auth_token = getattr(auth_module, "AUTH_TOKEN", "") if auth_module else ""
    if not auth_enabled:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and secrets.compare_digest(auth_header[7:], auth_token or ""):
        return True
    provided = request.args.get("token") or request.args.get("access_token") or request.args.get("bearer") or ""
    if provided.startswith("Bearer "):
        provided = provided[7:]
    return bool(provided and secrets.compare_digest(provided, auth_token or ""))


def _coagent_request(method, path, data=None, auth_header=None, timeout=30):
    headers = {"Accept": "application/json"}
    body = None
    if method.upper() != "GET":
        headers["Content-Type"] = "application/json"
        body = json.dumps(data or {}).encode("utf-8")
    token = _auth_header(auth_header)
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{_self_port()}{path}",
        data=body,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            if not text:
                return {"status": "ok", "status_code": getattr(response, "status", 200)}
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"text": text}
            if isinstance(payload, dict):
                payload.setdefault("status_code", getattr(response, "status", 200))
            return payload
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"error": text or str(exc)}
        if isinstance(payload, dict):
            payload.setdefault("error", payload.get("error") or f"HTTP {exc.code}")
            payload["status_code"] = exc.code
        return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "status_code": 0}


def _first_json_array(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty agent response")
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "[":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    raise ValueError("no JSON step list found")


def _first_json_value(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty agent response")
    fenced = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    raise ValueError("no JSON object or array found")


def _fallback_steps(goal):
    """Conservative local fallback when the agent gateway cannot decompose."""
    text = str(goal or "")
    lowered = text.lower()
    steps = []
    open_match = re.search(r"\b(open|launch|start)\s+([a-z0-9_. -]+)", lowered)
    if open_match:
        query = open_match.group(2).split(",")[0].strip()
        query = re.split(r"\b(search|send|type|click|wait)\b", query)[0].strip()
        if query:
            steps.append({"action": "launch", "params": {"query": query}})
            steps.append({"action": "wait", "params": {"seconds": 3}})
    search_match = re.search(r"\bsearch(?: for)?\s+['\"]?([^,'\"]+)", text, re.IGNORECASE)
    if search_match:
        steps.append({"action": "type", "params": {"text": search_match.group(1).strip()}})
        steps.append({"action": "key", "params": {"keys": ["enter"]}})
        steps.append({"action": "wait", "params": {"seconds": 2}})
    send_match = re.search(r"\bsend(?: message)?\s+['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    if send_match:
        steps.append({"action": "type", "params": {"text": send_match.group(1)}})
        steps.append({"action": "key", "params": {"keys": ["enter"]}})
    if not steps:
        steps = [{"action": "screenshot", "params": {}}]
    return steps


def _goal_requires_screenshot(goal):
    text = str(goal or "").lower()
    return bool(re.search(r"\b(screen\s*shot|screenshot|capture|screen|observe|ocr|read)\b", text))


def _clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_steps(raw_steps, max_steps):
    if not isinstance(raw_steps, list):
        raise ValueError("steps must be a list")
    normalized = []
    for raw in raw_steps[:max_steps]:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action") or raw.get("type") or "").strip().lower()
        params = raw.get("params", {})
        if not isinstance(params, dict):
            params = {}
        if action:
            normalized.append({"action": action, "params": params})
    if not normalized:
        raise ValueError("no executable steps returned")
    return normalized


_BATCH_TYPE_TO_ACTION = {
    "sleep": "wait",
    "wait": "wait",
    "key/press": "key",
    "key": "key",
    "hotkey": "key",
    "press": "key",
    "key/type": "type",
    "type": "type",
    "mouse/click": "click",
    "click": "click",
    "mouse/move": "mouse_move",
    "mouse/scroll": "mouse_scroll",
    "mouse/drag": "mouse_drag",
    "ocr/find": "ocr_find",
    "ocr_find": "ocr_find",
    "screen/base64": "screenshot",
    "screen/screenshot": "screenshot",
    "screenshot": "screenshot",
    "process/start": "launch",
    "app/open": "launch",
    "launch": "launch",
    "telegram/send": "telegram_send",
    "telegram_send": "telegram_send",
    "finder/click": "finder_click",
    "finder/type": "finder_type",
}

_ACTION_TO_BATCH_TYPE = {
    "wait": "sleep",
    "key": "key/press",
    "hotkey": "key/press",
    "press": "key/press",
    "type": "key/type",
    "click": "mouse/click",
    "mouse_move": "mouse/move",
    "mouse_scroll": "mouse/scroll",
    "mouse_drag": "mouse/drag",
    "ocr_find": "ocr/find",
    "screenshot": "screen/base64",
    "launch": "process/start",
    "telegram_send": "telegram/send",
    "finder_click": "finder/click",
    "finder_type": "finder/type",
}


def _normalize_batch_type(value):
    normalized = str(value or "").strip().lower().replace("_", "/")
    normalized = re.sub(r"\s+", "", normalized)
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def _batch_action_to_step(raw):
    if not isinstance(raw, dict):
        raise ValueError("each action must be an object")
    raw_type = raw.get("type") or raw.get("action")
    public_type = _normalize_batch_type(raw_type)
    action = _BATCH_TYPE_TO_ACTION.get(public_type)
    if not action:
        raise ValueError(f"unsupported action type: {raw_type}")
    data = raw.get("data", raw.get("params", {}))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("action data must be an object")
    data = deepcopy(data)
    if action == "wait":
        duration = raw.get("duration", data.get("duration", data.get("seconds", 1)))
        try:
            seconds = max(0.0, min(float(duration), 300.0))
        except (TypeError, ValueError):
            seconds = 1.0
        return {"action": "wait", "params": {"seconds": seconds}}, {"type": "sleep", "duration": seconds}
    public_type = _ACTION_TO_BATCH_TYPE.get(action, public_type)
    return {"action": action, "params": data}, {"type": public_type, "data": data}


def _normalize_batch_actions(raw_actions, max_actions):
    if not isinstance(raw_actions, list):
        raise ValueError("actions must be a list")
    public_actions = []
    steps = []
    for raw in raw_actions[:max_actions]:
        step, public = _batch_action_to_step(raw)
        steps.append(step)
        public_actions.append(public)
    if not steps:
        raise ValueError("no executable actions returned")
    return public_actions, steps


def _decompose_goal(goal, max_steps, auth_header, agent=None, model=None):
    # First try the agent gateway (Codex CLI)
    prompt = (
        "Break this goal into step-by-step actions using available CoAgent API endpoints. "
        "Return only a JSON array. Each item must be an object with action and params. "
        "Allowed actions: launch, wait, ocr_find, click, type, key, screenshot, "
        "telegram_send, finder_click, finder_type. "
        "For launch: use params {\"query\": \"app_name\"} (e.g. {\"query\": \"telegram\"}, {\"query\": \"notepad\"}, {\"query\": \"brave\"}). "
        "Use $prev.x and $prev.y when a "
        "click should use the previous OCR or finder result.\n\n"
        f"Goal: {goal}\n"
        f"Maximum steps: {max_steps}"
    )
    payload = {
        "prompt": prompt,
        "agent": agent or "codex",
        "model": model,
        "timeout": 60,
        "workdir": str(COAGENT_DIR),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    try:
        response = _coagent_request("POST", "/agent/exec", payload, auth_header=auth_header, timeout=90)
        output = ""
        if isinstance(response, dict):
            output = response.get("output") or response.get("stdout") or response.get("text") or ""
        if output:
            try:
                steps = _normalize_steps(_first_json_array(output), max_steps)
                return steps, {"source": "agent_gateway", "agent_response": response}
            except Exception as exc:
                _console(f"[copilot_enhanced] agent parse failed: {type(exc).__name__}: {exc}")
    except Exception as exc:
        _console(f"[copilot_enhanced] agent request failed: {type(exc).__name__}: {exc}")

    # Fallback: use local planner (fast, no external dependency)
    return _local_planner(goal, max_steps), {"source": "local_planner"}


def _local_planner(goal, max_steps):
    """Simple local planner that converts common goals to steps without Codex."""
    import re
    goal_lower = goal.lower()
    steps = []

    # Detect app launch patterns
    app_match = re.search(r'(?:open|launch|start|run)\s+(\w+(?:\s+\w+)?)', goal_lower)
    if app_match:
        app = app_match.group(1)
        # Map common names to search queries
        app_map = {
            "telegram": "telegram",
            "notepad": "notepad",
            "brave": "brave",
            "chrome": "chrome",
            "firefox": "firefox",
            "calculator": "calculator",
            "spotify": "spotify",
            "discord": "discord",
            "explorer": "file explorer",
        }
        query = app_map.get(app, app)
        steps.append({"action": "launch", "params": {"query": query}})
        steps.append({"action": "wait", "params": {"seconds": 3}})
        steps.append({"action": "screenshot", "params": {}})

    # Detect search patterns
    search_match = re.search(r'(?:search|find|look\s+for)\s+(.+?)(?:\s+and\s+|$)', goal_lower)
    search_target = search_match.group(1).strip() if search_match else None
    
    # Detect "say X" or "send X" or "type X"
    say_match = re.search(r'(?:say|type|send|write|enter)\s+(.+?)(?:\s+to\s+|$)', goal_lower)
    type_text = say_match.group(1).strip().strip('"').strip("'") if say_match else None

    # Detect "click on X" or "press X"
    click_match = re.search(r'(?:click|press|tap|hit)\s+(?:on\s+)?(.+)', goal_lower)
    click_target = click_match.group(1).strip() if click_match else None

    # Construct steps based on detected patterns
    if "telegram" in goal_lower or "discord" in goal_lower:
        if not app_match:
            steps.append({"action": "launch", "params": {"query": "telegram" if "telegram" in goal_lower else "discord"}})
            steps.append({"action": "wait", "params": {"seconds": 5}})

    if search_target:
        steps.append({"action": "finder_click", "params": {"text": "search" if "telegram" in goal_lower else search_target}})
        steps.append({"action": "wait", "params": {"seconds": 1}})
        if type_text:
            steps.append({"action": "finder_type", "params": {"text": type_text}})
            steps.append({"action": "key", "params": {"keys": ["enter"]}})
    elif type_text:
        # Just type the text
        steps.append({"action": "click", "params": {}})
        steps.append({"action": "type", "params": {"text": type_text}})
        steps.append({"action": "key", "params": {"keys": ["enter"]}})

    if click_target and not search_target:
        steps.append({"action": "finder_click", "params": {"text": click_target}})

    # If no patterns matched, return a generic sequence
    if not steps:
        steps = [
            {"action": "screenshot", "params": {}},
            {"action": "ocr_find", "params": {"text": goal}},
        ]

    # Cap at max_steps
    return steps[:max_steps]


def _plan_batch_actions(
    goal,
    context,
    max_actions,
    auth_header,
    agent=None,
    model=None,
    provider=None,
    base_url=None,
    api_key=None,
):
    prompt = (
        "Create a speculative multi-action plan for Hermes CoAgent. Return only JSON with this shape: "
        '{"reasoning":"short explanation","actions":[{"type":"key/press","data":{"keys":["win","r"]}}]}. '
        "Generate 5-10 actions when the goal needs them, fewer when the goal is small. "
        "Allowed action types: sleep, key/press, key/type, mouse/click, mouse/move, mouse/scroll, "
        "mouse/drag, process/start, app/open, ocr/find, screen/base64, telegram/send, finder/click, finder/type. "
        "Use action data matching the target endpoint payload. For sleep, use duration seconds.\n\n"
        f"Goal: {goal}\n"
        f"Context: {context or 'No additional context provided.'}\n"
        f"Maximum actions: {max_actions}"
    )
    payload = {
        "prompt": prompt,
        "agent": agent,
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "timeout": 120,
        "workdir": str(COAGENT_DIR),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    response = _coagent_request("POST", "/agent/exec", payload, auth_header=auth_header, timeout=150)
    output = ""
    if isinstance(response, dict):
        output = response.get("output") or response.get("stdout") or response.get("text") or ""
    try:
        parsed = _first_json_value(output)
        if isinstance(parsed, dict):
            reasoning = str(parsed.get("reasoning") or parsed.get("summary") or "")
            raw_actions = parsed.get("actions")
        else:
            reasoning = ""
            raw_actions = parsed
        public_actions, steps = _normalize_batch_actions(raw_actions, max_actions)
        return public_actions, steps, {
            "source": "agent_gateway",
            "reasoning": reasoning,
            "agent_response": response,
        }
    except Exception as exc:
        fallback_actions, steps = _normalize_batch_actions(_fallback_steps(goal), max_actions)
        return fallback_actions, steps, {
            "source": "fallback",
            "reasoning": "Used local fallback planner because agent planning did not return executable JSON.",
            "warning": f"agent batch planning failed: {type(exc).__name__}: {exc}",
            "agent_response": response,
        }


def _lookup_path(data, path):
    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except Exception:
                return None
        else:
            return None
    return value


def _resolve_refs(value, previous):
    if isinstance(value, str) and value.startswith("$prev."):
        resolved = _lookup_path(previous or {}, value[6:])
        return value if resolved is None else resolved
    if isinstance(value, str) and "$prev." in value:
        def repl(match):
            resolved = _lookup_path(previous or {}, match.group(1))
            return match.group(0) if resolved is None else str(resolved)
        return re.sub(r"\$prev\.([A-Za-z0-9_.]+)", repl, value)
    if isinstance(value, list):
        return [_resolve_refs(item, previous) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_refs(item, previous) for key, item in value.items()}
    return value


def _prev_from_result(result):
    if not isinstance(result, dict):
        return {}
    matches = result.get("matches")
    if isinstance(matches, list) and matches:
        first = matches[0] if isinstance(matches[0], dict) else {}
        center = first.get("center") if isinstance(first.get("center"), dict) else {}
        bounds = first.get("bounds") if isinstance(first.get("bounds"), dict) else {}
        x = center.get("x")
        y = center.get("y")
        if x is None and bounds:
            x = int(bounds.get("x", 0)) + int(bounds.get("width", 0)) // 2
        if y is None and bounds:
            y = int(bounds.get("y", 0)) + int(bounds.get("height", 0)) // 2
        return {"x": x, "y": y, "match": first, "result": result}
    at = result.get("at") if isinstance(result.get("at"), dict) else {}
    if at:
        return {"x": at.get("x"), "y": at.get("y"), "result": result}
    for key in ("x", "desktop_x"):
        if key in result:
            return {"x": result.get(key), "y": result.get("y") or result.get("desktop_y"), "result": result}
    return {"result": result}


def _telegram_send(params):
    try:
        from routes_telegram import CONFIG_FILE, _load_config, _resolve_target_chat, _send_telegram_message
    except Exception as exc:
        return {"error": f"telegram helper unavailable: {exc}"}
    config = _load_config()
    if not config:
        return {"error": "telegram not configured"}
    bot_token = config.get("bot_token")
    chat_id = params.get("chat_id") or _resolve_target_chat(config)
    text = params.get("message") or params.get("text") or ""
    if not bot_token or not chat_id:
        return {"error": "telegram bot_token or chat_id missing", "config_file": str(CONFIG_FILE)}
    ok, response = _send_telegram_message(bot_token, chat_id, text)
    return {"status": "sent", "response": response} if ok else {"error": str(response)}


def _local_appdata_path(*parts):
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return str(Path(root).joinpath(*parts))
    return str(Path.home().joinpath("AppData", "Local", *parts))


def _run_step(step, previous, stop_event, auth_header):
    action = step.get("action", "")
    params = _resolve_refs(deepcopy(step.get("params") or {}), previous)
    if stop_event.is_set():
        return {"status": "stopped", "result": {"error": "goal stopped"}}
    if action == "wait":
        seconds = max(0.0, min(float(params.get("seconds", 1)), 300.0))
        if stop_event.wait(seconds):
            return {"status": "stopped", "result": {"error": "goal stopped during wait"}}
        return {"status": "ok", "result": {"status": "ok", "slept": seconds}}
    if action == "launch":
        query = params.get("query") or params.get("path") or params.get("command") or params.get("app")
        if not query:
            return {"status": "error", "result": {"error": "launch target is required"}}
        # Resolve common app names to known paths
        _APP_ALIASES = {
            "telegram": _local_appdata_path("Telegram Desktop", "Telegram.exe"),
            "chrome": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            "brave": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "terminal": "cmd.exe",
            "powershell": "powershell.exe",
            "discord": f"{_local_appdata_path('Discord', 'Update.exe')} --processStart Discord.exe",
            "outlook": r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
            "code": _local_appdata_path("Programs", "Microsoft VS Code", "Code.exe"),
            "vscode": _local_appdata_path("Programs", "Microsoft VS Code", "Code.exe"),
        }
        query = str(query).strip()
        resolved = _APP_ALIASES.get(query.lower(), query)
        result = _coagent_request("POST", "/process/start", {"path": resolved}, auth_header=auth_header)
        if isinstance(result, dict) and result.get("error"):
            result = _coagent_request("POST", "/app/open", {"path": query}, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "click":
        result = _coagent_request("POST", "/mouse/click", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "mouse_move":
        result = _coagent_request("POST", "/mouse/move", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "mouse_scroll":
        result = _coagent_request("POST", "/mouse/scroll", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "mouse_drag":
        result = _coagent_request("POST", "/mouse/drag", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "type":
        result = _coagent_request("POST", "/key/type", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action in {"key", "hotkey", "press"}:
        keys = params.get("keys", params.get("key", []))
        if isinstance(keys, str):
            keys = [part for part in keys.replace("+", " ").split() if part]
        result = _coagent_request("POST", "/key/press", {"keys": keys}, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "ocr_find":
        result = _coagent_request("POST", "/ocr/find", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "screenshot":
        result = _coagent_request("GET", "/screen/base64", auth_header=auth_header, timeout=30)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "telegram_send":
        result = _coagent_request("POST", "/telegram/send", params, auth_header=auth_header)
        if isinstance(result, dict) and result.get("status_code") == 404:
            result = _telegram_send(params)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "finder_click":
        result = _coagent_request("POST", "/finder/click", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    if action == "finder_type":
        result = _coagent_request("POST", "/finder/type", params, auth_header=auth_header)
        return {"status": "error" if result.get("error") else "ok", "result": result}
    return {"status": "error", "result": {"error": f"Unknown action: {action}"}}


def _snapshot_goal(goal):
    internal = {"thread", "stop_event", "subscribers", "events", "event_seq"}
    payload = {key: value for key, value in goal.items() if key not in internal}
    payload["completed"] = sum(1 for step in payload.get("steps", []) if step.get("status") == "ok")
    payload["failed"] = sum(1 for step in payload.get("steps", []) if step.get("status") == "error")
    started_at = payload.get("started_at") or payload.get("created_at") or _now()
    payload["duration_seconds"] = round((payload.get("finished_at") or _now()) - started_at, 2)
    return payload


def _push_completed_ring(goal_id, step_record):
    """Ring-buffer track a just-completed step so rollback can undo it."""
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return
        ring = goal.setdefault("completed_ring", [])
        ring.append({
            "index": step_record.get("index"),
            "action": step_record.get("action"),
            "params": deepcopy(step_record.get("params") or {}),
            "result": deepcopy(step_record.get("result") or {}),
            "duration_ms": step_record.get("duration_ms"),
            "recorded_at": _now(),
        })
        if len(ring) > MAX_COMPLETED_RING:
            del ring[:-MAX_COMPLETED_RING]


def _drain_steer_queue(goal_id):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return []
        pending = list(goal.get("steering_queue") or [])
        goal["steering_queue"] = []
        return pending


def _record_steer_history(goal_id, entry):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return
        history = goal.setdefault("steering_history", [])
        history.append(entry)
        if len(history) > MAX_STEER_HISTORY:
            del history[:-MAX_STEER_HISTORY]


def _undo_step_action(auth_header, step_record):
    """Best-effort inverse for a completed step. Uses routes_undo when possible."""
    action = str(step_record.get("action") or "").lower()
    params = step_record.get("params") or {}
    result = step_record.get("result") if isinstance(step_record.get("result"), dict) else {}
    try:
        if action in {"click", "finder_click"}:
            return {"status": "skipped", "reason": "click actions are not automatically reversible"}
        if action == "type":
            text = str(params.get("text", ""))
            if text:
                return _coagent_request(
                    "POST",
                    "/key/press",
                    {"keys": ["backspace"] * min(len(text), 200)},
                    auth_header=auth_header,
                )
            return {"status": "skipped", "reason": "no text to erase"}
        if action == "mouse_scroll":
            clicks = params.get("clicks", params.get("amount", params.get("dy", 0)))
            try:
                clicks = int(clicks)
            except (TypeError, ValueError):
                clicks = 0
            return _coagent_request("POST", "/mouse/scroll", {"clicks": -clicks}, auth_header=auth_header)
        if action == "mouse_drag":
            return _coagent_request(
                "POST",
                "/mouse/drag",
                {
                    "x1": params.get("x2"),
                    "y1": params.get("y2"),
                    "x2": params.get("x1"),
                    "y2": params.get("y1"),
                },
                auth_header=auth_header,
            )
        if action in {"key", "hotkey", "press"}:
            return {"status": "skipped", "reason": "key press cannot be inverted"}
        if action == "launch":
            return {"status": "skipped", "reason": "launched app must be closed manually"}
        return {"status": "skipped", "reason": f"no inverse defined for {action}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _rollback_last_completed(goal_id, auth_header):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return {"error": "goal not found"}
        ring = goal.get("completed_ring") or []
        if not ring:
            return {"error": "no completed step to roll back"}
        step_record = ring.pop()
        index = step_record.get("index")
        steps = goal.get("steps") or []
        if isinstance(index, int) and 0 <= index < len(steps):
            steps[index]["status"] = "pending"
            steps[index].pop("result", None)
            steps[index].pop("duration_ms", None)
            steps[index].pop("duration", None)
    outcome = _undo_step_action(auth_header, step_record)
    return {
        "rolled_back_index": step_record.get("index"),
        "action": step_record.get("action"),
        "result": outcome,
    }


def _revise_plan(goal_id, goal_text, instructions, remaining_index, max_steps, auth_header, agent, model):
    """Re-plan the remaining steps folding in accumulated steering instructions."""
    combined = str(goal_text or "")
    if instructions:
        formatted = "\n".join(f"- {text}" for text in instructions)
        combined = (
            f"{combined}\n\nOperator corrections to fold in (do not discard already-completed steps):\n{formatted}"
        )
    try:
        new_steps, meta = _decompose_goal(combined, max_steps, auth_header, agent=agent, model=model)
    except Exception as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}
    remaining_slots = max(1, max_steps - remaining_index)
    new_steps = list(new_steps)[:remaining_slots]
    if not new_steps:
        return False, {"error": "revised plan returned no steps"}
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return False, {"error": "goal not found"}
        steps = goal.get("steps") or []
        kept = steps[:remaining_index]
        appended = [
            {
                "index": remaining_index + offset,
                "action": step["action"],
                "params": step.get("params", {}),
                "status": "pending",
            }
            for offset, step in enumerate(new_steps)
        ]
        goal["steps"] = kept + appended
        goal["decomposition"] = meta
        goal["updated_at"] = _now()
    return True, {"revised_from": remaining_index, "new_steps": len(new_steps), "source": meta.get("source")}


def _save_goal_update(goal_id, **updates):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None
        goal.update(updates)
        goal["updated_at"] = _now()
        return goal


def _complete_goal(goal_id, status, error=None):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None
        goal["status"] = status
        goal["finished_at"] = _now()
        goal["updated_at"] = goal["finished_at"]
        if error:
            goal["error"] = error
        payload = _goal_complete_payload(goal)
    _emit_goal_timeline(goal_id)
    _emit_goal_event(goal_id, "goal_complete", payload)
    return payload


def _run_goal(goal_id, auth_header):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return
        goal["status"] = "planning"
        goal["started_at"] = _now()
        goal["updated_at"] = goal["started_at"]
        stop_event = goal["stop_event"]
        goal_text = goal["goal"]
        max_steps = goal["max_steps"]
        agent = goal.get("agent")
        model = goal.get("model")
    _log_entry(goal_id, "planning", f'Planning goal: "{goal_text}"', "\U0001F7E1")
    _emit_goal_event(goal_id, "goal_status", {"status": "planning", "icon": _STATUS_ICONS["planning"]})
    _emit_goal_timeline(goal_id)
    try:
        steps, decomposition = _decompose_goal(goal_text, max_steps, auth_header, agent=agent, model=model)
        with _GOALS_LOCK:
            goal = _GOALS[goal_id]
            goal["decomposition"] = decomposition
            goal["steps"] = [
                {"index": index, "action": step["action"], "params": step.get("params", {}), "status": "pending"}
                for index, step in enumerate(steps)
            ]
            goal["status"] = "running"
            goal["updated_at"] = _now()
        source = str((decomposition or {}).get("source") or "planner")
        if source == "agent_gateway":
            _log_entry(goal_id, "info", f"Codex returned {len(steps)} steps", "\U0001F7E2")
        else:
            warning = (decomposition or {}).get("warning")
            _log_entry(goal_id, "warn", f"Planner returned {len(steps)} fallback steps", "\U0001F7E1")
            if warning:
                _log_entry(goal_id, "warn", warning, "\U0001F7E1")
        _emit_goal_event(goal_id, "steps_planned", {"total": len(steps)})
        _emit_goal_event(goal_id, "goal_status", {"status": "running", "icon": _STATUS_ICONS["running"]})
        _emit_goal_timeline(goal_id)
        previous = {}
        failed = False
        failed_record = None
        index = 0
        while True:
            with _GOALS_LOCK:
                current_steps = list(_GOALS[goal_id].get("steps") or [])
            if index >= len(current_steps):
                break
            step = {"action": current_steps[index]["action"], "params": current_steps[index].get("params", {})}
            if stop_event.is_set():
                _log_entry(goal_id, "warn", f"Goal stopped before step {index + 1}", "\U0001F7E1")
                _complete_goal(goal_id, "stopped")
                return
            pending_steers = _drain_steer_queue(goal_id)
            if pending_steers:
                instructions = [str(s.get("instruction") or "").strip() for s in pending_steers]
                instructions = [text for text in instructions if text]
                for entry in pending_steers:
                    text = str(entry.get("instruction") or "").strip()
                    label = _short_text(text, 120) or "(empty instruction)"
                    _log_entry(goal_id, "info", f"Steer applied: {label}", "\U0001F9ED")
                    _emit_goal_event(goal_id, "steer", {
                        "index": index,
                        "instruction": text,
                        "rollback": bool(entry.get("rollback")),
                        "applied_at": _now(),
                    })
                ok, meta = _revise_plan(
                    goal_id, goal_text, instructions, index, max_steps, auth_header, agent, model
                )
                if ok:
                    _log_entry(
                        goal_id,
                        "planning",
                        f"Plan revised from step {index + 1} ({meta.get('new_steps')} new steps)",
                        "\U0001F7E1",
                    )
                    _emit_goal_event(goal_id, "steps_planned", {"total": index + int(meta.get("new_steps") or 0)})
                    _emit_goal_timeline(goal_id)
                    continue
                else:
                    warning = meta.get("error") or "revise failed"
                    _log_entry(goal_id, "warn", f"Plan revision failed: {warning}", "\U0001F7E1")
            start = _now()
            final_record = None
            label = _step_label({"index": index, "action": step["action"], "params": step.get("params", {})})
            icon = _step_icon(step)
            for attempt in (1, 2):
                with _GOALS_LOCK:
                    goal = _GOALS[goal_id]
                    goal["steps"][index].update({"status": "running", "attempt": attempt})
                    goal["updated_at"] = _now()
                if attempt == 1:
                    _log_entry(goal_id, "action", label, icon)
                    _emit_goal_event(goal_id, "step_start", {"index": index, "label": label, "icon": icon})
                    _emit_goal_timeline(goal_id)
                else:
                    _log_entry(goal_id, "warn", f"Retrying {label}", "\U0001F7E1")
                    _emit_goal_event(goal_id, "step_retry", {"index": index, "label": label, "attempt": attempt})
                outcome = _run_step(step, previous, stop_event, auth_header)
                duration = round(_now() - start, 3)
                result = outcome.get("result", {})
                final_record = {
                    "index": index,
                    "action": step["action"],
                    "params": step.get("params", {}),
                    "status": outcome.get("status", "error"),
                    "result": result,
                    "duration": duration,
                    "duration_ms": int(round(duration * 1000)),
                    "attempt": attempt,
                }
                if final_record["status"] in {"ok", "stopped"}:
                    break
                error_text = _step_error_text(final_record) or "Step failed"
                if attempt == 1:
                    _log_entry(goal_id, "warn", f"{label} failed, retrying: {error_text}", "\U0001F7E1")
                time.sleep(0.4)
            if (
                final_record
                and final_record.get("status") == "error"
                and step.get("action") == "screenshot"
                and not _goal_requires_screenshot(goal_text)
            ):
                result = final_record.get("result") if isinstance(final_record.get("result"), dict) else {}
                final_record["status"] = "ok"
                final_record["optional_warning"] = _step_error_text(final_record) or "Screenshot unavailable"
                final_record["result"] = {
                    **result,
                    "status": "skipped",
                    "warning": final_record["optional_warning"],
                    "optional": True,
                }
            with _GOALS_LOCK:
                goal = _GOALS[goal_id]
                goal["steps"][index].update(final_record)
                goal["updated_at"] = _now()
            if final_record["status"] == "ok":
                previous = _prev_from_result(final_record.get("result") or {})
                _push_completed_ring(goal_id, final_record)
                _log_entry(goal_id, "success", f"{label} completed in {final_record['duration_ms']} ms", "\u2705")
                _emit_goal_event(
                    goal_id,
                    "step_complete",
                    {"index": index, "status": "ok", "duration_ms": final_record["duration_ms"], "label": label},
                )
                _emit_goal_timeline(goal_id)
                index += 1
                continue
            if final_record["status"] == "stopped":
                _log_entry(goal_id, "warn", f"Stopped during {label}", "\U0001F7E1")
                _emit_goal_event(goal_id, "step_error", {"index": index, "error": "Goal stopped", "label": label})
                _complete_goal(goal_id, "stopped")
                return
            failed = True
            failed_record = final_record
            error_text = _step_error_text(final_record) or "Step failed"
            _log_entry(goal_id, "error", f"{label} failed: {error_text}", "\u274C")
            _emit_goal_event(goal_id, "step_error", {"index": index, "error": error_text, "label": label})
            _emit_goal_timeline(goal_id)
            break
        with _GOALS_LOCK:
            total_steps = len(_GOALS[goal_id].get("steps") or [])
        if failed:
            error_text = _step_error_text(failed_record or {}) or "Goal failed"
            _log_entry(goal_id, "error", f"Goal failed: {error_text}", "\u274C")
            _complete_goal(goal_id, "failed", error=error_text)
        else:
            _log_entry(goal_id, "success", f"Goal completed: {total_steps} steps", "\u2705")
            _complete_goal(goal_id, "completed")
    except Exception as exc:
        _console(f"[copilot_enhanced] goal {goal_id} failed: {type(exc).__name__}: {exc}")
        message = f"{type(exc).__name__}: {exc}"
        _log_entry(goal_id, "error", f"Goal failed: {message}", "\u274C")
        _complete_goal(goal_id, "failed", error=message)


def _active_goal_count():
    with _GOALS_LOCK:
        return sum(1 for goal in _GOALS.values() if goal.get("status") in {"queued", "planning", "running"})


def _trim_goals():
    with _GOALS_LOCK:
        while len(_GOAL_ORDER) > MAX_STORED_GOALS:
            old_id = _GOAL_ORDER.pop(0)
            goal = _GOALS.get(old_id)
            if goal and goal.get("status") in {"queued", "planning", "running"}:
                _GOAL_ORDER.append(old_id)
                break
            _GOALS.pop(old_id, None)


def _latest_goal(active_only=False):
    with _GOALS_LOCK:
        for goal_id in reversed(_GOAL_ORDER):
            goal = _GOALS.get(goal_id)
            if not goal:
                continue
            if active_only and goal.get("status") not in {"queued", "planning", "running", "stopping"}:
                continue
            return goal
    return None


def _goal_progress_percent(goal):
    if not goal:
        return 0
    timeline = _timeline_from_goal(goal)
    progress = timeline.get("progress") or {}
    total = int(progress.get("total") or 0)
    current = int(progress.get("current") or 0)
    if total <= 0:
        return 100 if timeline.get("status") == "completed" else 0
    return max(0, min(100, int(round((current / total) * 100))))


def _execute_batch_actions(raw_actions, auth_header, max_actions=50, continue_on_error=False):
    public_actions, steps = _normalize_batch_actions(raw_actions, max_actions)
    stop_event = threading.Event()
    previous = {}
    results = []
    completed = 0
    failed = 0
    failed_at = None
    error = ""
    for index, step in enumerate(steps):
        start = _now()
        outcome = _run_step(step, previous, stop_event, auth_header)
        duration = round(_now() - start, 3)
        result = outcome.get("result", {})
        status = outcome.get("status", "error")
        record = {
            "index": index,
            "type": public_actions[index].get("type"),
            "data": public_actions[index].get("data", {}),
            "duration": public_actions[index].get("duration"),
            "status": status,
            "result": result,
            "duration_seconds": duration,
        }
        if record["duration"] is None:
            record.pop("duration", None)
        results.append(record)
        if status == "ok":
            completed += 1
            previous = _prev_from_result(result or {})
            continue
        failed += 1
        failed_at = index if failed_at is None else failed_at
        if isinstance(result, dict):
            error = str(result.get("error") or result)
        else:
            error = str(result)
        if not continue_on_error:
            break
    return {
        "completed": completed,
        "failed": failed,
        "failed_at": failed_at,
        "error": error,
        "results": results,
        "action_count": len(public_actions),
        "continue_on_error": bool(continue_on_error),
    }


@copilot_enhanced_bp.route("/copilot/status", methods=["GET"])
def route_copilot_status():
    with _GOALS_LOCK:
        latest = _latest_goal()
        latest_payload = _snapshot_goal(latest) if latest else None
        return jsonify({
            "status": latest.get("status") if latest else "idle",
            "active_goals": _active_goal_count(),
            "stored_goals": len(_GOALS),
            "latest_goal": latest_payload,
        })


@copilot_enhanced_bp.route("/copilot/timeline", methods=["GET"])
def route_copilot_timeline():
    with _GOALS_LOCK:
        latest = _latest_goal()
        if not latest:
            return jsonify({
                "goal_id": None,
                "goal": "",
                "status": "idle",
                "progress": {"current": 0, "total": 0},
                "steps": [],
                "log": [],
            })
        return jsonify(_timeline_from_goal(latest))


@copilot_enhanced_bp.route("/copilot/progress", methods=["GET"])
def route_copilot_progress():
    with _GOALS_LOCK:
        latest = _latest_goal()
        percent = _goal_progress_percent(latest)
        progress = _timeline_from_goal(latest).get("progress") if latest else {"current": 0, "total": 0}
        return jsonify({
            "goal_id": latest.get("goal_id") if latest else None,
            "status": latest.get("status") if latest else "idle",
            "percent": percent,
            "progress": progress,
        })


@copilot_enhanced_bp.route("/copilot/stop", methods=["POST"])
def route_copilot_stop_latest():
    with _GOALS_LOCK:
        goal = _latest_goal(active_only=True)
        if not goal:
            return jsonify({"error": "no running goal"}), 404
        goal_id = goal["goal_id"]
        goal["stop_event"].set()
        if goal.get("status") in {"queued", "planning", "running"}:
            goal["status"] = "stopping"
        goal["updated_at"] = _now()
    _log_entry(goal_id, "warn", "Stop requested", "\U0001F7E1")
    _emit_goal_event(goal_id, "goal_status", {"status": "stopping", "icon": _STATUS_ICONS["stopping"]})
    _emit_goal_timeline(goal_id)
    with _GOALS_LOCK:
        return jsonify(_snapshot_goal(_GOALS[goal_id]))


@copilot_enhanced_bp.route("/copilot/batch-plan", methods=["POST"])
def route_copilot_batch_plan():
    data = _json_body()
    goal_text = str(data.get("goal") or "").strip()
    if not goal_text:
        return jsonify({"error": "goal is required"}), 400
    context = str(data.get("context") or "")
    max_actions = _clamp_int(data.get("max_actions"), 10, 1, 50)
    auth = _auth_header(request.headers.get("Authorization", ""))
    try:
        actions, _steps, meta = _plan_batch_actions(
            goal_text,
            context,
            max_actions,
            auth,
            agent=data.get("agent"),
            model=data.get("model"),
            provider=data.get("provider"),
            base_url=data.get("base_url"),
            api_key=data.get("api_key"),
        )
        return jsonify({
            "actions": actions,
            "reasoning": meta.get("reasoning", ""),
            "action_count": len(actions),
            "source": meta.get("source"),
            "warning": meta.get("warning"),
        })
    except Exception as exc:
        _console(f"[copilot_enhanced] batch-plan failed: {type(exc).__name__}: {exc}")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@copilot_enhanced_bp.route("/copilot/batch-execute", methods=["POST"])
def route_copilot_batch_execute():
    data = _json_body()
    actions = data.get("actions")
    if not isinstance(actions, list):
        return jsonify({"error": "actions must be a list"}), 400
    max_actions = _clamp_int(data.get("max_actions"), len(actions), 1, 100)
    continue_on_error = str(data.get("continue_on_error", "")).lower() in {"1", "true", "yes", "on"}
    auth = _auth_header(request.headers.get("Authorization", ""))
    try:
        return jsonify(_execute_batch_actions(actions, auth, max_actions=max_actions, continue_on_error=continue_on_error))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        _console(f"[copilot_enhanced] batch-execute failed: {type(exc).__name__}: {exc}")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@copilot_enhanced_bp.route("/copilot/batch-plan-execute", methods=["POST"])
def route_copilot_batch_plan_execute():
    data = _json_body()
    goal_text = str(data.get("goal") or "").strip()
    if not goal_text:
        return jsonify({"error": "goal is required"}), 400
    context = str(data.get("context") or "")
    max_actions = _clamp_int(data.get("max_actions"), 10, 1, 50)
    include_screenshots = str(data.get("include_screenshots", "true")).lower() not in {"0", "false", "no", "off"}
    continue_on_error = str(data.get("continue_on_error", "")).lower() in {"1", "true", "yes", "on"}
    auth = _auth_header(request.headers.get("Authorization", ""))
    before = None
    after = None
    try:
        if include_screenshots:
            before = _coagent_request("GET", "/screen/base64", auth_header=auth, timeout=30)
        actions, _steps, meta = _plan_batch_actions(
            goal_text,
            context,
            max_actions,
            auth,
            agent=data.get("agent"),
            model=data.get("model"),
            provider=data.get("provider"),
            base_url=data.get("base_url"),
            api_key=data.get("api_key"),
        )
        execution = _execute_batch_actions(
            actions,
            auth,
            max_actions=max_actions,
            continue_on_error=continue_on_error,
        )
        if include_screenshots:
            after = _coagent_request("GET", "/screen/base64", auth_header=auth, timeout=30)
        return jsonify({
            "goal": goal_text,
            "plan": {
                "actions": actions,
                "reasoning": meta.get("reasoning", ""),
                "action_count": len(actions),
                "source": meta.get("source"),
                "warning": meta.get("warning"),
            },
            "execution": execution,
            "before_screenshot": before,
            "after_screenshot": after,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        _console(f"[copilot_enhanced] batch-plan-execute failed: {type(exc).__name__}: {exc}")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@copilot_enhanced_bp.route("/copilot/goal", methods=["POST"])
def route_copilot_goal():
    data = _json_body()
    goal_text = str(data.get("goal") or "").strip()
    if not goal_text:
        return jsonify({"error": "goal is required"}), 400
    try:
        max_steps = max(1, min(int(data.get("max_steps", 10)), 50))
    except (TypeError, ValueError):
        max_steps = 10
    if _active_goal_count() >= MAX_CONCURRENT_GOALS:
        return jsonify({"error": "maximum concurrent goals reached", "limit": MAX_CONCURRENT_GOALS}), 429
    goal_id = uuid.uuid4().hex
    stop_event = threading.Event()
    auth = _auth_header(request.headers.get("Authorization", ""))
    record = {
        "id": goal_id,
        "goal_id": goal_id,
        "goal": goal_text,
        "status": "queued",
        "steps": [],
        "log": [],
        "events": [],
        "event_seq": 0,
        "subscribers": set(),
        "steering_queue": [],
        "steering_history": [],
        "completed_ring": [],
        "max_steps": max_steps,
        "created_at": _now(),
        "created_at_iso": _iso(),
        "updated_at": _now(),
        "started_at": None,
        "finished_at": None,
        "agent": data.get("agent") or "codex",
        "model": data.get("model"),
        "stop_event": stop_event,
    }
    thread = threading.Thread(target=_run_goal, args=(goal_id, auth), name=f"copilot-goal-{goal_id[:8]}", daemon=True)
    record["thread"] = thread
    with _GOALS_LOCK:
        _GOALS[goal_id] = record
        _GOAL_ORDER.append(goal_id)
    _log_entry(goal_id, "info", f'Queued goal: "{goal_text}"', "\U0001F7E2")
    thread.start()
    _trim_goals()
    status_code = 202
    return jsonify(_snapshot_goal(record)), status_code


@copilot_enhanced_bp.route("/copilot/goal/<goal_id>", methods=["GET"])
def route_copilot_goal_status(goal_id):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return jsonify({"error": "goal not found", "goal_id": goal_id}), 404
        return jsonify(_snapshot_goal(goal))


@copilot_enhanced_bp.route("/goal/<goal_id>/timeline", methods=["GET"])
@copilot_enhanced_bp.route("/copilot/goal/<goal_id>/timeline", methods=["GET"])
def route_goal_timeline(goal_id):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return jsonify({"error": "goal not found", "goal_id": goal_id}), 404
        return jsonify(_timeline_from_goal(goal))


@copilot_enhanced_bp.route("/copilot/events/<goal_id>", methods=["GET"])
@copilot_enhanced_bp.route("/copilot/goal/<goal_id>/events", methods=["GET"])
@copilot_enhanced_bp.route("/goal/<goal_id>/events", methods=["GET"])
def route_goal_events(goal_id):
    if not _eventsource_authorized():
        return jsonify({"error": "Unauthorized - provide Bearer token"}), 401
    client_queue = queue.Queue(maxsize=100)
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return jsonify({"error": "goal not found", "goal_id": goal_id}), 404
        goal.setdefault("subscribers", set()).add(client_queue)
        initial = _timeline_from_goal(goal)
        terminal = goal.get("status") in _TERMINAL_GOAL_STATUSES
        complete_payload = _goal_complete_payload(goal) if terminal else None

    def generate():
        try:
            yield sse_pack("timeline", initial, retry=1500)
            if complete_payload is not None:
                yield sse_pack("goal_complete", complete_payload)
                return
            while True:
                try:
                    event = client_queue.get(timeout=20)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield sse_pack(event.get("event"), event.get("data"), event_id=event.get("id"))
                if event.get("event") == "goal_complete":
                    return
        finally:
            with _GOALS_LOCK:
                goal = _GOALS.get(goal_id)
                if goal:
                    goal.setdefault("subscribers", set()).discard(client_queue)

    return sse_stream_response(
        stream_with_context(generate()),
        headers={"X-Goal-Id": goal_id},
    )


route_goal_events._hermes_auth_wrapped = True


@copilot_enhanced_bp.route("/copilot/stop/<goal_id>", methods=["POST"])
def route_copilot_goal_stop(goal_id):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return jsonify({"error": "goal not found", "goal_id": goal_id}), 404
        goal["stop_event"].set()
        if goal.get("status") in {"queued", "planning", "running"}:
            goal["status"] = "stopping"
        goal["updated_at"] = _now()
    _log_entry(goal_id, "warn", "Stop requested", "\U0001F7E1")
    _emit_goal_event(goal_id, "goal_status", {"status": "stopping", "icon": _STATUS_ICONS["stopping"]})
    _emit_goal_timeline(goal_id)
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        return jsonify(_snapshot_goal(goal))


def _enqueue_steer(goal_id, instruction, rollback=False, source="operator"):
    text = str(instruction or "").strip()
    if not text:
        return None, "instruction is required"
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None, "goal not found"
        if goal.get("status") in _TERMINAL_GOAL_STATUSES:
            return None, f"goal is {goal.get('status')} and cannot be steered"
        queue_list = goal.setdefault("steering_queue", [])
        if len(queue_list) >= MAX_STEER_QUEUE:
            return None, "steering queue full"
        entry = {
            "id": uuid.uuid4().hex,
            "instruction": text,
            "rollback": bool(rollback),
            "source": source,
            "created_at": _now(),
            "created_at_iso": _iso(),
        }
        queue_list.append(entry)
    _record_steer_history(goal_id, entry)
    _log_entry(goal_id, "info", f"Steer queued: {_short_text(text, 120)}", "\U0001F9ED")
    return entry, None


@copilot_enhanced_bp.route("/goal-runner/<goal_id>/steer", methods=["POST"])
@copilot_enhanced_bp.route("/copilot/goal/<goal_id>/steer", methods=["POST"])
def route_copilot_goal_steer(goal_id):
    data = _json_body() or {}
    instruction = str(data.get("instruction") or data.get("message") or "").strip()
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400
    rollback = str(data.get("rollback", "")).lower() in {"1", "true", "yes", "on"} or data.get("rollback") is True
    source = str(data.get("source") or "operator")
    with _GOALS_LOCK:
        exists = goal_id in _GOALS
    if not exists:
        return jsonify({"error": "goal not found", "goal_id": goal_id}), 404
    rollback_result = None
    if rollback:
        auth = _auth_header(request.headers.get("Authorization", ""))
        rollback_result = _rollback_last_completed(goal_id, auth)
        if rollback_result and rollback_result.get("rolled_back_index") is not None:
            _log_entry(
                goal_id,
                "warn",
                f"Rolled back step {int(rollback_result['rolled_back_index']) + 1} for steer",
                "\U0001F9ED",
            )
            _emit_goal_event(goal_id, "steer_rollback", rollback_result)
    entry, error = _enqueue_steer(goal_id, instruction, rollback=rollback, source=source)
    if error:
        return jsonify({"error": error, "goal_id": goal_id}), 409
    _emit_goal_timeline(goal_id)
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        snapshot = _snapshot_goal(goal) if goal else {}
    return jsonify({
        "goal_id": goal_id,
        "steer": entry,
        "rollback": rollback_result,
        "queued": len(snapshot.get("steering_queue") or []),
        "status": snapshot.get("status"),
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(copilot_enhanced_bp)
    _wrap_registered_blueprint_routes(app, copilot_enhanced_bp.name, require_auth)
    state.copilot_enhanced = {"max_concurrent_goals": MAX_CONCURRENT_GOALS}
