import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_agent
from routes_agent import AgentSpec


def test_args_mode_agents_do_not_use_batch_wrappers(tmp_path, monkeypatch):
    cmd_path = tmp_path / "agent.cmd"
    cmd_path.write_text("@echo off\n", encoding="utf-8")
    spec = AgentSpec("agent", ("agent",), (str(cmd_path),), supports_stdin=False)

    monkeypatch.setattr(routes_agent.shutil, "which", lambda _binary: None)
    monkeypatch.setattr(routes_agent, "_where_candidates", lambda _binary: [])

    assert routes_agent._command_candidates(spec) == []


def test_stdin_agents_can_use_batch_wrappers(tmp_path, monkeypatch):
    cmd_path = tmp_path / "agent.cmd"
    cmd_path.write_text("@echo off\n", encoding="utf-8")
    spec = AgentSpec("agent", ("agent",), (str(cmd_path),), supports_stdin=True)

    monkeypatch.setattr(routes_agent.shutil, "which", lambda _binary: None)
    monkeypatch.setattr(routes_agent, "_where_candidates", lambda _binary: [])

    assert routes_agent._command_candidates(spec) == [str(cmd_path)]


def test_read_only_command_args_are_applied():
    assert routes_agent._build_command("codex", "codex", "prompt", None, read_only=True) == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
    ]
    assert routes_agent._build_command("claude", "claude", "prompt", None, read_only=True) == [
        "claude",
        "--permission-mode",
        "plan",
        "--disallowedTools",
        "Edit,Write,MultiEdit,NotebookEdit",
        "-p",
        "prompt",
    ]


def test_read_only_unsupported_agent_fails_closed():
    try:
        routes_agent._execute_agent("test", agent_name="gemini", read_only=True, timeout=1)
    except RuntimeError as exc:
        assert "does not support enforced read-only execution" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_audit_paths_must_stay_inside_workdir(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    outside = tmp_path / "outside.py"
    workdir.mkdir()
    outside.write_text("print('outside')\n", encoding="utf-8")

    monkeypatch.setattr(routes_agent, "_allowed_workdir_roots", lambda: [tmp_path.resolve()])
    monkeypatch.setattr(
        routes_agent,
        "_execute_agent",
        lambda **_kwargs: {
            "success": True,
            "agent": "codex",
            "output": "",
            "exit_code": 0,
            "duration_seconds": 0,
            "files_modified": [],
            "log_id": "test",
        },
    )

    app = Flask(__name__)

    class State:
        pass

    routes_agent.register_routes(app, State(), lambda fn: fn)
    client = app.test_client()

    res = client.post(
        "/agent/audit",
        json={"workdir": str(workdir), "paths": [str(outside)], "focus": "quality"},
    )

    assert res.status_code == 400
    assert res.get_json()["error"] == "audit paths must be inside workdir"
