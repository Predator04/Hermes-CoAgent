import json
import math
import sys
from pathlib import Path

import pytest
from flask import Flask, g

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
from routes_bypass import MAX_TEXT_CHARS, register_routes


TOKEN = "test-token"
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(TESTING=True)
    auth.AUTH_ENABLED = True
    auth.AUTH_TOKEN = TOKEN

    @app.before_request
    def auth_gate():
        result = auth.require_auth(lambda: None)()
        if result is not None:
            return result
        g._auth_passed = True
        return None

    register_routes(app, state=None, require_auth=auth.require_auth)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def post_json(client, path, payload, headers=None):
    return client.post(path, json=payload, headers=headers or AUTH_HEADER)


def post_raw_json(client, path, payload, headers=None):
    return client.post(
        path,
        data=json.dumps(payload, allow_nan=True),
        content_type="application/json",
        headers=headers or AUTH_HEADER,
    )


def test_index_returns_all_9_tools(client):
    res = client.get("/bypass", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["tools"]) == 9
    assert {tool["path"] for tool in body["tools"]} == {
        "/bypass/leetspeak",
        "/bypass/homoglyph",
        "/bypass/zero-width",
        "/bypass/parseltongue",
        "/bypass/prefill",
        "/bypass/adversarial",
        "/bypass/scan",
        "/bypass/clean",
        "/bypass/all",
    }


def test_normal_endpoint_responses(client):
    text = "Please review password handling."

    res = post_json(client, "/bypass/leetspeak", {"text": "abc", "intensity": 1, "use_cyrillic": False})
    assert res.status_code == 200
    assert res.get_json()["encoded"] != "abc"

    res = post_json(client, "/bypass/homoglyph", {"text": "ABC", "block": "fullwidth"})
    assert res.status_code == 200
    assert res.get_json()["encoded"] != "ABC"

    res = post_json(client, "/bypass/zero-width", {"text": "abc", "frequency": 1})
    assert res.status_code == 200
    assert len(res.get_json()["encoded"]) > 3

    res = post_json(client, "/bypass/parseltongue", {"text": text, "passes": 2})
    assert res.status_code == 200
    assert len(res.get_json()["passes"]) == 2

    res = client.get("/bypass/prefill", headers=AUTH_HEADER)
    assert res.status_code == 200
    assert "boundary_inversion" in res.get_json()["templates"]

    res = post_json(client, "/bypass/prefill", {"text": text, "template": "educational_compatibility"})
    assert res.status_code == 200
    assert res.get_json()["template"] == "educational_compatibility"

    res = post_json(client, "/bypass/adversarial", {"text": text})
    assert res.status_code == 200
    assert len(res.get_json()["variants"]) >= 5

    res = post_json(client, "/bypass/scan", {"text": text})
    assert res.status_code == 200
    assert res.get_json()["total_matches"] >= 1

    res = post_json(client, "/bypass/clean", {"text": text})
    assert res.status_code == 200
    assert res.get_json()["total_replaced"] >= 1

    res = post_json(client, "/bypass/all", {"text": text, "template": "story_framing"})
    assert res.status_code == 200
    body = res.get_json()
    assert {"scan", "cleaned", "parseltongue", "adversarial", "prefilled", "cli"} <= set(body)


@pytest.mark.parametrize(
    "path",
    [
        "/bypass/leetspeak",
        "/bypass/homoglyph",
        "/bypass/zero-width",
        "/bypass/parseltongue",
        "/bypass/prefill",
        "/bypass/adversarial",
        "/bypass/scan",
        "/bypass/clean",
        "/bypass/all",
    ],
)
def test_empty_text_returns_400(client, path):
    res = post_json(client, path, {"text": ""})
    assert res.status_code == 400


def test_oversized_text_returns_413(client):
    res = post_json(client, "/bypass/scan", {"text": "x" * (MAX_TEXT_CHARS + 1)})
    assert res.status_code == 413


def test_bad_json_shapes(client):
    res = post_json(client, "/bypass/scan", ["not", "an", "object"])
    assert res.status_code == 400

    res = post_json(client, "/bypass/scan", {"text": ["not", "a", "string"]})
    assert res.status_code == 400


@pytest.mark.parametrize("value", [math.nan, math.inf, "0.5"])
def test_bad_float_fields(client, value):
    res = post_raw_json(client, "/bypass/leetspeak", {"text": "abc", "intensity": value})
    assert res.status_code == 400

    res = post_raw_json(client, "/bypass/zero-width", {"text": "abc", "frequency": value})
    assert res.status_code == 400


@pytest.mark.parametrize("value", [math.nan, math.inf, "3"])
def test_bad_int_fields(client, value):
    res = post_raw_json(client, "/bypass/parseltongue", {"text": "abc", "passes": value})
    assert res.status_code == 400


@pytest.mark.parametrize("path", ["/bypass/prefill", "/bypass/all"])
def test_bad_template_names(client, path):
    res = post_json(client, path, {"text": "abc", "template": "missing_template"})
    assert res.status_code == 400


@pytest.mark.parametrize(
    "text",
    [
        "漢字かなカナ",
        "🙂🚀✨",
        "مرحبا بالعالم",
    ],
)
def test_unicode_only_text(client, text):
    for path in ["/bypass/leetspeak", "/bypass/homoglyph", "/bypass/scan", "/bypass/all"]:
        res = post_json(client, path, {"text": text})
        assert res.status_code == 200


def test_cli_escaping_in_bypass_all(client):
    res = post_json(client, "/bypass/all", {"text": "john's password"})
    assert res.status_code == 200
    cli = res.get_json()["cli"]
    assert "\\u0027" in cli["scan_check"]
    assert "john's" not in cli["scan_check"]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/bypass", None),
        ("POST", "/bypass/leetspeak", {"text": "abc"}),
        ("POST", "/bypass/homoglyph", {"text": "abc"}),
        ("POST", "/bypass/zero-width", {"text": "abc"}),
        ("POST", "/bypass/parseltongue", {"text": "abc"}),
        ("GET", "/bypass/prefill", None),
        ("POST", "/bypass/prefill", {"text": "abc"}),
        ("POST", "/bypass/adversarial", {"text": "abc"}),
        ("POST", "/bypass/scan", {"text": "abc"}),
        ("POST", "/bypass/clean", {"text": "abc"}),
        ("POST", "/bypass/all", {"text": "abc"}),
    ],
)
def test_all_bypass_routes_require_auth(client, method, path, payload):
    if method == "GET":
        res = client.get(path)
    else:
        res = client.post(path, json=payload)
    assert res.status_code == 401
