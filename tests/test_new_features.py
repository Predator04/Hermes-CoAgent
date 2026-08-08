"""Tests for the v8.52 feature modules: discover, humanize, approvals,
macro builder, and semantic UIA (issues #5, #9, #13, #2, #8)."""
import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_discover
import routes_humanize
import routes_approvals
import routes_macro_builder
import routes_uia_semantic


def _client(*modules):
    app = Flask(__name__)
    for m in modules:
        m.register_routes(app, state=None, require_auth=lambda f: f)
    return app, app.test_client()


# ---- #5 discover ---------------------------------------------------------
def test_discover_manifest_groups_and_availability():
    app, c = _client(routes_discover, routes_humanize)
    r = c.get("/discover")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] and data["group_count"] >= 1
    groups = {g["group"] for g in data["groups"]}
    assert "mouse" in groups  # humanized_move registered under /mouse
    for g in data["groups"]:
        assert set(["group", "available", "endpoints", "requirements"]) <= set(g)


def test_discover_marks_missing_tools_unavailable():
    # tunnel requires ngrok/cloudflared which aren't installed in CI
    manifest = routes_discover.build_manifest(_client(routes_discover)[0].url_map)
    # inject a fake tunnel rule via a throwaway app
    app = Flask(__name__)
    app.add_url_rule("/tunnel/start", "t", lambda: "", methods=["POST"])
    m = {g["group"]: g for g in routes_discover.build_manifest(app.url_map)}
    assert m["tunnel"]["available"] is False


# ---- #9 humanized mouse --------------------------------------------------
def test_humanized_path_deterministic_and_exact_endpoints():
    p1 = routes_humanize.humanized_path((0, 0), (200, 100), steps=25, seed=7)
    p2 = routes_humanize.humanized_path((0, 0), (200, 100), steps=25, seed=7)
    assert p1 == p2
    assert (p1[0]["x"], p1[0]["y"]) == (0, 0)
    assert (p1[-1]["x"], p1[-1]["y"]) == (200, 100)
    assert abs(sum(pt["delay_ms"] for pt in p1) - 600) < 1.0


def test_humanized_move_endpoint_dry_run():
    app, c = _client(routes_humanize)
    r = c.post("/mouse/humanized_move", json={"x": 50, "y": 60, "seed": 1})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] and d["target"] == {"x": 50, "y": 60}


# ---- #13 approvals -------------------------------------------------------
def test_approvals_full_flow():
    app, c = _client(routes_approvals)
    routes_approvals._QUEUE._items.clear()
    r = c.post("/approvals/request", json={"action": "delete", "detail": "x"})
    aid = r.get_json()["approval"]["id"]
    assert c.get("/approvals/pending").get_json()["count"] == 1
    r2 = c.post(f"/approvals/{aid}/approve", json={"by": "will"})
    assert r2.get_json()["approval"]["status"] == "approved"
    assert c.get("/approvals/pending").get_json()["count"] == 0
    assert c.get("/approvals/nope").status_code == 404


def test_approvals_reject_and_missing_action():
    app, c = _client(routes_approvals)
    routes_approvals._QUEUE._items.clear()
    assert c.post("/approvals/request", json={}).status_code == 400
    aid = c.post("/approvals/request", json={"action": "x"}).get_json()["approval"]["id"]
    assert c.post(f"/approvals/{aid}/reject").get_json()["approval"]["status"] == "rejected"


# ---- #2 macro builder ----------------------------------------------------
def test_macro_build_parses_grammar():
    app, c = _client(routes_macro_builder)
    text = "click 10,20; type hi there; press ctrl+s; wait 250ms; scroll down 2"
    r = c.post("/macro/build", json={"text": text})
    d = r.get_json()
    assert [s["action"] for s in d["steps"]] == ["click", "type", "hotkey", "wait", "scroll"]
    assert d["steps"][1]["text"] == "hi there"


def test_macro_build_requires_text():
    app, c = _client(routes_macro_builder)
    assert c.post("/macro/build", json={}).status_code == 400


# ---- #8 semantic UIA -----------------------------------------------------
def test_uia_act_ranks_and_matches():
    app, c = _client(routes_uia_semantic)
    tree = [
        {"role": "Button", "name": "Save", "bbox": [1, 2, 3, 4]},
        {"role": "Button", "name": "Cancel"},
        {"role": "Edit", "name": "Filename"},
    ]
    r = c.post("/uia/act", json={"role": "Button", "name": "Save", "tree": tree})
    d = r.get_json()
    assert d["ok"] and d["matched"]["name"] == "Save" and d["score"] == 1.0
    assert d["dry_run"] is True


def test_uia_act_no_match_and_missing_query():
    app, c = _client(routes_uia_semantic)
    assert c.post("/uia/act", json={"tree": []}).status_code == 400
    r = c.post("/uia/act", json={"name": "Nonexistent", "tree": [{"role": "Button", "name": "Save"}]})
    assert r.status_code == 404
