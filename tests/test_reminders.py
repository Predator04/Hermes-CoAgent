"""Tests for the timed reminder and push alert routes (routes_reminders.py)."""
import functools
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_reminders


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
    monkeypatch.setattr(routes_reminders, "DB_FILE", tmp_path / "reminders.db")
    monkeypatch.setattr(routes_reminders, "_SCHEDULER_THREAD", None)
    monkeypatch.setattr(routes_reminders, "_start_scheduler", lambda: None)
    app = Flask(__name__)

    class State:
        pass

    routes_reminders.register_routes(app, State(), require_auth)
    return app.test_client()


def test_create_list_cancel_and_stats(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/reminders/create",
        json={"title": "Stretch", "message": "Stand up", "trigger_at": "in 5m", "deliver_to": "toast"},
    )
    assert created.status_code == 200
    reminder_id = created.get_json()["reminder"]["id"]

    listed = client.get("/reminders/list")
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1

    stats = client.get("/reminders/stats")
    assert stats.status_code == 200
    assert stats.get_json()["active"] == 1

    canceled = client.post(f"/reminders/cancel/{reminder_id}")
    assert canceled.status_code == 200
    assert canceled.get_json()["reminder"]["status"] == "canceled"


def test_reminder_bad_input_returns_400(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post("/reminders/create", json={"message": "missing title", "trigger_at": "in 1m"})
    assert response.status_code == 400


def test_reminder_routes_enforce_auth(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, require_auth=_auth)
    response = client.get("/reminders/list")
    assert response.status_code == 401
