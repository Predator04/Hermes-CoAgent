import json
import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shared


def test_version_and_build_are_v81():
    assert shared.VERSION == "8.1"
    assert shared.BUILD


def test_json_frame_matches_sse_format():
    payload = {"ok": True, "value": 3}
    assert shared._json_frame("status", payload) == f"event: status\ndata: {json.dumps(payload)}\n\n"


def test_sse_response_uses_event_stream_content_type():
    app = Flask(__name__)
    with app.app_context():
        response = shared._sse_response([shared._json_frame("ready", {"status": "ok"})])
        assert response.mimetype == "text/event-stream"
        assert "event: ready" in response.get_data(as_text=True)


def test_missing_field_supports_payload_check_and_legacy_name():
    app = Flask(__name__)
    with app.app_context():
        assert shared._missing_field({"name": "Hermes"}, "name") is None
        response, status = shared._missing_field({}, "name")
        assert status == 400
        assert response.get_json()["error"] == "Missing required field: name"

        response, status = shared._missing_field("text")
        assert status == 400
        assert response.get_json()["error"] == "Missing required field: text"


def test_json_body_can_build_json_response_and_read_request_body():
    app = Flask(__name__)
    with app.app_context():
        response, status = shared._json_body({"status": "ok"}, status=201)
        assert status == 201
        assert response.mimetype == "application/json"
        assert response.get_json() == {"status": "ok"}

    with app.test_request_context(json={"unicode": "漢字"}):
        assert shared._json_body() == {"unicode": "漢字"}
