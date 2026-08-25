"""Agent gateway routes for invoking allowlisted local AI agent CLIs."""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request, stream_with_context

from shared import COAGENT_DIR, _console, _is_private_url, _log, _wrap_registered_blueprint_routes


def _userprofile():
    return os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())


def _resolve_npm_paths(name):
    """Resolve known paths for npm-installed CLI tools."""
    userprofile = _userprofile()
    return (
        Path(userprofile) / "AppData/Roaming/npm" / f"{name}.cmd",
        Path(userprofile) / "AppData/Roaming/npm" / f"{name}.exe",
        Path(userprofile) / "AppData/Roaming/npm" / name,
    )


agent_bp = Blueprint("agent_gateway", __name__)
_LOGGER = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 100 * 1024
MAX_OUTPUT_CHARS = 500 * 1024
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 1800
LOG_DIR = COAGENT_DIR / "agent_logs"
PROVIDER_CONFIG_FILE = COAGENT_DIR / "agent_providers_config.json"
STREAM_BACKLOG_EVENTS = 10000
STREAM_IDLE_CLEANUP_SECONDS = 300

AGENT_DETECTION_LOCK = threading.Lock()
LOG_WRITE_LOCK = threading.Lock()
EXECUTION_LOCKS_LOCK = threading.Lock()
PROVIDER_CONFIG_LOCK = threading.Lock()
_streams_lock = threading.Lock()
EXECUTION_LOCKS = {}
ACTIVE_STREAMS = {}
AGENT_CACHE = {}


def _debug_failure(context, exc):
    _LOGGER.debug("%s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)
DEFAULT_AGENT = None

SUPPORTED_PROVIDERS = {"codex", "openai", "anthropic", "deepseek", "ollama", "generic"}
PROVIDER_DEFAULTS = {
    "codex": {"model": None, "base_url": None},
    "openai": {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"model": "claude-sonnet-4", "base_url": "https://api.anthropic.com/v1"},
    "deepseek": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    "ollama": {"model": "qwen3.6:27b", "base_url": "http://127.0.0.1:11434"},
    "generic": {"model": None, "base_url": None},
}
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "generic": "GENERIC_AI_API_KEY",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "agent_logs",
}

SKIP_FILES = {
    "coagent_server.log",
    "tray_icon.log",
    "tunnel.log",
}


@dataclass(frozen=True)
class AgentSpec:
    name: str
    binaries: tuple
    known_paths: tuple
    version_args: tuple = ("--version",)
    supports_stdin: bool = False
    base_args: tuple = ()
    prompt_prefix_args: tuple = ()
    read_only_args: tuple = ()
    model_flag: str = "--model"


AGENT_SPECS = {
    "codex": AgentSpec(
        name="codex",
        binaries=("codex",),
        known_paths=_resolve_npm_paths("codex"),
        supports_stdin=True,
        base_args=("exec",),
        read_only_args=("--sandbox", "read-only"),
        model_flag="--model",
    ),
    "claude": AgentSpec(
        name="claude",
        binaries=("claude",),
        known_paths=(str(Path(_userprofile()) / ".local" / "bin" / "claude.exe"),) + _resolve_npm_paths("claude"),
        supports_stdin=False,
        prompt_prefix_args=("-p",),
        read_only_args=("--permission-mode", "plan", "--disallowedTools", "Edit,Write,MultiEdit,NotebookEdit"),
        model_flag="--model",
    ),
    "gemini": AgentSpec(
        name="gemini",
        binaries=("gemini",),
        known_paths=_resolve_npm_paths("gemini"),
        supports_stdin=True,
        model_flag="--model",
    ),
    "opencode": AgentSpec(
        name="opencode",
        binaries=("opencode",),
        known_paths=_resolve_npm_paths("opencode") + (str(Path(_userprofile()) / ".local" / "bin" / "opencode.exe"),),
        supports_stdin=False,
        base_args=("run",),
        model_flag="--model",
    ),
}


def _json_payload():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _validate_provider_name(provider):
    if provider in (None, ""):
        return None  # No default agent — must be explicitly requested
    if not isinstance(provider, str):
        raise ValueError("provider must be a string")
    normalized = provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"provider must be one of: {allowed}")
    return normalized


