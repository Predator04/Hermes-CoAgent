"""Enhanced multi-step AI copilot goal execution routes."""

import json
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from copy import deepcopy

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes


copilot_enhanced_bp = Blueprint("copilot_enhanced", __name__)

MAX_CONCURRENT_GOALS = 3
MAX_STORED_GOALS = 50
DEFAULT_TIMEOUT_SECONDS = 300

_GOALS = {}
_GOAL_ORDER = []
_GOALS_LOCK = threading.RLock()


def _now():
    return time.time()


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or _now()))


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
        f"http://127.0.0.1:9123{path}",
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
    prompt = (
        "Break this goal into step-by-step actions using available CoAgent API endpoints. "
        "Return only a JSON array. Each item must be an object with action and params. "
        "Allowed actions: launch, wait, ocr_find, click, type, key, screenshot, "
        "telegram_send, finder_click, finder_type. Use $prev.x and $prev.y when a "
        "click should use the previous OCR or finder result.\n\n"
        f"Goal: {goal}\n"
        f"Maximum steps: {max_steps}"
    )
    payload = {
        "prompt": prompt,
        "agent": agent or "codex",
        "model": model,
        "timeout": 120,
        "workdir": str(COAGENT_DIR),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    response = _coagent_request("POST", "/agent/exec", payload, auth_header=auth_header, timeout=150)
    output = ""
    if isinstance(response, dict):
        output = response.get("output") or response.get("stdout") or response.get("text") or ""
    try:
        steps = _normalize_steps(_first_json_array(output), max_steps)
        return steps, {"source": "agent_gateway", "agent_response": response}
    except Exception as exc:
        fallback = _normalize_steps(_fallback_steps(goal), max_steps)
        return fallback, {
            "source": "fallback",
            "warning": f"agent decomposition failed: {type(exc).__name__}: {exc}",
            "agent_response": response,
        }


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
        result = _coagent_request("POST", "/process/start", {"path": query}, auth_header=auth_header)
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
    payload = {key: value for key, value in goal.items() if key not in {"thread", "stop_event"}}
    payload["completed"] = sum(1 for step in payload.get("steps", []) if step.get("status") == "ok")
    payload["failed"] = sum(1 for step in payload.get("steps", []) if step.get("status") == "error")
    payload["duration_seconds"] = round((payload.get("finished_at") or _now()) - payload.get("started_at", _now()), 2)
    return payload


def _save_goal_update(goal_id, **updates):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return None
        goal.update(updates)
        goal["updated_at"] = _now()
        return goal


def _run_goal(goal_id, auth_header):
    with _GOALS_LOCK:
        goal = _GOALS.get(goal_id)
        if not goal:
            return
        goal["status"] = "planning"
        goal["started_at"] = _now()
        stop_event = goal["stop_event"]
        goal_text = goal["goal"]
        max_steps = goal["max_steps"]
        agent = goal.get("agent")
        model = goal.get("model")
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
        previous = {}
        failed = False
        for index, step in enumerate(steps):
            if stop_event.is_set():
                _save_goal_update(goal_id, status="stopped", finished_at=_now())
                return
            start = _now()
            final_record = None
            for attempt in (1, 2):
                with _GOALS_LOCK:
                    goal = _GOALS[goal_id]
                    goal["steps"][index].update({"status": "running", "attempt": attempt})
                    goal["updated_at"] = _now()
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
                    "attempt": attempt,
                }
                if final_record["status"] in {"ok", "stopped"}:
                    break
                time.sleep(0.4)
            with _GOALS_LOCK:
                goal = _GOALS[goal_id]
                goal["steps"][index].update(final_record)
                goal["updated_at"] = _now()
            if final_record["status"] == "ok":
                previous = _prev_from_result(final_record.get("result") or {})
                continue
            if final_record["status"] == "stopped":
                _save_goal_update(goal_id, status="stopped", finished_at=_now())
                return
            failed = True
            break
        _save_goal_update(goal_id, status="failed" if failed else "completed", finished_at=_now())
    except Exception as exc:
        _console(f"[copilot_enhanced] goal {goal_id} failed: {type(exc).__name__}: {exc}")
        _save_goal_update(
            goal_id,
            status="failed",
            finished_at=_now(),
            error=f"{type(exc).__name__}: {exc}",
        )


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
        return jsonify(_snapshot_goal(goal))


def register_routes(app, state, require_auth):
    app.register_blueprint(copilot_enhanced_bp)
    _wrap_registered_blueprint_routes(app, copilot_enhanced_bp.name, require_auth)
    state.copilot_enhanced = {"max_concurrent_goals": MAX_CONCURRENT_GOALS}
