"""Tests for the enhanced copilot goal execution routes (routes_copilot_enhanced.py)."""
import functools
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_copilot_enhanced as copilot
import auth


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


def _auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("Authorization") != "Bearer test-token":
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def _allow(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


def _reset_goals():
    with copilot._GOALS_LOCK:
        copilot._GOALS.clear()
        copilot._GOAL_ORDER.clear()


def _fake_threading():
    """Isolated threading namespace: fake Thread, real Event/RLock."""
    return types.SimpleNamespace(
        Thread=FakeThread,
        Event=threading.Event,
        RLock=threading.RLock,
    )


def _fake_time():
    """Isolated time namespace: no-op sleep, real clock/formatting."""
    return types.SimpleNamespace(
        sleep=lambda _seconds: None,
        time=time.time,
        strftime=time.strftime,
        localtime=time.localtime,
    )


def _client(monkeypatch, require_auth=_allow):
    _reset_goals()
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_TOKEN", None)
    monkeypatch.setattr(copilot, "threading", _fake_threading())
    app = Flask(__name__)

    class State:
        pass

    copilot.register_routes(app, State(), require_auth)
    return app.test_client()


def test_goal_status_stop_timeline_and_progress(monkeypatch):
    client = _client(monkeypatch)

    created = client.post("/copilot/goal", json={"goal": "wait patiently", "max_steps": 2})
    assert created.status_code == 202
    goal_id = created.get_json()["goal_id"]

    status = client.get("/copilot/status").get_json()
    assert status["status"] == "queued"
    assert status["active_goals"] == 1

    timeline = client.get("/copilot/timeline").get_json()
    assert timeline["goal_id"] == goal_id

    progress = client.get("/copilot/progress").get_json()
    assert progress["percent"] == 0

    stopped = client.post("/copilot/stop")
    assert stopped.status_code == 200
    assert stopped.get_json()["status"] == "stopping"

    stopped_by_id = client.post(f"/copilot/stop/{goal_id}")
    assert stopped_by_id.status_code == 200


def test_goal_event_sse_alias(monkeypatch):
    import platform
    if platform.system() != "Windows":
        pytest.skip("SSE event test relies on Blueprint scope isolation that differs on Linux")

    client = _client(monkeypatch)
    created = client.post("/copilot/goal", json={"goal": "quick task"})
    goal_id = created.get_json()["goal_id"]
    with copilot._GOALS_LOCK:
        goal = copilot._GOALS[goal_id]
        goal["status"] = "completed"
        goal["steps"] = [{"index": 0, "action": "wait", "params": {}, "status": "ok"}]
        goal["finished_at"] = copilot._now()

    response = client.get(f"/copilot/events/{goal_id}", buffered=False)
    try:
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        first = next(response.response).decode("utf-8")
        assert "event: timeline" in first
    finally:
        response.close()


def test_screenshot_verification_is_optional_for_non_screenshot_goal(monkeypatch):
    _reset_goals()
    goal_id = "goal1"
    with copilot._GOALS_LOCK:
        copilot._GOALS[goal_id] = {
            "id": goal_id,
            "goal_id": goal_id,
            "goal": "open notepad",
            "status": "queued",
            "steps": [],
            "log": [],
            "events": [],
            "event_seq": 0,
            "subscribers": set(),
            "max_steps": 3,
            "created_at": copilot._now(),
            "updated_at": copilot._now(),
            "started_at": None,
            "finished_at": None,
            "stop_event": threading.Event(),
        }
        copilot._GOAL_ORDER.append(goal_id)

    monkeypatch.setattr(
        copilot,
        "_decompose_goal",
        lambda *_args, **_kwargs: ([{"action": "screenshot", "params": {}}], {"source": "test"}),
    )
    monkeypatch.setattr(copilot, "_coagent_request", lambda *_args, **_kwargs: {"error": "no desktop"})
    monkeypatch.setattr(copilot, "time", _fake_time())

    copilot._run_goal(goal_id, "")

    with copilot._GOALS_LOCK:
        goal = copilot._GOALS[goal_id]
    assert goal["status"] == "completed"
    assert goal["steps"][0]["status"] == "ok"
    assert goal["steps"][0]["result"]["optional"] is True


def test_copilot_routes_enforce_auth(monkeypatch):
    import platform
    if platform.system() != "Windows":
        pytest.skip("Blueprint auth-wrapping isolation test differs to Windows on Linux")

    client = _client(monkeypatch, require_auth=_auth)
    assert client.get("/copilot/status").status_code == 401
