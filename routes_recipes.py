"""Scheduled multi-step automation recipes."""

import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from shared import _self_port, COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    croniter = None
    HAS_CRONITER = False


recipes_bp = Blueprint("recipes", __name__)

RECIPES_FILE = COAGENT_DIR / "recipes.json"
SCHEDULER_INTERVAL_SECONDS = 30
MAX_LOGS_PER_RECIPE = 20

_RECIPES_LOCK = threading.RLock()
_RECIPES = {}
_RECIPE_LOGS = {}
_RUNNING_RECIPES = set()
_SCHED_LAST_RUN = {}
_SCHEDULER_THREAD = None


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


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
            text = response.read().decode("utf-8", errors="replace")
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


def _step_params(step, previous):
    params = _resolve_refs(deepcopy(step.get("params") or {}), previous)
    target = _resolve_refs(deepcopy(step.get("target") or {}), previous)
    if isinstance(target, dict):
        for key, value in target.items():
            params.setdefault(key, value)
    return params


def _step_target(step):
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    merged = {}
    merged.update(target)
    merged.update({key: value for key, value in params.items() if value is not None})
    return merged


def _step_target_text(step):
    target = _step_target(step)
    for key in ("text", "name", "automation_id", "selector", "query"):
        value = target.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if key == "selector" and text[:1] in {"#", "."}:
                text = text[1:]
            return text
    return ""


def _describe_step_action(step):
    action = str(step.get("action") or "").strip().lower() or "unknown"
    target = _step_target(step)
    if action == "click":
        text = _step_target_text(step)
        if text:
            return f"click on {text}"
        if "x" in target and "y" in target:
            return f"click at {target.get('x')},{target.get('y')}"
    if action == "type":
        text = target.get("text") or (step.get("params") or {}).get("text") or ""
        return f"type {str(text)[:40]}"
    return action


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
            x = _coerce_int(bounds.get("x"), 0) + _coerce_int(bounds.get("width"), 0) // 2
        if y is None and bounds:
            y = _coerce_int(bounds.get("y"), 0) + _coerce_int(bounds.get("height"), 0) // 2
        return {"x": x, "y": y, "match": first, "result": result}
    at = result.get("at") if isinstance(result.get("at"), dict) else {}
    if at:
        return {"x": at.get("x"), "y": at.get("y"), "result": result}
    return {"result": result}


def _result_error(result):
    if isinstance(result, dict):
        return result.get("error")
    return f"unexpected response type: {type(result).__name__}"