def _validate_api_key(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("api_key must be a string")
    value = value.strip()
    if len(value) > 4096:
        raise ValueError("api_key is too long")
    return value


def _validate_base_url(value, allow_private=False):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("base_url must be a string")
    base_url = value.strip().rstrip("/")
    if len(base_url) > 2048:
        raise ValueError("base_url is too long")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an http or https URL")
    if not allow_private and _is_private_url(base_url):
        raise ValueError("base_url resolves to a blocked private or internal address")
    return base_url


def _provider_defaults(provider):
    return dict(PROVIDER_DEFAULTS.get(provider, {}))


def _load_provider_config_unlocked():
    config = {"provider": "codex", "providers": {}}
    try:
        if PROVIDER_CONFIG_FILE.exists():
            loaded = json.loads(PROVIDER_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                if isinstance(loaded.get("providers"), dict):
                    config.update(loaded)
                else:
                    provider = _validate_provider_name(loaded.get("provider"))
                    config["provider"] = provider
                    if provider is not None:
                        config["providers"][provider] = {
                            key: loaded.get(key)
                            for key in ("api_key", "model", "base_url")
                            if loaded.get(key) not in (None, "")
                        }
    except Exception as exc:
        _console(f"[agent] failed to load provider config: {exc}")
    try:
        config["provider"] = _validate_provider_name(config.get("provider"))
    except ValueError:
        config["provider"] = None  # No default agent
    providers = config.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    sanitized = {}
    for provider, entry in providers.items():
        try:
            normalized = _validate_provider_name(provider)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        clean = {}
        for key in ("api_key", "model", "base_url"):
            value = entry.get(key)
            if value not in (None, ""):
                clean[key] = str(value)
        sanitized[normalized] = clean
    config["providers"] = sanitized
    return config


def _load_provider_config():
    with PROVIDER_CONFIG_LOCK:
        return _load_provider_config_unlocked()


def _save_provider_config(config):
    with PROVIDER_CONFIG_LOCK:
        PROVIDER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = PROVIDER_CONFIG_FILE.with_suffix(".json.tmp")
        # Production deployments should encrypt this file before writing API keys.
        tmp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(PROVIDER_CONFIG_FILE)


def _provider_entry(provider, config=None):
    config = config or _load_provider_config()
    entry = _provider_defaults(provider)
    stored = (config.get("providers") or {}).get(provider)
    if isinstance(stored, dict):
        for key in ("api_key", "model", "base_url"):
            if stored.get(key) not in (None, ""):
                entry[key] = stored.get(key)
    return entry


def _mask_api_key(value):
    if not value:
        return ""
    value = str(value)
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _masked_provider_entry(provider, entry):
    masked = {
        "provider": provider,
        "model": entry.get("model"),
        "base_url": entry.get("base_url"),
        "api_key_configured": bool(entry.get("api_key") or os.environ.get(PROVIDER_ENV_KEYS.get(provider, ""))),
    }
    if entry.get("api_key"):
        masked["api_key"] = _mask_api_key(entry.get("api_key"))
        masked["api_key_source"] = "config"
    elif os.environ.get(PROVIDER_ENV_KEYS.get(provider, "")):
        masked["api_key"] = _mask_api_key(os.environ.get(PROVIDER_ENV_KEYS.get(provider, "")))
        masked["api_key_source"] = "environment"
    else:
        masked["api_key"] = ""
        masked["api_key_source"] = ""
    return masked


def _provider_name_for_exec(data):
    if isinstance(data, dict) and data.get("provider") not in (None, ""):
        return _validate_provider_name(data.get("provider"))
    if isinstance(data, dict) and data.get("agent") not in (None, ""):
        return "codex"
    config = _load_provider_config()
    return _validate_provider_name(config.get("provider"))


def _provider_settings(provider, data=None):
    data = data or {}
    config = _load_provider_config()
    entry = _provider_entry(provider, config=config)
    if data.get("model") not in (None, ""):
        entry["model"] = _validate_model(data.get("model"))
    if data.get("base_url") not in (None, ""):
        entry["base_url"] = _validate_base_url(data.get("base_url"), allow_private=(provider == "ollama"))
    if data.get("api_key") not in (None, ""):
        entry["api_key"] = _validate_api_key(data.get("api_key"))
    env_key = PROVIDER_ENV_KEYS.get(provider)
    if not entry.get("api_key") and env_key:
        entry["api_key"] = os.environ.get(env_key, "")
    return entry


def _post_json(url, headers, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
    request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = getattr(response, "status", 200)
            reason = getattr(response, "reason", "")
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        reason = exc.reason
        text = exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {"text": text}
    if status_code >= 400:
        detail = data.get("error") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type") or json.dumps(detail)
        if not detail:
            detail = text[:500] or reason
        raise RuntimeError(f"HTTP {status_code}: {detail}")
    return data


def _content_from_openai_payload(payload):
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if content in (None, ""):
        content = first.get("text") or message.get("reasoning_content") or ""
    return str(content)


def _provider_generic(prompt, model, api_key, base_url, timeout):
    model = model or ""
    if not model:
        raise ValueError("model is required for generic provider")
    base_url = _validate_base_url(base_url)
    if not base_url:
        raise ValueError("base_url is required for generic provider")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    data = _post_json(f"{base_url}/chat/completions", headers, payload, timeout)
    return {"role": "assistant", "content": _content_from_openai_payload(data)}


def _provider_openai(prompt, model, api_key, base_url, timeout):
    if not api_key:
        raise ValueError("api_key is required for openai provider")
    return _provider_generic(
        prompt,
        model or PROVIDER_DEFAULTS["openai"]["model"],
        api_key,
        base_url or PROVIDER_DEFAULTS["openai"]["base_url"],
        timeout,
    )


def _provider_deepseek(prompt, model, api_key, base_url, timeout):
    if not api_key:
        raise ValueError("api_key is required for deepseek provider")
    return _provider_generic(
        prompt,
        model or PROVIDER_DEFAULTS["deepseek"]["model"],
        api_key,
        base_url or PROVIDER_DEFAULTS["deepseek"]["base_url"],
        timeout,
    )


def _provider_anthropic(prompt, model, api_key, timeout):
    if not api_key:
        raise ValueError("api_key is required for anthropic provider")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model or PROVIDER_DEFAULTS["anthropic"]["model"],
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post_json(f"{PROVIDER_DEFAULTS['anthropic']['base_url']}/messages", headers, payload, timeout)
    content = data.get("content") if isinstance(data, dict) else None
    if isinstance(content, list):
        text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("text"))
    else:
        text = str(content or "")
    return {"role": "assistant", "content": text}


def _provider_ollama(prompt, model):
    return _provider_ollama_request(prompt, model, PROVIDER_DEFAULTS["ollama"]["base_url"], DEFAULT_TIMEOUT_SECONDS)


def _provider_ollama_request(prompt, model, base_url, timeout):
    # Ollama is a local model server (default http://127.0.0.1:11434) — allow
    # private/loopback addresses that the generic SSRF check would reject.
    base_url = _validate_base_url(base_url, allow_private=True) or PROVIDER_DEFAULTS["ollama"]["base_url"]
    payload = {
        "model": model or PROVIDER_DEFAULTS["ollama"]["model"],
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post_json(f"{base_url}/api/chat", {"Content-Type": "application/json"}, payload, timeout)
    message = data.get("message") if isinstance(data, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    return {"role": "assistant", "content": str(content or data.get("response") or "")}


def _provider_codex(prompt, timeout):
    result = _execute_agent(prompt=prompt, timeout=timeout, purpose="exec")
    return {"role": "assistant", "content": result.get("output", "")}


def _call_provider(provider, prompt, settings, timeout):
    model = settings.get("model")
    api_key = settings.get("api_key")
    base_url = settings.get("base_url")
    if provider == "openai":
        return _provider_openai(prompt, model, api_key, base_url, timeout)
    if provider == "anthropic":
        return _provider_anthropic(prompt, model, api_key, timeout)
    if provider == "deepseek":
        return _provider_deepseek(prompt, model, api_key, base_url, timeout)
    if provider == "ollama":
        return _provider_ollama_request(prompt, model, base_url, timeout)
    if provider == "generic":
        return _provider_generic(prompt, model, api_key, base_url, timeout)
    if provider == "codex":
        return _provider_codex(prompt, timeout)
    raise ValueError(f"unsupported provider: {provider}")


def _execute_provider(data, provider, purpose="exec"):
    prompt = _validate_prompt(data.get("prompt"))
    timeout = _validate_timeout(data.get("timeout"))
    settings = _provider_settings(provider, data)
    started = time.time()
    message = {"role": "assistant", "content": ""}
    error = ""
    success = False
    try:
        message = _call_provider(provider, prompt, settings, timeout)
        success = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    duration = round(time.time() - started, 2)
    output = message.get("content", "") if success else f"[provider:{provider}] {error}"
    response = {
        "success": success,
        "agent": provider,
        "provider": provider,
        "message": message,
        "output": output,
        "exit_code": 0 if success else 1,
        "duration_seconds": duration,
        "files_modified": [],
        "log_id": "",
        "read_only": False,
        "read_only_violation": False,
    }
    record = {
        **response,
        "purpose": purpose,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "workdir": str(COAGENT_DIR),
        "command": [f"provider:{provider}"],
        "model": settings.get("model"),
        "base_url": settings.get("base_url"),
        "timeout_seconds": timeout,
        "timed_out": False,
        "output_truncated": False,
        "stdout": output if success else "",
        "stderr": "" if success else error,
        "prompt": prompt,
    }
    try:
        response["log_id"] = _write_log(record)
    except Exception as exc:
        _console(f"[agent] failed to write provider log: {exc}")
    return response


def _validate_log_id(log_id):
    if not isinstance(log_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", log_id):
        raise ValueError("invalid log_id")
    return log_id


def _log_path_for_id(log_id):
    return LOG_DIR / f"{_validate_log_id(log_id)}.json"


def _new_stream_state():
    return {
        "events": deque(maxlen=STREAM_BACKLOG_EVENTS),
        "next_seq": 0,
        "complete": False,
        "connections": 0,
        "finished_at": None,
        "created_at": time.time(),
    }


def _schedule_stream_cleanup(log_id, delay=STREAM_IDLE_CLEANUP_SECONDS):
    timer = threading.Timer(delay, _cleanup_stream_if_idle, args=(log_id,))
    timer.daemon = True
    timer.start()


def _cleanup_stream_if_idle(log_id):
    delay = None
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if not state or not state.get("complete"):
            return
        if state.get("connections", 0) > 0:
            delay = STREAM_IDLE_CLEANUP_SECONDS
        else:
            finished_at = state.get("finished_at") or time.time()
            age = time.time() - finished_at
            if age >= STREAM_IDLE_CLEANUP_SECONDS:
                ACTIVE_STREAMS.pop(log_id, None)
                return
            delay = max(1, STREAM_IDLE_CLEANUP_SECONDS - age)
    if delay is not None:
        _schedule_stream_cleanup(log_id, delay)


def _ensure_stream(log_id):
    if not log_id:
        return None
    _validate_log_id(log_id)
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if state is None:
            state = _new_stream_state()
            ACTIVE_STREAMS[log_id] = state
        return state


def _write_stream_event(log_id, event):
    if not log_id:
        return
    event = _redact_for_log(event)
    event_json = json.dumps(event, ensure_ascii=False)
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if state is None:
            state = _new_stream_state()
            ACTIVE_STREAMS[log_id] = state
        seq = state["next_seq"]
        state["next_seq"] = seq + 1
        state["events"].append((seq, event_json))


def _write_line(log_id, line_type, text):
    _write_stream_event(log_id, {"type": line_type, "text": text})


def _close_stream(log_id, exit_code, duration):
    if not log_id:
        return
    _write_stream_event(
        log_id,
        {"type": "complete", "exit_code": exit_code, "duration": duration},
    )
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if state:
            state["complete"] = True
            state["finished_at"] = time.time()
    _schedule_stream_cleanup(log_id)


def _reserve_stream_log_id(agent_name="agent"):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "_", agent_name or "agent")
    for counter in range(1000):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{counter}" if counter else ""
        log_id = f"{stamp}_{safe_agent}{suffix}"
        path = _log_path_for_id(log_id)
        with _streams_lock:
            if log_id not in ACTIVE_STREAMS and not path.exists():
                ACTIVE_STREAMS[log_id] = _new_stream_state()
                return log_id
        time.sleep(0.001)
    raise RuntimeError("failed to reserve agent log_id")


def _stream_exists(log_id):
    with _streams_lock:
        return log_id in ACTIVE_STREAMS


def _open_stream_connection(log_id):
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if not state:
            return False
        state["connections"] += 1
        return True


def _release_stream_connection(log_id):
    should_cleanup = False
    with _streams_lock:
        state = ACTIVE_STREAMS.get(log_id)
        if state:
            state["connections"] = max(0, state.get("connections", 0) - 1)
            should_cleanup = bool(state.get("complete") and state["connections"] == 0)
    if should_cleanup:
        _schedule_stream_cleanup(log_id)


def _format_sse(event):
    if isinstance(event, str):
        payload = event
    else:
        payload = json.dumps(event, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _completed_log_events(log_id):
    path = _log_path_for_id(log_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        return [
            {"type": "stderr", "text": f"Failed to read agent log: {exc}\n"},
            {"type": "complete", "exit_code": -1, "duration": 0},
        ]

    events = []
    stdout = record.get("stdout")
    stderr = record.get("stderr")
    if stdout is not None or stderr is not None:
        for line in (stdout or "").splitlines(keepends=True):
            events.append({"type": "stdout", "text": line})
        for line in (stderr or "").splitlines(keepends=True):
            events.append({"type": "stderr", "text": line})
    else:
        for line in (record.get("output") or "").splitlines(keepends=True):
            events.append({"type": "stdout", "text": line})

    files_modified = record.get("files_modified", [])
    if not isinstance(files_modified, list):
        files_modified = []
    events.append({"type": "files_modified", "files": files_modified})
    events.append({
        "type": "complete",
        "exit_code": record.get("exit_code"),
        "duration": record.get("duration_seconds", record.get("duration", 0)),
    })
    return events


def stream_agent_output(log_id):
    log_id = _validate_log_id(log_id)

    def generate():
        connected = _open_stream_connection(log_id)
        if not connected:
            events = _completed_log_events(log_id)
            if events is None:
                yield _format_sse({"type": "stderr", "text": "stream not found\n"})
                yield _format_sse({"type": "complete", "exit_code": -1, "duration": 0})
                return
            for event in events:
                yield _format_sse(event)
            return

        last_seq = -1
        try:
            while True:
                with _streams_lock:
                    state = ACTIVE_STREAMS.get(log_id)
                    entries = list(state["events"]) if state else []

                if not state:
                    return

                for seq, entry_json in entries:
                    if seq <= last_seq:
                        continue
                    yield _format_sse(entry_json)
                    last_seq = seq
                    try:
                        parsed = json.loads(entry_json)
                    except json.JSONDecodeError:
                        parsed = {}
                    if parsed.get("type") == "complete":
                        return
                time.sleep(0.1)
        finally:
            _release_stream_connection(log_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _norm_path(path):
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except (OSError, RuntimeError, ValueError) as exc:
        _debug_failure("agent path normalization", exc)
        return os.path.normcase(str(path))


def _dedupe_paths(paths):
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        key = _norm_path(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(str(path))
    return result


def _path_priority(path):
    suffix = Path(path).suffix.lower()
    priority = {".exe": 0, ".cmd": 1, ".bat": 2, "": 3, ".ps1": 4}
    return priority.get(suffix, 5)


def _is_batch_wrapper(path):
    return Path(path).suffix.lower() in {".cmd", ".bat"}


def _where_candidates(binary):
    candidates = []
    try:
        result = subprocess.run(
            ["where.exe", binary],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if result.returncode == 0:
            candidates.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError) as exc:
        _debug_failure("agent where.exe lookup", exc)
    return candidates


def _command_candidates(spec):
    known_existing = [
        path for path in _dedupe_paths(spec.known_paths)
        if Path(path).exists() and (spec.supports_stdin or not _is_batch_wrapper(path))
    ]
    path_candidates = []
    for binary in spec.binaries:
        found = shutil.which(binary)
        if found:
            path_candidates.append(found)
        path_candidates.extend(_where_candidates(binary))
    known_keys = {_norm_path(path) for path in known_existing}
    path_existing = [
        path for path in _dedupe_paths(path_candidates)
        if (
            Path(path).exists()
            and _norm_path(path) not in known_keys
            and (spec.supports_stdin or not _is_batch_wrapper(path))
        )
    ]
    return sorted(known_existing, key=_path_priority) + sorted(path_existing, key=_path_priority)


def _read_version(cmd, spec):
    try:
        result = subprocess.run(
            [cmd, *spec.version_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = (result.stdout or result.stderr or "").strip()
        if output:
            return output.splitlines()[0][:200]
        if result.returncode == 0:
            return "available"
    except Exception as exc:
        return f"version check failed: {type(exc).__name__}"
    return None


def _detect_agents_unlocked():
    agents = {}
    default_agent = None
    for name, spec in AGENT_SPECS.items():
        candidates = _command_candidates(spec)
        if candidates:
            cmd = candidates[0]
            version = _read_version(cmd, spec)
            agents[name] = {
                "available": True,
                "cmd": cmd,
                "version": version or "unknown",
                "supports_stdin": spec.supports_stdin,
            }
            if default_agent is None:
                default_agent = name
        else:
            agents[name] = {
                "available": False,
                "reason": "not found on PATH or known locations",
                "supports_stdin": spec.supports_stdin,
            }
    return agents, default_agent


def refresh_agent_cache():
    global AGENT_CACHE, DEFAULT_AGENT
    with AGENT_DETECTION_LOCK:
        AGENT_CACHE, DEFAULT_AGENT = _detect_agents_unlocked()
        return AGENT_CACHE.copy(), DEFAULT_AGENT


def _agent_status(refresh=False):
    global AGENT_CACHE, DEFAULT_AGENT
    with AGENT_DETECTION_LOCK:
        if refresh or not AGENT_CACHE:
            AGENT_CACHE, DEFAULT_AGENT = _detect_agents_unlocked()
        return json.loads(json.dumps(AGENT_CACHE)), DEFAULT_AGENT


def _allowed_workdir_roots():
    roots = [COAGENT_DIR]
    configured = os.environ.get("HERMES_AGENT_WORKDIR_ROOTS", "")
    for raw in configured.split(os.pathsep):
        raw = raw.strip().strip('"')
        if raw:
            roots.append(Path(raw))
    resolved = []
    for root in roots:
        try:
            resolved.append(Path(root).expanduser().resolve())
        except (OSError, RuntimeError) as exc:
            _debug_failure("agent safe root resolution", exc)
            continue
    return resolved


def _is_within(path, root):
    try:
        common = os.path.commonpath([
            os.path.normcase(str(Path(path).resolve())),
            os.path.normcase(str(Path(root).resolve())),
        ])
        return common == os.path.normcase(str(Path(root).resolve()))
    except ValueError:
        return False
    except (OSError, RuntimeError) as exc:
        _debug_failure("agent safe root check", exc)
        return False


def _resolve_workdir(raw_workdir):
    if raw_workdir in (None, ""):
        path = COAGENT_DIR
    elif isinstance(raw_workdir, str):
        path = Path(raw_workdir).expanduser()
        if not path.is_absolute():
            path = COAGENT_DIR / path
    else:
        raise ValueError("workdir must be a string")
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"workdir does not exist or is not a directory: {raw_workdir}")
    roots = _allowed_workdir_roots()
    if not any(_is_within(resolved, root) for root in roots):
        allowed = [str(root) for root in roots]
        raise ValueError("workdir is outside allowed roots")
    return resolved


def _resolve_target_path(raw_path, workdir):
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("paths entries must be non-empty strings")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = workdir / path
    resolved = path.resolve()
    roots = _allowed_workdir_roots()
    if not any(_is_within(resolved, root) for root in roots):
        raise ValueError(f"path is outside allowed roots: {raw_path}")
    return resolved


def _validate_prompt(prompt, field="prompt"):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{field} is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"{field} exceeds {MAX_PROMPT_CHARS} characters")
    return prompt


def _validate_agent_name(agent_name):
    if agent_name in (None, ""):
        return None
    if not isinstance(agent_name, str):
        raise ValueError("agent must be a string")
    normalized = agent_name.strip().lower()
    if normalized not in AGENT_SPECS:
        raise ValueError("agent must be one of: codex, claude, gemini, opencode")
    return normalized


def _validate_model(model):
    if model in (None, ""):
        return None
    if not isinstance(model, str):
        raise ValueError("model must be a string")
    model = model.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:/@+\-]{1,120}", model):
        raise ValueError("model contains unsupported characters")
    return model


def _validate_timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(float(value))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("timeout must be a number")
    return min(MAX_TIMEOUT_SECONDS, max(1, timeout))


def _validate_focus(value):
    if value is None:
        return "all"
    if not isinstance(value, str):
        raise ValueError("focus must be one of: security, quality, all")
    focus = value.strip().lower()
    if focus not in {"security", "quality", "all"}:
        raise ValueError("focus must be one of: security, quality, all")
    return focus


def _validate_context(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("context must be a string")
    if len(value) > MAX_PROMPT_CHARS:
        raise ValueError(f"context exceeds {MAX_PROMPT_CHARS} characters")
    return value


def _snapshot_files(workdir):
    snapshot = {}
    for root, dirs, files in os.walk(workdir, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for filename in files:
            if filename in SKIP_FILES:
                continue
            path = Path(root) / filename
            try:
                rel = str(path.relative_to(workdir)).replace("\\", "/")
                stat = path.stat()
                snapshot[rel] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
            except ValueError:
                continue
    return snapshot


def _changed_files(before, after):
    changed = []
    for rel, fingerprint in after.items():
        if rel not in before or before[rel] != fingerprint:
            changed.append(rel)
    for rel in before:
        if rel not in after:
            changed.append(rel)
    return sorted(set(changed))


def _truncate_output(stdout, stderr):
    output = stdout or ""
    if stderr:
        if output:
            output += "\n"
        output += "[stderr]\n" + stderr
    truncated = False
    if len(output) > MAX_OUTPUT_CHARS:
        truncated = True
        omitted = len(output) - MAX_OUTPUT_CHARS
        output = output[:MAX_OUTPUT_CHARS] + f"\n...[truncated {omitted} characters]"
    return output, truncated


def _read_limited_text(path, max_bytes):
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
        truncated = size > max_bytes
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
        if truncated:
            text += f"\n...[stream truncated at {max_bytes} bytes]"
        return text, truncated
    except FileNotFoundError:
        return "", False


def _kill_process_tree(pid):
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
            return
        except (OSError, subprocess.SubprocessError) as exc:
            _debug_failure("agent taskkill termination", exc)
    try:
        os.kill(pid, 9)
    except OSError as exc:
        _debug_failure("agent os.kill termination", exc)


def _execution_lock_for(workdir_path):
    key = _norm_path(workdir_path)
    with EXECUTION_LOCKS_LOCK:
        lock = EXECUTION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            EXECUTION_LOCKS[key] = lock
        return lock


def _pump_pipe(pipe, path, log_id, line_type):
    try:
        with path.open("w", encoding="utf-8", errors="replace", newline="") as handle:
            for line in iter(pipe.readline, ""):
                if line == "":
                    break
                handle.write(line)
                handle.flush()
                _write_line(log_id, line_type, line)
    finally:
        try:
            pipe.close()
        except OSError as exc:
            _debug_failure("agent pipe close", exc)


def _append_temp_line(path, text):
    if not path:
        return
    try:
        with path.open("a", encoding="utf-8", errors="replace", newline="") as handle:
            handle.write(text)
    except OSError:
        pass


def _run_command(command, prompt_input, timeout, workdir_path, env, log_id=None):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = None
    stderr_path = None
    stdout_text = ""
    stderr_text = ""
    stdout_truncated = False
    stderr_truncated = False
    timed_out = False
    exit_code = -1
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0

    try:
        stdin_target = subprocess.PIPE if prompt_input is not None else subprocess.DEVNULL
        proc = subprocess.Popen(
            command,
            stdin=stdin_target,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workdir_path),
            env=env,
            creationflags=creationflags,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        stdout_path = LOG_DIR / f"STDOUT_{proc.pid}.tmp"
        stderr_path = LOG_DIR / f"STDERR_{proc.pid}.tmp"
        stdout_thread = threading.Thread(
            target=_pump_pipe,
            args=(proc.stdout, stdout_path, log_id, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_pump_pipe,
            args=(proc.stderr, stderr_path, log_id, "stderr"),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        if prompt_input is not None and proc.stdin:
            # Feed stdin from a daemon thread so a child that never reads its
            # stdin cannot block the main thread on a full pipe buffer before
            # the wait(timeout=...) guard below is reached.
            def _feed_stdin(stream, data):
                try:
                    stream.write(data)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        stream.close()
                    except (BrokenPipeError, OSError):
                        pass

            threading.Thread(
                target=_feed_stdin, args=(proc.stdin, prompt_input), daemon=True
            ).start()

        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError as exc:
                    _debug_failure("agent process kill after timeout", exc)
                try:
                    proc.wait(timeout=5)
                except subprocess.SubprocessError as exc:
                    _debug_failure("agent process wait after kill", exc)
            exit_code = -1
        finally:
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
    finally:
        if timed_out:
            timeout_line = f"Timed out after {timeout} seconds\n"
            _append_temp_line(stderr_path, timeout_line)
            _write_line(log_id, "stderr", timeout_line)
        if stdout_path:
            stdout_text, stdout_truncated = _read_limited_text(stdout_path, MAX_OUTPUT_CHARS)
        if stderr_path:
            stderr_text, stderr_truncated = _read_limited_text(stderr_path, MAX_OUTPUT_CHARS)
        for path in (stdout_path, stderr_path):
            if path:
                try:
                    path.unlink()
                except OSError:
                    pass

    return stdout_text, stderr_text, exit_code, timed_out, stdout_truncated or stderr_truncated


def _build_command(agent_name, cmd_path, prompt, model, read_only=False):
    spec = AGENT_SPECS[agent_name]
    if _is_batch_wrapper(cmd_path) and not spec.supports_stdin:
        # A .bat/.cmd is executed via cmd.exe, which reparses argv — passing a
        # prompt on the command line would reopen the BatBadBut (CVE-2024-1874)
        # vector. Batch shims are only ever selected when the prompt is
        # stdin-routed; assert that invariant defensively.
        raise ValueError("batch wrapper requires stdin-routed prompt (BatBadBut guard)")
    command = [cmd_path, *spec.base_args]
    if read_only:
        command.extend(spec.read_only_args)
    if model:
        command.extend([spec.model_flag, model])
    if not spec.supports_stdin:
        command.extend(spec.prompt_prefix_args)
        command.append(prompt)
    return command


def _next_log_path(agent_name):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "_", agent_name)
    # Reject names that survive as ".", "..", empty, or dot/dash-only — they
    # could become path-traversal or dotfile-collision landmines on refactor.
    if not safe_agent or safe_agent in (".", "..") or set(safe_agent) <= {".", "-", "_"}:
        safe_agent = "agent"
    path = LOG_DIR / f"{stamp}_{safe_agent}.json"
    counter = 1
    while path.exists():
        path = LOG_DIR / f"{stamp}_{safe_agent}_{counter}.json"
        counter += 1
    return path


_REDACT_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{15,}"), "sk-[REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(api[_-]?key\s*[:=]\s*)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1[REDACTED]"),
]
_REDACT_KEY_RE = re.compile(r"^(authorization|bearer|token|api[_-]?key|secret)$", re.IGNORECASE)


def _redact_text(text):
    redacted = text
    for pattern, replacement in _REDACT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _redact_for_log(value, key=None):
    if isinstance(value, str):
        if key and _REDACT_KEY_RE.search(str(key)):
            return "[REDACTED]" if value else value
        return _redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_for_log(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_for_log(item) for item in value)
    return value


def _write_log(record, log_id=None):
    with LOG_WRITE_LOCK:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if log_id:
            path = _log_path_for_id(log_id)
        else:
            path = _next_log_path(record.get("agent", "agent"))
            log_id = path.stem
        record = _redact_for_log({**record, "log_id": log_id})
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return log_id


def _execute_agent(
    prompt,
    agent_name=None,
    model=None,
    timeout=None,
    workdir=None,
    purpose="exec",
    read_only=False,
    log_id=None,
):
    if log_id:
        log_id = _validate_log_id(log_id)
    prompt = _validate_prompt(prompt)
    selected = _validate_agent_name(agent_name)
    model = _validate_model(model)
    timeout = _validate_timeout(timeout)
    workdir_path = _resolve_workdir(workdir)

    agents, default_agent = _agent_status()
    if selected is None:
        selected = default_agent
    if not selected:
        raise RuntimeError("no supported agents are available")
    if read_only and not AGENT_SPECS[selected].read_only_args:
        raise RuntimeError(f"agent '{selected}' does not support enforced read-only execution")

    agent_info = agents.get(selected) or {}
    if not agent_info.get("available"):
        reason = agent_info.get("reason", "not available")
        raise RuntimeError(f"agent '{selected}' is not available: {reason}")

    cmd_path = agent_info.get("cmd")
    command = _build_command(selected, cmd_path, prompt, model, read_only=read_only)

    env = os.environ.copy()
    # Defense-in-depth: don't leak unrelated secrets to the child agent. Keep
    # AI-provider keys (the agent needs its own) but strip other credential
    # families that a compromised/verbose agent could otherwise read.
    _UNRELATED_SECRET_KEYS = {
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN",
        "DOCKER_PASSWORD", "DOCKER_AUTH_CONFIG", "SLACK_TOKEN", "SLACK_WEBHOOK",
        "DISCORD_TOKEN", "TELEGRAM_BOT_TOKEN", "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID",
        "STRIPE_SECRET_KEY", "STRIPE_API_KEY", "SHOPIFY_API_SECRET", "SHOPIFY_ACCESS_TOKEN",
        "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY", "KALSHI_API_SECRET", "KALSHI_PRIVATE_KEY",
    }
    for _k in list(env.keys()):
        if _k.upper() in _UNRELATED_SECRET_KEYS:
            env.pop(_k, None)
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    if log_id:
        _write_stream_event(
            log_id,
            {
                "type": "start",
                "log_id": log_id,
                "agent": selected,
                "purpose": purpose,
                "workdir": str(workdir_path),
            },
        )

    run_lock = _execution_lock_for(workdir_path)
    with run_lock:
        before = _snapshot_files(workdir_path)
        started = time.time()
        stdout = ""
        stderr = ""
        exit_code = -1
        timed_out = False
        stream_truncated = False

        _log(f"[agent] running {selected} purpose={purpose} cwd={workdir_path}")
        stdout, stderr, exit_code, timed_out, stream_truncated = _run_command(
            command=command,
            prompt_input=prompt if AGENT_SPECS[selected].supports_stdin else None,
            timeout=timeout,
            workdir_path=workdir_path,
            env=env,
            log_id=log_id,
        )
        duration = round(time.time() - started, 2)
        after = _snapshot_files(workdir_path)
        files_modified = _changed_files(before, after)
        if log_id:
            _write_stream_event(log_id, {"type": "files_modified", "files": files_modified})
        output, output_truncated = _truncate_output(stdout, stderr)
        output_truncated = output_truncated or stream_truncated
        read_only_violation = bool(read_only and files_modified)
        success = (exit_code == 0 and not timed_out and not read_only_violation)
        if read_only_violation:
            output = (
                output
                + ("\n" if output else "")
                + "[agent_gateway]\nRead-only execution modified files: "
                + ", ".join(files_modified)
            )

    response = {
        "success": success,
        "agent": selected,
        "output": output,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "files_modified": files_modified,
        "log_id": log_id or "",
        "read_only": read_only,
        "read_only_violation": read_only_violation,
    }
    record = {
        **response,
        "purpose": purpose,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "workdir": str(workdir_path),
        "command": command[:-1] + ["<prompt>"] if not AGENT_SPECS[selected].supports_stdin else command,
        "model": model,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "output_truncated": output_truncated,
        "stdout": stdout,
        "stderr": stderr,
        "prompt": prompt,
        "read_only": read_only,
        "read_only_violation": read_only_violation,
    }
    try:
        response["log_id"] = _write_log(record, log_id=log_id)
    except Exception as exc:
        _console(f"[agent] failed to write log: {exc}")
    finally:
        if log_id:
            _close_stream(log_id, exit_code, duration)
    return response


def _status_code_for_result(result):
    if result.get("success"):
        return 200
    if result.get("exit_code") == -1:
        return 504
    return 500


def _stream_requested():
    return request.args.get("stream", "").lower() in {"1", "true", "yes", "sse"}


def _validate_exec_payload_for_background(data):
    provider = _provider_name_for_exec(data)
    if provider != "codex":
        raise ValueError("streaming/background execution is only supported for codex provider")
    _validate_prompt(data.get("prompt"))
    agent_name = _validate_agent_name(data.get("agent"))
    _validate_model(data.get("model"))
    _validate_timeout(data.get("timeout"))
    _resolve_workdir(data.get("workdir"))
    return agent_name


def _write_background_error_log(log_id, data, purpose, exc, duration, read_only=False):
    stderr = f"[agent_gateway] {type(exc).__name__}: {exc}\n"
    record = {
        "success": False,
        "agent": data.get("agent") or "",
        "output": "[stderr]\n" + stderr,
        "exit_code": -1,
        "duration_seconds": duration,
        "files_modified": [],
        "log_id": log_id,
        "read_only": read_only,
        "read_only_violation": False,
        "purpose": purpose,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "workdir": str(data.get("workdir") or COAGENT_DIR),
        "command": [],
        "model": data.get("model"),
        "timeout_seconds": data.get("timeout"),
        "timed_out": False,
        "output_truncated": False,
        "stdout": "",
        "stderr": stderr,
        "prompt": data.get("prompt") if isinstance(data.get("prompt"), str) else "",
    }
    try:
        _write_log(record, log_id=log_id)
    except Exception as log_exc:
        _console(f"[agent] failed to write background error log: {log_exc}")


def _execute_agent_payload(data, purpose, read_only=False, log_id=None):
    return _execute_agent(
        prompt=data.get("prompt"),
        agent_name=data.get("agent"),
        model=data.get("model"),
        timeout=data.get("timeout"),
        workdir=data.get("workdir"),
        purpose=purpose,
        read_only=read_only,
        log_id=log_id,
    )


def _start_background_agent(data, purpose="exec", read_only=False):
    agent_hint = _validate_exec_payload_for_background(data) or "agent"
    log_id = _reserve_stream_log_id(agent_hint)

    def runner():
        started = time.time()
        try:
            _execute_agent_payload(data, purpose=purpose, read_only=read_only, log_id=log_id)
        except Exception as exc:
            duration = round(time.time() - started, 2)
            stderr = f"[agent_gateway] {type(exc).__name__}: {exc}\n"
            _console(f"[agent] background {purpose} failed: {exc}")
            _write_line(log_id, "stderr", stderr)
            _write_stream_event(log_id, {"type": "files_modified", "files": []})
            _write_background_error_log(log_id, data, purpose, exc, duration, read_only=read_only)
            _close_stream(log_id, -1, duration)

    thread = threading.Thread(target=runner, name=f"agent-{purpose}-{log_id}", daemon=True)
    thread.start()
    return log_id


@agent_bp.route("/agent/status", methods=["GET"])
def route_agent_status():
    refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    agents, default_agent = _agent_status(refresh=refresh)
    return jsonify({"agents": agents, "default_agent": default_agent})


@agent_bp.route("/agent/providers/config", methods=["GET"])
def route_agent_provider_config():
    try:
        config = _load_provider_config()
        active_provider = _validate_provider_name(config.get("provider"))
        active_entry = _provider_entry(active_provider, config=config)
        providers = {
            provider: _masked_provider_entry(provider, _provider_entry(provider, config=config))
            for provider in sorted(SUPPORTED_PROVIDERS)
        }
        return jsonify({
            "provider": active_provider,
            "config_file": str(PROVIDER_CONFIG_FILE),
            "config": _masked_provider_entry(active_provider, active_entry),
            "providers": providers,
            "default_provider": "codex",
        })
    except Exception as exc:
        _console(f"[agent] provider config failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/providers/configure", methods=["POST"])
def route_agent_provider_configure():
    data = _json_payload()
    try:
        provider = _validate_provider_name(data.get("provider"))
        config = _load_provider_config()
        providers = config.setdefault("providers", {})
        entry = _provider_entry(provider, config=config)
        if "api_key" in data:
            api_key = _validate_api_key(data.get("api_key"))
            if api_key:
                entry["api_key"] = api_key
            else:
                entry.pop("api_key", None)
        if "model" in data:
            model = _validate_model(data.get("model")) if data.get("model") not in (None, "") else None
            if model:
                entry["model"] = model
            else:
                entry.pop("model", None)
        if "base_url" in data:
            base_url = _validate_base_url(data.get("base_url"))
            if base_url:
                entry["base_url"] = base_url
            else:
                entry.pop("base_url", None)
        providers[provider] = {
            key: value
            for key, value in entry.items()
            if key in {"api_key", "model", "base_url"} and value not in (None, "")
        }
        config["provider"] = provider
        _save_provider_config(config)
        return jsonify({
            "status": "configured",
            "provider": provider,
            "config_file": str(PROVIDER_CONFIG_FILE),
            "config": _masked_provider_entry(provider, providers[provider]),
        })
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] provider configure failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/providers/test", methods=["POST"])
def route_agent_provider_test():
    data = _json_payload()
    try:
        provider = _provider_name_for_exec(data)
        if provider == "codex":
            result = _execute_agent(
                prompt="Say hello",
                agent_name=data.get("agent"),
                model=data.get("model"),
                timeout=data.get("timeout"),
                workdir=data.get("workdir"),
                purpose="provider_test",
            )
            return jsonify({
                "success": result.get("success"),
                "provider": "codex",
                "message": {"role": "assistant", "content": result.get("output", "")},
                "output": result.get("output", ""),
                "log_id": result.get("log_id", ""),
            }), _status_code_for_result(result)
        payload = dict(data)
        payload["prompt"] = "Say hello"
        result = _execute_provider(payload, provider, purpose="provider_test")
        return jsonify(result), _status_code_for_result(result)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] provider test failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


_SKILLS_PROVIDER = None  # set in register_routes; see routes_skills.py


def _inject_skills(data):
    """Progressive-disclosure skill injection.

    If the request carries a ``skills`` field (list of skill names) and the
    skills loader (routes_skills.py) is installed, append the matching skill
    bodies to the prompt before dispatch. No-op when skills are absent.
    """
    provider = _SKILLS_PROVIDER
    if not provider or not isinstance(data, dict):
        return
    skill_names = data.get("skills")
    if not skill_names or not isinstance(skill_names, list):
        return
    render = provider.get("render")
    if not callable(render):
        return
    try:
        data["prompt"] = render(data.get("prompt"), skill_names)
    except Exception as exc:  # noqa: BLE001
        _console(f"[agent] skills injection failed: {exc}")


@agent_bp.route("/agent/exec", methods=["POST"])
def route_agent_exec():
    data = _json_payload()
    _inject_skills(data)
    try:
        provider = _provider_name_for_exec(data)
    except ValueError as exc:
        return _error(str(exc), 400)
    if _stream_requested():
        if provider != "codex":
            return _error("streaming is only supported for codex CLI provider", 400, provider=provider)
        try:
            log_id = _start_background_agent(data, purpose="exec")
            return stream_agent_output(log_id)
        except ValueError as exc:
            return _error(str(exc), 400)
        except Exception as exc:
            _console(f"[agent] exec stream failed: {exc}")
            return _error(str(exc), 500, type=type(exc).__name__)

    try:
        if provider != "codex":
            result = _execute_provider(data, provider, purpose="exec")
            return jsonify(result), _status_code_for_result(result)
        result = _execute_agent(
            prompt=data.get("prompt"),
            agent_name=data.get("agent"),
            model=data.get("model"),
            timeout=data.get("timeout"),
            workdir=data.get("workdir"),
            purpose="exec",
        )
        return jsonify(result), _status_code_for_result(result)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] exec failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/exec-stream", methods=["POST"])
def route_agent_exec_stream_start():
    data = _json_payload()
    try:
        provider = _provider_name_for_exec(data)
        if provider != "codex":
            return _error("exec-stream is only supported for codex CLI provider", 400, provider=provider)
        log_id = _start_background_agent(data, purpose="exec")
        return jsonify({
            "log_id": log_id,
            "stream_url": f"/agent/exec/stream/{log_id}",
        }), 202
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] exec-stream failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/exec/stream/<log_id>", methods=["GET"])
def route_agent_exec_stream(log_id):
    try:
        log_id = _validate_log_id(log_id)
    except ValueError as exc:
        return _error(str(exc), 400)
    if not _stream_exists(log_id) and not _log_path_for_id(log_id).exists():
        return _error("stream not found", 404, log_id=log_id)
    return stream_agent_output(log_id)


@agent_bp.route("/agent/audit", methods=["POST"])
def route_agent_audit():
    data = _json_payload()
    try:
        workdir = _resolve_workdir(data.get("workdir"))
        paths = data.get("paths", ["."])
        if not isinstance(paths, list) or not paths:
            return _error("paths must be a non-empty list")
        resolved_paths = [_resolve_target_path(path, workdir) for path in paths]
        missing = [str(path) for path in resolved_paths if not path.exists()]
        if missing:
            return _error("one or more paths do not exist", paths=missing)
        outside_workdir = [str(path) for path in resolved_paths if not _is_within(path, workdir)]
        if outside_workdir:
            return _error("audit paths must be inside workdir", paths=outside_workdir)
        focus = _validate_focus(data.get("focus", "all"))
        rel_paths = []
        for path in resolved_paths:
            try:
                rel_paths.append(str(path.relative_to(workdir)).replace("\\", "/"))
            except ValueError:
                rel_paths.append(str(path))
        prompt = (
            "Audit the following Hermes CoAgent paths with a "
            f"{focus} focus. Prioritize concrete bugs, security issues, "
            "behavior regressions, and missing tests. Lead with findings, "
            "include file and line references when available, and avoid "
            "unrelated refactors. Do not modify files.\n\nPaths:\n"
            + "\n".join(f"- {path}" for path in rel_paths)
        )
        result = _execute_agent(
            prompt=prompt,
            agent_name=data.get("agent"),
            model=data.get("model"),
            timeout=data.get("timeout"),
            workdir=str(workdir),
            purpose="audit",
            read_only=True,
        )
        return jsonify(result), _status_code_for_result(result)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] audit failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/plan", methods=["POST"])
def route_agent_plan():
    data = _json_payload()
    try:
        task = _validate_prompt(data.get("task"), field="task")
        context = _validate_context(data.get("context", ""))
        prompt = (
            "Create an implementation plan for this Hermes CoAgent task. "
            "Do not modify files. Be specific about files, endpoints, tests, "
            "risks, and verification commands.\n\nTask:\n"
            f"{task}\n\nContext:\n{context}"
        )
        result = _execute_agent(
            prompt=prompt,
            agent_name=data.get("agent"),
            model=data.get("model"),
            timeout=data.get("timeout"),
            workdir=data.get("workdir"),
            purpose="plan",
            read_only=True,
        )
        return jsonify(result), _status_code_for_result(result)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] plan failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/implement", methods=["POST"])
def route_agent_implement():
    data = _json_payload()
    try:
        task = _validate_prompt(data.get("task"), field="task")
        context = _validate_context(data.get("context", ""))
        prompt = (
            "Implement this Hermes CoAgent task directly in the working "
            "directory. Apply changes only when they are required, keep the "
            "scope tight, then summarize changed files and verification.\n\n"
            f"Task:\n{task}\n\nContext:\n{context}"
        )
        result = _execute_agent(
            prompt=prompt,
            agent_name=data.get("agent"),
            model=data.get("model"),
            timeout=data.get("timeout"),
            workdir=data.get("workdir"),
            purpose="implement",
        )
        return jsonify(result), _status_code_for_result(result)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        _console(f"[agent] implement failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


@agent_bp.route("/agent/logs", methods=["GET"])
def route_agent_logs():
    try:
        limit_raw = request.args.get("limit", "20")
        try:
            limit = min(100, max(1, int(limit_raw)))
        except (TypeError, ValueError):
            limit = 20
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logs = []
        for path in sorted(LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            item = {
                "log_id": path.stem,
                "path": str(path),
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                "size": path.stat().st_size,
            }
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                item.update({
                    "agent": data.get("agent"),
                    "purpose": data.get("purpose"),
                    "success": data.get("success"),
                    "exit_code": data.get("exit_code"),
                    "duration_seconds": data.get("duration_seconds"),
                    "files_modified": data.get("files_modified", []),
                })
            except Exception as exc:
                item["error"] = f"failed to read log: {exc}"
            logs.append(item)
        return jsonify({"logs": logs, "count": len(logs)})
    except Exception as exc:
        _console(f"[agent] logs failed: {exc}")
        return _error(str(exc), 500, type=type(exc).__name__)


def register_routes(app, state, require_auth):
    global _SKILLS_PROVIDER
    _SKILLS_PROVIDER = getattr(state, "skills", None)
    app.register_blueprint(agent_bp)
    _wrap_registered_blueprint_routes(app, agent_bp.name, require_auth)
    state.agent_gateway = {
        "agents": AGENT_CACHE,
        "default_agent": DEFAULT_AGENT,
        "log_dir": str(LOG_DIR),
        "provider_config": str(PROVIDER_CONFIG_FILE),
        "providers": sorted(SUPPORTED_PROVIDERS),
    }


try:
    refresh_agent_cache()
except Exception as exc:
    _console(f"[agent] initial detection failed: {exc}")
