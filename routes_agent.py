"""Agent gateway routes for invoking allowlisted local AI agent CLIs."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _log


agent_bp = Blueprint("agent_gateway", __name__)

MAX_PROMPT_CHARS = 100 * 1024
MAX_OUTPUT_CHARS = 500 * 1024
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 1800
LOG_DIR = COAGENT_DIR / "agent_logs"

AGENT_DETECTION_LOCK = threading.Lock()
LOG_WRITE_LOCK = threading.Lock()
EXECUTION_LOCKS_LOCK = threading.Lock()
EXECUTION_LOCKS = {}
AGENT_CACHE = {}
DEFAULT_AGENT = None

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
        known_paths=(
            r"C:\Users\Admin\AppData\Roaming\npm\codex.cmd",
            r"C:\Users\Admin\AppData\Roaming\npm\codex.exe",
            r"C:\Users\Admin\AppData\Roaming\npm\codex",
        ),
        supports_stdin=True,
        base_args=("exec",),
        read_only_args=("--sandbox", "read-only"),
        model_flag="--model",
    ),
    "claude": AgentSpec(
        name="claude",
        binaries=("claude",),
        known_paths=(
            r"C:\Users\Admin\.local\bin\claude.exe",
            r"C:\Users\Admin\AppData\Roaming\npm\claude.cmd",
            r"C:\Users\Admin\AppData\Roaming\npm\claude.exe",
        ),
        supports_stdin=False,
        prompt_prefix_args=("-p",),
        read_only_args=("--permission-mode", "plan", "--disallowedTools", "Edit,Write,MultiEdit,NotebookEdit"),
        model_flag="--model",
    ),
    "gemini": AgentSpec(
        name="gemini",
        binaries=("gemini",),
        known_paths=(
            r"C:\Users\Admin\AppData\Roaming\npm\gemini.cmd",
            r"C:\Users\Admin\AppData\Roaming\npm\gemini.exe",
        ),
        supports_stdin=True,
        model_flag="--model",
    ),
    "opencode": AgentSpec(
        name="opencode",
        binaries=("opencode",),
        known_paths=(
            r"C:\Users\Admin\AppData\Roaming\npm\opencode.cmd",
            r"C:\Users\Admin\AppData\Roaming\npm\opencode.exe",
            r"C:\Users\Admin\.local\bin\opencode.exe",
        ),
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
    except Exception:
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
    except Exception:
        pass
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
        except Exception:
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
    except Exception:
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
        except Exception:
            pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


def _execution_lock_for(workdir_path):
    key = _norm_path(workdir_path)
    with EXECUTION_LOCKS_LOCK:
        lock = EXECUTION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            EXECUTION_LOCKS[key] = lock
        return lock


def _run_command(command, prompt_input, timeout, workdir_path, env):
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

    with tempfile.NamedTemporaryFile(prefix="agent_stdout_", suffix=".tmp", dir=LOG_DIR, delete=False) as stdout_file:
        stdout_path = Path(stdout_file.name)
    with tempfile.NamedTemporaryFile(prefix="agent_stderr_", suffix=".tmp", dir=LOG_DIR, delete=False) as stderr_file:
        stderr_path = Path(stderr_file.name)

    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            stdin_target = subprocess.PIPE if prompt_input is not None else subprocess.DEVNULL
            proc = subprocess.Popen(
                command,
                stdin=stdin_target,
                stdout=stdout_handle,
                stderr=stderr_handle,
                cwd=str(workdir_path),
                env=env,
                creationflags=creationflags,
            )
            try:
                stdin_bytes = prompt_input.encode("utf-8") if prompt_input is not None else None
                proc.communicate(input=stdin_bytes, timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_tree(proc.pid)
                try:
                    proc.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.communicate(timeout=5)
                    except Exception:
                        pass
                exit_code = -1
    finally:
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

    if timed_out:
        stderr_text = (stderr_text + "\n" if stderr_text else "") + f"Timed out after {timeout} seconds"
    return stdout_text, stderr_text, exit_code, timed_out, stdout_truncated or stderr_truncated


def _build_command(agent_name, cmd_path, prompt, model, read_only=False):
    spec = AGENT_SPECS[agent_name]
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
    path = LOG_DIR / f"{stamp}_{safe_agent}.json"
    counter = 1
    while path.exists():
        path = LOG_DIR / f"{stamp}_{safe_agent}_{counter}.json"
        counter += 1
    return path


def _write_log(record):
    with LOG_WRITE_LOCK:
        path = _next_log_path(record.get("agent", "agent"))
        log_id = path.stem
        record = {**record, "log_id": log_id}
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return log_id


def _execute_agent(prompt, agent_name=None, model=None, timeout=None, workdir=None, purpose="exec", read_only=False):
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
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

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
        )
        duration = round(time.time() - started, 2)
        after = _snapshot_files(workdir_path)
        files_modified = _changed_files(before, after)
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
        "log_id": "",
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
        "prompt": prompt,
        "read_only": read_only,
        "read_only_violation": read_only_violation,
    }
    try:
        response["log_id"] = _write_log(record)
    except Exception as exc:
        _console(f"[agent] failed to write log: {exc}")
    return response


def _status_code_for_result(result):
    if result.get("success"):
        return 200
    if result.get("exit_code") == -1:
        return 504
    return 500


@agent_bp.route("/agent/status", methods=["GET"])
def route_agent_status():
    refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    agents, default_agent = _agent_status(refresh=refresh)
    return jsonify({"agents": agents, "default_agent": default_agent})


@agent_bp.route("/agent/exec", methods=["POST"])
def route_agent_exec():
    data = _json_payload()
    try:
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
    _auth_blueprint(agent_bp, require_auth)
    app.register_blueprint(agent_bp)
    state.agent_gateway = {
        "agents": AGENT_CACHE,
        "default_agent": DEFAULT_AGENT,
        "log_dir": str(LOG_DIR),
    }


try:
    refresh_agent_cache()
except Exception as exc:
    _console(f"[agent] initial detection failed: {exc}")
