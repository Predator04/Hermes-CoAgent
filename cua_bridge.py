"""Cua Driver bridge helpers for Hermes CoAgent."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


def _userprofile():
    return os.environ.get("USERPROFILE") or os.environ.get("HOME") or "C:\\Users\\Default"


SPEC_CUA_EXE = Path(_userprofile()) / "AppData/Local/cua/cua-driver.exe"
PROGRAMS_CUA_EXE = Path(_userprofile()) / "AppData/Local/Programs/Cua/cua-driver/bin/cua-driver.exe"
PACKAGE_ROOT = Path(_userprofile()) / ".cua-driver/packages/releases"

_TOOL_RE = re.compile(r"^[A-Za-z0-9_:-]+$")
_STATUS_CACHE = {"ts": 0.0, "available": False, "detail": {}}
_STATUS_TTL = 30.0


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_powershell(script: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def resolve_cua_exe() -> str:
    """Resolve cua-driver.exe from the configured v7.4 path or known install paths."""
    if SPEC_CUA_EXE.is_file():
        return str(SPEC_CUA_EXE)
    if PROGRAMS_CUA_EXE.is_file():
        return str(PROGRAMS_CUA_EXE)
    if PACKAGE_ROOT.is_dir():
        candidates = sorted(
            PACKAGE_ROOT.glob("*/cua-driver.exe"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    found = shutil.which("cua-driver.exe") or shutil.which("cua-driver")
    if found:
        return found
    raise FileNotFoundError("cua-driver.exe not found")


def _daemon_status() -> dict:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'cua-driver.exe'\" "
        "| Select-Object ProcessId,ExecutablePath,CommandLine,SessionId "
        "| ConvertTo-Json -Compress"
    )
    try:
        result = _run_powershell(script, timeout=5)
    except Exception as exc:
        return {"available": False, "error": str(exc), "processes": []}

    if result.returncode != 0 or not result.stdout.strip():
        return {
            "available": False,
            "error": (result.stderr or result.stdout).strip(),
            "processes": [],
        }

    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"available": False, "error": "Could not parse cua-driver process list", "processes": []}
    if isinstance(rows, dict):
        rows = [rows]

    processes = []
    for row in rows:
        try:
            processes.append({
                "pid": int(row.get("ProcessId") or 0),
                "path": row.get("ExecutablePath") or "",
                "command_line": row.get("CommandLine") or "",
                "session_id": int(row.get("SessionId") or -1),
            })
        except Exception:
            continue

    session1_daemon = [
        p for p in processes
        if p.get("session_id") == 1 and " serve" in f" {p.get('command_line', '')} "
    ]
    return {
        "available": bool(session1_daemon),
        "processes": processes,
        "daemon": session1_daemon[0] if session1_daemon else None,
    }


def cua_available() -> bool:
    """Return True when the cua-driver daemon is running in Session 1."""
    now = time.time()
    if now - float(_STATUS_CACHE.get("ts", 0.0)) < _STATUS_TTL:
        return bool(_STATUS_CACHE.get("available"))

    detail = _daemon_status()
    _STATUS_CACHE.update({
        "ts": now,
        "available": bool(detail.get("available")),
        "detail": detail,
    })
    return bool(detail.get("available"))


def cua_status() -> dict:
    """Return current cua-driver status, version, and tool inventory."""
    available = cua_available()
    detail = dict(_STATUS_CACHE.get("detail") or {})
    try:
        exe = resolve_cua_exe()
    except FileNotFoundError as exc:
        return {"available": False, "error": str(exc), "tools_count": 0, "tools": [], **detail}

    version = ""
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip()
    except Exception:
        pass

    tools = []
    try:
        result = subprocess.run([exe, "list-tools"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if ":" in line:
                    tools.append(line.split(":", 1)[0].strip())
    except Exception:
        pass

    return {
        "available": available,
        "version": version,
        "tools_count": len(tools),
        "tools": tools,
        "exe": exe,
        **detail,
    }


def cua_call(tool: str, data: dict | None = None) -> dict:
    """Call a cua-driver tool by piping JSON through PowerShell stdin."""
    if not _TOOL_RE.match(str(tool or "")):
        raise ValueError("Invalid cua tool name")
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    exe = resolve_cua_exe()
    exe_ps = _ps_quote(exe)
    tool_ps = _ps_quote(tool)
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"$payload=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload_b64}')); "
        f"$payload | & {exe_ps} call {tool_ps}; "
        "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }"
    )
    result = _run_powershell(script, timeout=30)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        return {
            "ok": False,
            "tool": tool,
            "error": stderr or stdout or f"cua-driver exited {result.returncode}",
            "returncode": result.returncode,
        }
    try:
        parsed = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        parsed = stdout
    return {"ok": True, "tool": tool, "result": parsed}
