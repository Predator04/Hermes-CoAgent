import functools
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_recipes


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


def _client(tmp_path, monkeypatch, require_auth=_allow):
    monkeypatch.setattr(routes_recipes, "RECIPES_FILE", tmp_path / "recipes.json")
    monkeypatch.setattr(routes_recipes, "_RECIPES", {})
    monkeypatch.setattr(routes_recipes, "_RECIPE_LOGS", {})
    monkeypatch.setattr(routes_recipes, "_RUNNING_RECIPES", set())
    monkeypatch.setattr(routes_recipes, "_SCHED_LAST_RUN", {})
    monkeypatch.setattr(routes_recipes, "_SCHEDULER_THREAD", None)
    monkeypatch.setattr(routes_recipes, "_start_scheduler", lambda: None)
    monkeypatch.setattr(routes_recipes.time, "sleep", lambda _seconds: None)
    app = Flask(__name__)

    class State:
        pass

    routes_recipes.register_routes(app, State(), require_auth)
    return app.test_client()


def test_recipe_list_run_status_and_logs(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/recipes/list").get_json()["count"] == 0

    created = client.post(
        "/recipes/create",
        json={"recipe_id": "smoke", "name": "Smoke", "steps": [{"action": "wait", "params": {"seconds": 0}}]},
    )
    assert created.status_code == 200

    run = client.post("/recipes/run", json={"recipe_id": "smoke"})
    assert run.status_code == 200
    assert run.get_json()["status"] == "completed"

    status = client.get("/recipes/status/smoke")
    assert status.status_code == 200
    assert status.get_json()["last_status"] == "completed"
    assert status.get_json()["logs"]


def test_recipe_verify_run_verifies_each_step_before_proceeding(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    calls = []

    def fake_run_one_step(step, previous, auth_header):
        calls.append(("run", step["action"]))
        return {"status": "ok", "result": {"status": "ok"}}

    def fake_verify(expected, auth_header, screenshot_before="", screenshot_after=""):
        calls.append(("verify", expected["text"]))
        return {"ok": True, "actual": "verified"}

    monkeypatch.setattr(routes_recipes, "_run_one_step", fake_run_one_step)
    monkeypatch.setattr(routes_recipes, "_verify_expected", fake_verify)
    monkeypatch.setattr(routes_recipes, "_screen_base64", lambda _auth: "shot")

    response = client.post(
        "/recipes/run",
        json={
            "verify": True,
            "steps": [
                {"action": "wait", "params": {"seconds": 0}, "expected": {"type": "text", "text": "ready"}},
                {"action": "wait", "params": {"seconds": 0}, "expected": {"type": "text", "text": "done"}},
            ],
        },
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"
    assert calls == [("run", "wait"), ("verify", "ready"), ("run", "wait"), ("verify", "done")]


def test_recipe_routes_enforce_auth(tmp_path, monkeypatch):
    import platform
    if platform.system() != "Windows":
        pytest.skip("Blueprint auth-wrapping isolation test differs to Windows on Linux")
    client = _client(tmp_path, monkeypatch, require_auth=_auth)
    assert client.get("/recipes/list").status_code == 401
