"""Tests for process and application launch control."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shared


def _reset_lock_state():
    shared._LOCK_STATE.update({"pid_file": False, "mutex_handle": None, "mutex_name": None})


def test_launch_script_powershell_syntax_parses():
    import platform
    if platform.system() != "Windows":
        pytest.skip("PowerShell script parsing requires Windows (WSL path mismatch)")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("PowerShell is not available")
    script = ROOT / "launch_all.ps1"
    script_text = str(script).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{script_text}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_launch_script_contains_relay_pid_and_port_checks():
    text = (ROOT / "launch_all.ps1").read_text(encoding="utf-8")
    assert "$pidFile" in text
    assert "Get-CoAgentPidFromFile" in text
    assert "Test-PortListener" in text
    assert "$relayPort = 9124" in text
    assert "http://127.0.0.1:$relayPort/health" in text


def test_single_instance_acquire_creates_pid_and_release_cleans_up(tmp_path, monkeypatch):
    _reset_lock_state()
    pid_file = tmp_path / "coagent.pid"
    monkeypatch.setattr(shared, "PID_FILE", pid_file)
    monkeypatch.setattr(shared, "_kernel32", lambda: None)
    monkeypatch.setattr(shared, "is_coagent_server_running", lambda *args, **kwargs: False)
    monkeypatch.setattr(shared, "_can_bind_port", lambda *args, **kwargs: True)
    monkeypatch.setattr(shared.atexit, "register", lambda _fn: None)

    def fake_mutex():
        shared._LOCK_STATE["mutex_handle"] = object()
        shared._LOCK_STATE["mutex_name"] = "Global\\HermesCoAgent_Test"
        return True

    monkeypatch.setattr(shared, "_acquire_named_mutex", fake_mutex)

    assert shared.acquire_single_instance_lock(port=9123)
    assert pid_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    assert shared._LOCK_STATE["mutex_name"].startswith("Global\\HermesCoAgent_")

    shared.release_single_instance_lock()
    assert not pid_file.exists()
    assert shared._LOCK_STATE["mutex_handle"] is None


def test_single_instance_port_check_prevents_duplicate_launch(tmp_path, monkeypatch):
    _reset_lock_state()
    pid_file = tmp_path / "coagent.pid"
    monkeypatch.setattr(shared, "PID_FILE", pid_file)
    monkeypatch.setattr(shared, "_kernel32", lambda: None)
    monkeypatch.setattr(shared, "_acquire_named_mutex", lambda: True)
    monkeypatch.setattr(shared, "is_coagent_server_running", lambda *args, **kwargs: True)
    monkeypatch.setattr(shared, "_can_bind_port", lambda *args, **kwargs: False)

    assert shared.acquire_single_instance_lock(port=9123) is False
    assert not pid_file.exists()


def test_named_mutex_name_is_windows_global():
    assert shared._coagent_mutex_name().startswith("Global\\HermesCoAgent_")
