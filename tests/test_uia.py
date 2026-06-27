"""Tests for the UIA engine and element-finding routes (uia_engine.py, routes_uia.py)."""
import functools
import sys
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_uia


class FakeUIA:
    UIA_READY = True

    def uia_snapshot(self, timeout=5):
        return {
            "success": True,
            "tree": {
                "name": "Desktop",
                "children": [
                    {
                        "name": "Calculator",
                        "control_type": "Window",
                        "rect": {"left": 10, "top": 20, "width": 300, "height": 200},
                        "children": [
                            {
                                "name": "Equals",
                                "automation_id": "equalButton",
                                "control_type": "Button",
                                "class_name": "Button",
                                "rect": {"left": 50, "top": 60, "width": 40, "height": 30},
                            }
                        ],
                    }
                ],
            },
        }

    def uia_find_deep(self, name):
        return [{"name": name, "rect": {"left": 1, "top": 2, "width": 3, "height": 4}}]

    def find_on_screen(self, name):
        return {"name": name, "found": True}


class EmptyUIA(FakeUIA):
    def uia_snapshot(self, timeout=5):
        return {"success": False, "error": "missing desktop"}

    def uia_find_deep(self, name):
        return []


def _auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("Authorization") != "Bearer test-token":
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def _client(monkeypatch, engine=None, require_auth=lambda fn: fn):
    monkeypatch.setattr(routes_uia, "_uia_engine", engine or FakeUIA())
    app = Flask(__name__)

    class State:
        emergency_stop = False

    routes_uia.register_routes(app, State(), require_auth)
    return app.test_client()


def test_uia_tree_click_find_type_and_ocr(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes_uia, "_type_text", lambda text, _state: jsonify({"status": "ok", "text": text}))
    monkeypatch.setattr(routes_uia, "_ocr_screen_text", lambda: "Visible OCR text")

    tree = client.get("/uia/tree")
    assert tree.status_code == 200
    assert tree.get_json()["name"] == "Desktop"

    clicked = client.post("/uia/click", json={"name": "Equals"})
    assert clicked.status_code == 200
    assert clicked.get_json()["status"] == "queried"

    found = client.post("/uia/find", json={"text": "Equals", "type": "Button"})
    assert found.status_code == 200
    assert found.get_json()["found"] is True
    assert found.get_json()["method"] == "uia"

    typed = client.post("/uia/type", json={"text": "hello"})
    assert typed.status_code == 200
    assert typed.get_json()["text"] == "hello"

    ocr = client.post("/uia/ocr", json={})
    assert ocr.status_code == 200
    assert ocr.get_json()["text"] == "Visible OCR text"


def test_uia_vision_fallback_when_uia_misses(monkeypatch):
    client = _client(monkeypatch, engine=EmptyUIA())
    monkeypatch.setattr(
        routes_uia,
        "_find_ocr_candidate",
        lambda text: {
            "found": True,
            "method": "ocr",
            "x": 5,
            "y": 6,
            "width": 7,
            "height": 8,
            "center": {"x": 8, "y": 10},
            "element_info": {"text": text},
        },
    )

    found = client.post("/uia/find", json={"text": "Fallback"})
    assert found.status_code == 200
    assert found.get_json()["method"] == "ocr"


def test_uia_routes_enforce_auth(monkeypatch):
    client = _client(monkeypatch, require_auth=_auth)
    assert client.get("/uia/tree").status_code == 401
