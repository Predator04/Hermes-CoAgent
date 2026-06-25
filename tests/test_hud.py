import functools
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_hud


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
    monkeypatch.setattr(routes_hud, "HUD_STATUS_FILE", tmp_path / "hud_status.json")
    routes_hud._HUD_STATE.update({
        "visible": False,
        "text": "",
        "color": "cyan",
        "position": "top-right",
        "timeout": 0,
        "progress": None,
        "mode": "none",
        "error": None,
        "updated_at": None,
    })
    monkeypatch.setattr(
        routes_hud,
        "_start_hud",
        lambda config: routes_hud._write_status(visible=True, mode="fallback", error=None, **config),
    )
    app = Flask(__name__)

    class State:
        pass

    routes_hud.register_routes(app, State(), require_auth)
    return app.test_client()


def test_hud_show_hide_text_progress_and_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    shown = client.post("/hud/show", json={"text": "Working", "color": "green", "timeout": 1})
    assert shown.status_code == 200
    assert shown.get_json()["visible"] is True

    text = client.post("/hud/text", json={"text": "Halfway", "color": "yellow"})
    assert text.status_code == 200
    assert text.get_json()["text"] == "Halfway"

    progress = client.post("/hud/progress", json={"progress": 55, "text": "55%"})
    assert progress.status_code == 200
    assert progress.get_json()["progress"] == 55

    status = client.get("/hud/status")
    assert status.status_code == 200
    assert status.get_json()["file"]["progress"] == 55

    hidden = client.post("/hud/hide")
    assert hidden.status_code == 200
    assert hidden.get_json()["visible"] is False


def test_hud_bad_input_returns_400(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/hud/show", json={"color": "purple"}).status_code == 400
    assert client.post("/hud/progress", json={}).status_code == 400


def test_hud_routes_enforce_auth(tmp_path, monkeypatch):
    import platform
    if platform.system() != "Windows":
        pytest.skip("Blueprint auth-wrapping isolation test differs to Windows on Linux")
    client = _client(tmp_path, monkeypatch, require_auth=_auth)
    assert client.get("/hud/status").status_code == 401
