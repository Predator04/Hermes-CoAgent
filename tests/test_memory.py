"""Tests for the cross-session memory routes (routes_memory.py)."""
import functools
import sys
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_memory


def _auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("Authorization") != "Bearer test-token":
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def _client(tmp_path, monkeypatch, require_auth=lambda fn: fn):
    monkeypatch.setattr(routes_memory, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(routes_memory, "_DB_READY", False)
    app = Flask(__name__)

    class State:
        pass

    routes_memory.register_routes(app, State(), require_auth)
    return app.test_client()


def test_memory_store_recall_search_forget_and_stats(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    stored = client.post(
        "/memory/store",
        json={"key": "favorite_color", "value": "blue unicorn", "tags": ["profile", "unicode-漢字"]},
    )
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "stored"

    recalled = client.get("/memory/recall/favorite_color")
    assert recalled.status_code == 200
    assert recalled.get_json()["value"] == "blue unicorn"

    searched = client.get("/memory/search?q=unicorn")
    assert searched.status_code == 200
    assert searched.get_json()["count"] == 1
    assert searched.get_json()["results"][0]["key"] == "favorite_color"

    stats = client.get("/memory/stats")
    assert stats.status_code == 200
    assert stats.get_json()["facts"] == 1

    forgotten = client.post("/memory/forget/favorite_color")
    assert forgotten.status_code == 200
    assert forgotten.get_json()["status"] == "forgotten"

    missing = client.get("/memory/recall/favorite_color")
    assert missing.status_code == 404


def test_memory_empty_inputs_return_400(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/memory/store", json={"value": "x"}).status_code == 400
    assert client.get("/memory/search?q=").status_code == 400


def test_memory_routes_enforce_auth(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, require_auth=_auth)
    assert client.post("/memory/store", json={"key": "k", "value": "v"}).status_code == 401
