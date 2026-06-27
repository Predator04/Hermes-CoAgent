"""Tests for the screenshot relay server (screenshot_relay.py)."""
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import screenshot_relay


@pytest.fixture
def relay_server(monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (2, 2), "white")
    monkeypatch.setattr(screenshot_relay, "_capture_image", lambda: (image, "test", []))

    server = screenshot_relay.ThreadingHTTPServer(("127.0.0.1", 0), screenshot_relay.RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _read(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers, response.read()


def test_relay_defaults_to_port_9124():
    assert screenshot_relay.PORT == 9124


def test_relay_health_screenshot_screen_and_404(relay_server):
    status, headers, body = _read(f"{relay_server}/health")
    assert status == 200
    assert b'"status":"ok"' in body

    status, headers, body = _read(f"{relay_server}/screenshot")
    assert status == 200
    assert headers["Content-Type"] == "image/jpeg"
    assert body.startswith(b"\xff\xd8")

    status, headers, body = _read(f"{relay_server}/screen")
    assert status == 200
    assert headers["Content-Type"] == "image/jpeg"

    with pytest.raises(urllib.error.HTTPError) as exc:
        _read(f"{relay_server}/nonexistent")
    assert exc.value.code == 404
