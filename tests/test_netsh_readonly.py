"""Regression tests for netsh read-only enforcement (default-deny contexts)."""
import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes_auto_netsh


def _client():
    app = Flask(__name__)
    routes_auto_netsh.register_routes(app, state=None, require_auth=lambda f: f)
    return app.test_client()


def test_ras_context_cannot_run_state_changing_subcommand():
    # "ras" is an allowed context but has no read-only allowlist entry, so
    # every subcommand (set/add/delete) must be rejected before execution.
    resp = _client().post("/auto/netsh/command", json={"context": "ras", "command": "set foo"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_interface_show_is_permitted_past_the_guard():
    # A valid read-only subcommand must pass the allowlist guard (it may then
    # fail later trying to actually run netsh, but not with a 400 guard error).
    resp = _client().post("/auto/netsh/command", json={"context": "interface", "command": "show interfaces"})
    assert resp.status_code != 400  # read-only subcommand passes the guard
    # 'set' is not in the interface allowlist -> rejected
    resp2 = _client().post("/auto/netsh/command", json={"context": "interface", "command": "set bogus"})
    assert resp2.status_code == 400
    # 'delete' is not in the advfirewall allowlist -> rejected
    resp3 = _client().post("/auto/netsh/command", json={"context": "advfirewall", "command": "delete rule"})
    assert resp3.status_code == 400