def _run_one_step(step, previous, auth_header):
    action = str(step.get("action") or "").strip().lower()
    params = _step_params(step, previous)
    if action == "wait":
        seconds = max(0.0, min(_coerce_float(params.get("seconds", 1), 1.0), 3600.0))
        time.sleep(seconds)
        return {"status": "ok", "result": {"status": "ok", "slept": seconds}}
    if action == "launch":
        query = params.get("query") or params.get("path") or params.get("command") or params.get("app")
        result = _coagent_request("POST", "/process/start", {"path": query}, auth_header=auth_header)
        if isinstance(result, dict) and result.get("error"):
            result = _coagent_request("POST", "/app/open", {"path": query}, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "click":
        if ("x" not in params or "y" not in params) and _step_target_text(step):
            target_payload = {
                "text": _step_target_text(step),
                "type": params.get("type") or params.get("control_type") or "button",
                "fallback_to_ocr": params.get("fallback_to_ocr", True),
                "button": params.get("button", "left"),
                "background": params.get("background", True),
            }
            result = _coagent_request("POST", "/uia/click-hybrid", target_payload, auth_header=auth_header)
        else:
            result = _coagent_request("POST", "/mouse/click", params, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "type":
        if "text" not in params and _step_target_text(step):
            params["text"] = _step_target_text(step)
        result = _coagent_request("POST", "/key/type", params, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action in {"key", "hotkey", "press"}:
        keys = params.get("keys", params.get("key", []))
        if isinstance(keys, str):
            keys = [part for part in keys.replace("+", " ").split() if part]
        result = _coagent_request("POST", "/key/press", {"keys": keys}, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "ocr_find":
        result = _coagent_request("POST", "/ocr/find", params, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "telegram_send":
        result = _coagent_request("POST", "/telegram/send", params, auth_header=auth_header)
        if isinstance(result, dict) and result.get("status_code") == 404:
            result = _telegram_send(params)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "screenshot":
        result = _coagent_request("GET", "/screen/base64", auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "finder_click":
        result = _coagent_request("POST", "/finder/click", params, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    if action == "finder_type":
        result = _coagent_request("POST", "/finder/type", params, auth_header=auth_header)
        return {"status": "error" if _result_error(result) else "ok", "result": result}
    return {"status": "error", "result": {"error": f"Unknown action: {action}"}}


def _execute_steps(steps, timeout=300, auth_header=None, initial_context=None):
    """Execute a list of steps via CoAgent internal API calls.

    ``initial_context`` seeds the ``$prev.`` reference namespace (e.g. the JSON
    payload of an inbound webhook), so early steps can template in external input.
    """
    results = []
    deadline = time.time() + max(1, _coerce_int(timeout, 300))
    previous = dict(initial_context or {})
    for index, step in enumerate(steps):
        action = str(step.get("action") or "").strip().lower()
        start = time.time()
        if time.time() >= deadline:
            results.append({
                "step_index": index,
                "action": action,
                "status": "error",
                "error": "recipe timeout exceeded",
                "duration": 0,
            })
            break
        try:
            outcome = _run_one_step(step, previous, auth_header)
            result = outcome.get("result", {})
            status = outcome.get("status", "error")
            record = {
                "step_index": index,
                "action": action,
                "status": status,
                "result": result,
                "duration": round(time.time() - start, 3),
            }
            if isinstance(result, dict) and result.get("error"):
                record["error"] = result.get("error")
            results.append(record)
            if status != "ok":
                break
            previous = _prev_from_result(result)
            if initial_context:
                # Keep injected context available to later steps as well.
                previous = {**initial_context, **previous}
        except Exception as exc:
            results.append({
                "step_index": index,
                "action": action,
                "status": "error",
                "error": str(exc),
                "duration": round(time.time() - start, 3),
            })
            break
    return results


def _load_recipes():
    global _RECIPES
    try:
        if not RECIPES_FILE.exists():
            _RECIPES = {}
            return
        data = json.loads(RECIPES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            recipes = {str(item.get("recipe_id") or item.get("id") or uuid.uuid4().hex): item for item in data if isinstance(item, dict)}
        else:
            recipes = data.get("recipes", data) if isinstance(data, dict) else {}
        loaded = {}
        for rid, recipe in recipes.items():
            try:
                loaded[str(rid)] = _normalize_recipe(recipe, recipe_id=str(rid))
            except Exception as exc:
                _console(f"[recipes] skipping invalid recipe {rid}: {type(exc).__name__}: {exc}")
        _RECIPES = loaded
    except Exception as exc:
        _console(f"[recipes] failed to load recipes: {type(exc).__name__}: {exc}")
        _RECIPES = {}


def _save_recipes():
    tmp = RECIPES_FILE.with_suffix(".tmp")
    payload = {"recipes": _RECIPES, "updated_at": datetime.now().isoformat(timespec="seconds")}
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(RECIPES_FILE)


def _normalize_recipe(data, recipe_id=None):
    if not isinstance(data, dict):
        raise ValueError("recipe must be an object")
    rid = str(recipe_id or data.get("recipe_id") or data.get("id") or uuid.uuid4().hex)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    normalized_steps = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("each step must be an object")
        action = str(step.get("action") or "").strip().lower()
        if not action:
            raise ValueError("each step needs an action")
        params = step.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("step params must be an object")
        normalized = {"action": action, "params": params}
        for optional in ("target", "expected"):
            if optional in step:
                if not isinstance(step.get(optional), dict):
                    raise ValueError(f"step {optional} must be an object")
                normalized[optional] = step.get(optional)
        normalized_steps.append(normalized)
    created_at = data.get("created_at") or datetime.now().isoformat(timespec="seconds")
    return {
        "recipe_id": rid,
        "id": rid,
        "name": name,
        "steps": normalized_steps,
        "schedule": str(data.get("schedule") or "").strip(),
        "enabled": bool(data.get("enabled", True)),
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "last_run": data.get("last_run"),
        "last_status": data.get("last_status"),
    }


def _recipe_summary(recipe):
    item = dict(recipe)
    item["step_count"] = len(recipe.get("steps", []))
    return item


def _simple_schedule_matches(schedule, now):
    schedule = str(schedule or "").strip().lower()
    if not schedule:
        return False
    match = re.fullmatch(r"every\s+(\d+)\s+minutes?", schedule)
    if match:
        minutes = max(1, int(match.group(1)))
        return now.minute % minutes == 0
    if schedule == "hourly":
        return now.minute == 0
    match = re.fullmatch(r"daily\s+at\s+(\d{1,2}):(\d{2})", schedule)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return now.hour == hour and now.minute == minute
    return False


def _cron_schedule_matches(schedule, now):
    if not HAS_CRONITER:
        return _simple_schedule_matches(schedule, now)
    try:
        if hasattr(croniter, "match"):
            return bool(croniter.match(schedule, now))
        previous = croniter(schedule, now + timedelta(seconds=1)).get_prev(datetime)
        return 0 <= (now - previous).total_seconds() < 60
    except Exception:
        return _simple_schedule_matches(schedule, now)


def _append_log(recipe_id, run_record):
    with _RECIPES_LOCK:
        logs = _RECIPE_LOGS.setdefault(recipe_id, [])
        logs.append(run_record)
        del logs[:-MAX_LOGS_PER_RECIPE]


def _run_recipe(recipe_id, auth_header=None, triggered_by="manual"):
    with _RECIPES_LOCK:
        recipe = deepcopy(_RECIPES.get(recipe_id))
        if not recipe:
            return {"error": "recipe not found", "recipe_id": recipe_id}
        if recipe_id in _RUNNING_RECIPES:
            return {"error": "recipe already running", "recipe_id": recipe_id}
        _RUNNING_RECIPES.add(recipe_id)
    started = time.time()
    run_id = uuid.uuid4().hex
    try:
        results = _execute_steps(recipe.get("steps", []), auth_header=auth_header)
        failed = [item for item in results if item.get("status") != "ok"]
        status = "failed" if failed else "completed"
        run_record = {
            "run_id": run_id,
            "recipe_id": recipe_id,
            "name": recipe.get("name"),
            "triggered_by": triggered_by,
            "started_at": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(time.time() - started, 3),
            "status": status,
            "steps": results,
            "completed": sum(1 for item in results if item.get("status") == "ok"),
            "failed": len(failed),
        }
        with _RECIPES_LOCK:
            if recipe_id in _RECIPES:
                _RECIPES[recipe_id]["last_run"] = run_record["finished_at"]
                _RECIPES[recipe_id]["last_status"] = status
                _save_recipes()
        _append_log(recipe_id, run_record)
        return run_record
    finally:
        with _RECIPES_LOCK:
            _RUNNING_RECIPES.discard(recipe_id)


def _scheduler_loop():
    _console(f"[recipes] scheduler started interval={SCHEDULER_INTERVAL_SECONDS}s croniter={HAS_CRONITER}")
    while True:
        try:
            now = datetime.now().replace(second=0, microsecond=0)
            due = []
            with _RECIPES_LOCK:
                recipes = list(_RECIPES.values())
                last_run = dict(_SCHED_LAST_RUN)
            for recipe in recipes:
                if not recipe.get("enabled") or not recipe.get("schedule"):
                    continue
                recipe_id = recipe["recipe_id"]
                minute_key = now.strftime("%Y%m%d%H%M")
                if last_run.get(recipe_id) == minute_key:
                    continue
                if _cron_schedule_matches(recipe.get("schedule"), now):
                    with _RECIPES_LOCK:
                        _SCHED_LAST_RUN[recipe_id] = minute_key
                    due.append(recipe_id)
            for recipe_id in due:
                threading.Thread(
                    target=_run_recipe,
                    args=(recipe_id, _auth_header(None), "schedule"),
                    name=f"recipe-{recipe_id[:8]}",
                    daemon=True,
                ).start()
        except Exception as exc:
            _console(f"[recipes] scheduler iteration error: {type(exc).__name__}: {exc}")
        time.sleep(SCHEDULER_INTERVAL_SECONDS)


def _start_scheduler():
    global _SCHEDULER_THREAD
    with _RECIPES_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, name="recipes-scheduler", daemon=True)
        _SCHEDULER_THREAD.start()


def _steps_from_payload(data):
    if not isinstance(data, dict):
        return None, "payload must be an object", 400
    recipe_id = data.get("recipe_id") or data.get("id")
    if recipe_id:
        with _RECIPES_LOCK:
            recipe = deepcopy(_RECIPES.get(str(recipe_id)))
        if not recipe:
            return None, "recipe not found", 404
        return recipe.get("steps", []), None, 200
    recipe = data.get("recipe")
    if isinstance(recipe, dict):
        steps = recipe.get("steps")
    else:
        steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, "steps must be a non-empty list", 400
    return steps, None, 200


def _screen_base64(auth_header):
    result = _coagent_request("GET", "/screen/base64", auth_header=auth_header, timeout=20)
    if isinstance(result, dict) and result.get("data"):
        return result.get("data")
    return ""


def _expected_text(expected):
    for key in ("text", "selector", "name", "automation_id", "query"):
        value = expected.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if key == "selector" and text[:1] in {"#", "."}:
                text = text[1:]
            return text
    return ""


def _verify_expected(expected, auth_header, screenshot_before="", screenshot_after=""):
    if not expected:
        return {"ok": True, "actual": "no expected condition supplied"}
    if not isinstance(expected, dict):
        return {"ok": False, "actual": "expected condition must be an object"}
    expected_type = str(expected.get("type") or "text_visible").strip().lower()
    if expected_type in {"toast", "text", "text_visible", "ocr", "ocr_text"}:
        text = _expected_text(expected)
        if not text:
            return {"ok": False, "actual": "expected text is required"}
        result = _coagent_request("POST", "/uia/find-hybrid", {
            "text": text,
            "fallback_to_ocr": True,
        }, auth_header=auth_header, timeout=30)
        ok = bool(isinstance(result, dict) and result.get("found"))
        return {
            "ok": ok,
            "actual": f"Found '{text}' via {result.get('method')}" if ok else f"No '{text}' visible in screenshot",
            "result": result,
        }
    if expected_type in {"element_exists", "exists", "element"}:
        text = _expected_text(expected)
        if not text:
            return {"ok": False, "actual": "element selector/text is required"}
        result = _coagent_request("POST", "/uia/find-hybrid", {
            "text": text,
            "type": expected.get("control_type") or expected.get("element_type") or "",
            "fallback_to_ocr": True,
        }, auth_header=auth_header, timeout=30)
        ok = bool(isinstance(result, dict) and result.get("found"))
        return {
            "ok": ok,
            "actual": f"Element '{text}' exists via {result.get('method')}" if ok else f"Element '{text}' not found",
            "result": result,
        }
    if expected_type == "screen_changed":
        ok = bool(screenshot_before and screenshot_after and screenshot_before != screenshot_after)
        return {"ok": ok, "actual": "screen changed" if ok else "screen did not change"}
    return {"ok": False, "actual": f"unsupported expected type: {expected_type}"}


def _verify_target_exists(step, auth_header):
    action = str(step.get("action") or "").strip().lower()
    target = _step_target(step)
    if "x" in target and "y" in target:
        return {"ok": True, "actual": "coordinates supplied", "target": target}
    if action in {"type", "key", "hotkey", "press", "wait", "screenshot", "telegram_send"} and not (
        isinstance(step.get("target"), dict) and any(key in step["target"] for key in ("selector", "name", "automation_id"))
    ):
        return {"ok": True, "actual": "no UI element target required"}
    text = _step_target_text(step)
    if not text:
        return {"ok": True, "actual": "no UI element target supplied"}
    result = _coagent_request("POST", "/uia/find-hybrid", {
        "text": text,
        "type": target.get("type") or target.get("control_type") or "",
        "fallback_to_ocr": target.get("fallback_to_ocr", True),
    }, auth_header=auth_header, timeout=30)
    ok = bool(isinstance(result, dict) and result.get("found"))
    return {
        "ok": ok,
        "actual": f"target '{text}' found via {result.get('method')}" if ok else f"target '{text}' not found",
        "target": text,
        "result": result,
    }


def _execute_steps_with_verification(steps, auth_header, timeout=300):
    deadline = time.time() + max(1, _coerce_int(timeout, 300))
    total = len(steps)
    completed = 0
    previous = {}
    step_records = []
    for index, step in enumerate(steps):
        if time.time() >= deadline:
            return {
                "status": "failed",
                "completed": completed,
                "total": total,
                "failed_at_step": index + 1,
                "failed_action": _describe_step_action(step),
                "expected": step.get("expected"),
                "actual": "verify-run timeout exceeded",
                "steps": step_records,
            }
        screenshot_before = ""
        attempts = []
        verified = False
        latest_after = ""
        latest_result = {}
        latest_verify = {}
        for attempt in (1, 2):
            started = time.time()
            screenshot_before = _screen_base64(auth_header)
            outcome = _run_one_step(step, previous, auth_header)
            latest_result = outcome.get("result", {})
            time.sleep(1.0)
            latest_after = _screen_base64(auth_header)
            if outcome.get("status") != "ok":
                latest_verify = {
                    "ok": False,
                    "actual": latest_result.get("error") if isinstance(latest_result, dict) else "action failed",
                }
            else:
                latest_verify = _verify_expected(
                    step.get("expected"),
                    auth_header,
                    screenshot_before=screenshot_before,
                    screenshot_after=latest_after,
                )
            attempts.append({
                "attempt": attempt,
                "action_status": outcome.get("status"),
                "verification_ok": bool(latest_verify.get("ok")),
                "actual": latest_verify.get("actual"),
                "duration": round(time.time() - started, 3),
                "result": latest_result,
            })
            if latest_verify.get("ok"):
                verified = True
                completed += 1
                previous = _prev_from_result(latest_result)
                break
        record = {
            "step_index": index,
            "step_number": index + 1,
            "action": str(step.get("action") or "").strip().lower(),
            "verified": verified,
            "attempts": attempts,
        }
        step_records.append(record)
        if not verified:
            return {
                "status": "failed",
                "completed": completed,
                "total": total,
                "failed_at_step": index + 1,
                "failed_action": _describe_step_action(step),
                "expected": step.get("expected"),
                "actual": latest_verify.get("actual") or "verification failed",
                "screenshot_before": screenshot_before,
                "screenshot_after": latest_after,
                "steps": step_records,
            }
    return {"status": "completed", "completed": completed, "total": total, "steps": step_records}


@recipes_bp.route("/recipes/create", methods=["POST"])
def route_recipes_create():
    data = _json_body()
    try:
        recipe = _normalize_recipe(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _RECIPES_LOCK:
        _RECIPES[recipe["recipe_id"]] = recipe
        _save_recipes()
    return jsonify({
        "recipe_id": recipe["recipe_id"],
        "name": recipe["name"],
        "schedule": recipe["schedule"],
        "steps": len(recipe["steps"]),
        "enabled": recipe["enabled"],
    })


@recipes_bp.route("/recipes/verify", methods=["POST"])
def route_recipes_verify():
    data = _json_body()
    steps, error, status = _steps_from_payload(data)
    if error:
        return jsonify({"error": error}), status
    auth = _auth_header(request.headers.get("Authorization", ""))
    results = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            results.append({
                "step_index": index,
                "step_number": index + 1,
                "ok": False,
                "actual": "step must be an object",
            })
            continue
        check = _verify_target_exists(step, auth)
        results.append({
            "step_index": index,
            "step_number": index + 1,
            "action": str(step.get("action") or "").strip().lower(),
            **check,
        })
    ok_count = sum(1 for item in results if item.get("ok"))
    return jsonify({
        "valid": ok_count == len(results),
        "completed": ok_count,
        "total": len(results),
        "results": results,
    })


@recipes_bp.route("/recipes/verify-run", methods=["POST"])
def route_recipes_verify_run():
    data = _json_body()
    steps, error, status = _steps_from_payload(data)
    if error:
        return jsonify({"error": error}), status
    for step in steps:
        if not isinstance(step, dict):
            return jsonify({"error": "each step must be an object"}), 400
    auth = _auth_header(request.headers.get("Authorization", ""))
    timeout = data.get("timeout", 300) if isinstance(data, dict) else 300
    result = _execute_steps_with_verification(steps, auth, timeout=timeout)
    return jsonify(result)


@recipes_bp.route("/recipes/list", methods=["GET"])
def route_recipes_list():
    with _RECIPES_LOCK:
        recipes = [_recipe_summary(recipe) for recipe in _RECIPES.values()]
    recipes.sort(key=lambda item: item.get("name", "").lower())
    return jsonify({"recipes": recipes, "count": len(recipes), "croniter": HAS_CRONITER})


@recipes_bp.route("/recipes/run", methods=["POST"])
def route_recipes_run():
    data = _json_body()
    recipe_id = data.get("recipe_id") or data.get("id")
    auth = _auth_header(request.headers.get("Authorization", ""))
    if recipe_id:
        result = _run_recipe(str(recipe_id), auth_header=auth, triggered_by="manual")
        status = 404 if result.get("error") == "recipe not found" else 409 if result.get("error") else 200
        return jsonify(result), status
    steps, error, status = _steps_from_payload(data)
    if error:
        return jsonify({"error": error}), status
    for step in steps:
        if not isinstance(step, dict):
            return jsonify({"error": "each step must be an object"}), 400
    timeout = data.get("timeout", 300) if isinstance(data, dict) else 300
    if str(data.get("verify", "false")).lower() in {"1", "true", "yes", "on"}:
        result = _execute_steps_with_verification(steps, auth, timeout=timeout)
        return jsonify(result), 200 if result.get("status") == "completed" else 409
    results = _execute_steps(steps, timeout=timeout, auth_header=auth)
    failed = [item for item in results if item.get("status") != "ok"]
    return jsonify({
        "status": "failed" if failed else "completed",
        "completed": sum(1 for item in results if item.get("status") == "ok"),
        "failed": len(failed),
        "total": len(steps),
        "steps": results,
    }), 200 if not failed else 409


@recipes_bp.route("/recipes/status/<recipe_id>", methods=["GET"])
def route_recipe_status(recipe_id):
    with _RECIPES_LOCK:
        recipe = _RECIPES.get(recipe_id)
        if not recipe:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        payload = _recipe_summary(recipe)
        payload["running"] = recipe_id in _RUNNING_RECIPES
        payload["logs"] = list(_RECIPE_LOGS.get(recipe_id, []))
        return jsonify(payload)


@recipes_bp.route("/recipes/<recipe_id>", methods=["GET"])
def route_recipe_get(recipe_id):
    with _RECIPES_LOCK:
        recipe = _RECIPES.get(recipe_id)
        if not recipe:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        return jsonify(_recipe_summary(recipe))


@recipes_bp.route("/recipes/run/<recipe_id>", methods=["POST"])
def route_recipe_run(recipe_id):
    auth = _auth_header(request.headers.get("Authorization", ""))
    result = _run_recipe(recipe_id, auth_header=auth, triggered_by="manual")
    status = 404 if result.get("error") == "recipe not found" else 409 if result.get("error") else 200
    return jsonify(result), status


@recipes_bp.route("/recipes/<recipe_id>", methods=["POST"])
def route_recipe_update(recipe_id):
    data = _json_body()
    try:
        recipe = _normalize_recipe(data, recipe_id=recipe_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _RECIPES_LOCK:
        if recipe_id not in _RECIPES:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        recipe["created_at"] = _RECIPES[recipe_id].get("created_at")
        _RECIPES[recipe_id] = recipe
        _save_recipes()
    return jsonify(_recipe_summary(recipe))


@recipes_bp.route("/recipes/<recipe_id>", methods=["DELETE"])
def route_recipe_delete(recipe_id):
    with _RECIPES_LOCK:
        if recipe_id not in _RECIPES:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        _RECIPES.pop(recipe_id, None)
        _RECIPE_LOGS.pop(recipe_id, None)
        _SCHED_LAST_RUN.pop(recipe_id, None)
        _save_recipes()
    return jsonify({"status": "deleted", "recipe_id": recipe_id})


@recipes_bp.route("/recipes/toggle/<recipe_id>", methods=["POST"])
def route_recipe_toggle(recipe_id):
    data = _json_body()
    with _RECIPES_LOCK:
        recipe = _RECIPES.get(recipe_id)
        if not recipe:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        raw_enabled = data.get("enabled")
        if "enabled" in data:
            if isinstance(raw_enabled, bool):
                enabled = raw_enabled
            else:
                enabled = str(raw_enabled).strip().lower() in ("true", "1", "yes", "on")
        else:
            enabled = not bool(recipe.get("enabled"))
        recipe["enabled"] = enabled
        recipe["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_recipes()
        return jsonify({"recipe_id": recipe_id, "enabled": enabled})


@recipes_bp.route("/recipes/logs/<recipe_id>", methods=["GET"])
def route_recipe_logs(recipe_id):
    with _RECIPES_LOCK:
        if recipe_id not in _RECIPES:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404
        logs = list(_RECIPE_LOGS.get(recipe_id, []))
    return jsonify({"recipe_id": recipe_id, "logs": logs, "count": len(logs)})


def register_routes(app, state, require_auth):
    _load_recipes()
    app.register_blueprint(recipes_bp)
    _wrap_registered_blueprint_routes(app, recipes_bp.name, require_auth)
    _start_scheduler()
    state.recipes = {"file": str(RECIPES_FILE), "croniter": HAS_CRONITER}
