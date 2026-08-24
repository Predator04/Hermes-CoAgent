#!/usr/bin/env python3
"""One-shot CLI for Hermes CoAgent.

Runs a single natural-language computer-use goal headlessly:

    coagent "open Chrome, check my inbox, and summarize unread mail"

Starts (or attaches to) a local CoAgent server, drives the goal through the
goal-runner, streams progress to stderr, prints a structured JSON result to
stdout, and exits 0 (success) / 1 (failure) / 2 (timeout).

Flags:
    --goal TEXT         Goal to run (defaults to positional arg or stdin)
    --json              Emit final result as JSON (already the default)
    --timeout SECONDS   Overall run budget (default 300)
    --max-steps N       Maximum goal-runner steps (default 10)
    --approve           Opt into auto-approval for non-dangerous steps
    --dry-run           Print what would run without contacting the server
    --attach            Reuse an already-running server (do not spawn)
    --token TOKEN       Bearer token (else COAGENT_TOKEN env, else .token file)
    --port N            Server port to spawn/attach to (default 9123)
    --base-url URL      Full base URL override (default http://127.0.0.1:PORT)
    --model NAME        Model hint passed through to the goal-runner
    --agent NAME        Agent hint passed through to the goal-runner
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9123
DEFAULT_TIMEOUT = 300
DEFAULT_MAX_STEPS = 10
POLL_INTERVAL = 2.0

TERMINAL_STATUSES = {"completed", "failed", "stopped"}


def _eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def _find_token(explicit_token):
    """Resolve the bearer token from --token, env, or the .token file."""
    if explicit_token:
        return explicit_token
    env = os.environ.get("COAGENT_TOKEN")
    if env:
        return env.strip()
    candidates = [
        Path(__file__).resolve().parent / ".token",
        Path.cwd() / ".token",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                token = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if token:
                    return token
        except OSError:
            continue
    return None


def _request(base_url, method, path, token=None, payload=None, timeout=30):
    """Minimal urllib JSON request. Returns (status_code, parsed_body)."""
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        return 0, {"error": f"connection failed: {exc.reason}"}
    body = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {"_raw": body}
    return status, parsed


def _wait_for_server(base_url, timeout=45):
    """Poll /ping until the server responds. /ping is not auth-gated."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = _request(base_url, "GET", "/ping", timeout=3)
            if status == 200 and body.get("status") == "pong":
                return body
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _spawn_server(port):
    """Launch hermes_coagent.py --secure in the background and return the Popen."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    sibling = Path(__file__).resolve().parent / "hermes_coagent.py"
    commands = []
    if sibling.is_file():
        commands.append([sys.executable, str(sibling), "--secure", "--port", str(port)])
    commands.append([sys.executable, "-m", "hermes_coagent", "--secure", "--port", str(port)])
    last_err = None
    for cmd in commands:
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"could not spawn server: {last_err}")


def _read_goal(args):
    if args.goal:
        return args.goal.strip()
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            return text
    return None


def _progress_step(step):
    if not isinstance(step, dict):
        return
    status = step.get("status") or "pending"
    action = step.get("action") or "?"
    params = step.get("params")
    if isinstance(params, dict):
        params = json.dumps(params, default=str)
    else:
        params = str(params or "")
    if len(params) > 120:
        params = params[:120] + "..."
    _eprint(f"  [{status}] {action} {params}".rstrip())


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="coagent",
        description="Run a computer-use goal against a Hermes CoAgent server.",
    )
    parser.add_argument("goal", nargs="?", default=None, help="Natural-language goal to run")
    parser.add_argument("--goal", dest="goal_flag", default=None, help="Goal to run (alternative to positional)")
    parser.add_argument("--json", action="store_true", help="Emit final result as JSON")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Overall run budget in seconds")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="Max goal-runner steps")
    parser.add_argument("--approve", action="store_true", help="Opt into auto-approval for non-dangerous steps")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without executing")
    parser.add_argument("--attach", action="store_true", help="Reuse an already-running server")
    parser.add_argument("--token", default=None, help="Bearer token")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port (default 9123)")
    parser.add_argument("--base-url", default=None, help="Full base URL override")
    parser.add_argument("--model", default=None, help="Model hint passed to the goal-runner")
    parser.add_argument("--agent", default=None, help="Agent hint passed to the goal-runner")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    args.goal = args.goal or args.goal_flag
    goal = _read_goal(args)

    base_url = args.base_url or f"http://127.0.0.1:{args.port}"

    if not goal:
        _eprint("error: no goal provided (pass it positionally, via --goal, or on stdin)")
        return 1

    if args.dry_run:
        result = {
            "dry_run": True,
            "goal": goal,
            "base_url": base_url,
            "attach": args.attach,
            "max_steps": args.max_steps,
            "approve": args.approve,
            "model": args.model,
            "agent": args.agent,
        }
        print(json.dumps(result, indent=2))
        return 0

    token = _find_token(args.token)
    proc = None
    try:
        if not args.attach:
            # Reuse an already-running server if one is listening; otherwise spawn.
            existing = _wait_for_server(base_url, timeout=2)
            if existing is None:
                _eprint(f"starting CoAgent server on {base_url} ...")
                try:
                    proc = _spawn_server(args.port)
                except RuntimeError as exc:
                    _eprint(f"error: {exc}")
                    return 1
                ping = _wait_for_server(base_url, timeout=45)
                if ping is None:
                    _eprint("error: server did not become ready")
                    return 1
                _eprint(f"server ready: {ping.get('agent', 'coagent')}")
            else:
                _eprint(f"attached to running server: {existing.get('agent', 'coagent')}")
            # A freshly spawned --secure server writes a random token to .token.
            token = _find_token(None) or token

        payload = {"goal": goal, "max_steps": args.max_steps}
        if args.approve:
            payload["auto_approve"] = True
        if args.model:
            payload["model"] = args.model
        if args.agent:
            payload["agent"] = args.agent

        status, snapshot = _request(base_url, "POST", "/copilot/goal", token=token, payload=payload, timeout=30)
        if status >= 400 or not isinstance(snapshot, dict) or not snapshot.get("goal_id"):
            _eprint(f"error: failed to start goal (HTTP {status}): {json.dumps(snapshot, default=str)}")
            return 1

        goal_id = snapshot["goal_id"]
        _eprint(f"goal started: {goal_id}")

        deadline = time.time() + args.timeout
        last_sig = None
        last_gstatus = None
        while True:
            time.sleep(POLL_INTERVAL)
            status, snap = _request(base_url, "GET", f"/copilot/goal/{goal_id}", token=token, timeout=15)
            if status == 404:
                _eprint("error: goal disappeared from the server")
                return 1
            if not isinstance(snap, dict):
                continue
            gstatus = str(snap.get("status") or "")
            if gstatus != last_gstatus:
                _eprint(f"goal status: {gstatus}")
                last_gstatus = gstatus
            steps = snap.get("steps") or []
            if steps:
                last = steps[-1]
                sig = (len(steps), last.get("status"), last.get("action"))
                if sig != last_sig:
                    _progress_step(last)
                    last_sig = sig
            if gstatus in TERMINAL_STATUSES:
                break
            if time.time() >= deadline:
                _eprint(f"timeout reached after {args.timeout}s")
                out = dict(snap)
                out["timed_out"] = True
                print(json.dumps(out, indent=2, default=str))
                return 2

        print(json.dumps(snap, indent=2, default=str))
        return 0 if gstatus == "completed" else 1
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
