"""Windows 11 virtual desktop management routes.

Endpoints:
  GET/POST /vdesk/list   - enumerate current virtual desktops
  POST     /vdesk/create - create a new virtual desktop (optionally switch to it)
  POST     /vdesk/switch - switch to a virtual desktop by index, id, or name
  POST     /vdesk/move   - move a window (hwnd or title match) to a desktop

Primary backend is the third-party "VirtualDesktop" PowerShell module
(https://github.com/MScholtes/PSVirtualDesktop) which ships a single-file
script (VirtualDesktop.ps1 / VirtualDesktop11.ps1) exposing cmdlets like
Get-DesktopList, New-Desktop, Switch-Desktop, Move-Window. Fallback is a
direct COM interop path through comtypes against IVirtualDesktopManager,
which supports IsWindowOnCurrentVirtualDesktop / MoveWindowToDesktop only
(enumeration/create still require the PowerShell module or IVirtualDesktop*
private interfaces which are Windows-build-specific).

All PowerShell / subprocess strings are pure ASCII; no smart quotes.
Windows-only imports are guarded so Linux syntax-check CI stays green.
"""

import json as _json
import os
import shutil
import subprocess

from flask import jsonify

from shared import _json_body, _log, _missing_field


# ---------------------------------------------------------------------------
# Optional Windows-only imports
# ---------------------------------------------------------------------------
_COM_AVAILABLE = False
_COM_IMPORT_ERROR = None

try:
    import comtypes  # type: ignore  # noqa: F401
    import comtypes.client  # type: ignore  # noqa: F401
    _COM_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    comtypes = None
    _COM_IMPORT_ERROR = str(_exc)


_USER32 = None
if os.name == "nt":
    try:
        import ctypes  # noqa: F401
        from ctypes import wintypes  # noqa: F401
        _USER32 = ctypes.windll.user32
    except Exception as _exc:  # noqa: BLE001
        _USER32 = None


_DEFAULT_TIMEOUT = 15


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _find_powershell():
    return (
        shutil.which("pwsh")
        or shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _escape_like_wildcards(s):
    """Escape PowerShell `-like` wildcards so they match literally."""
    return (
        s.replace("`", "``")
        .replace("*", "`*")
        .replace("?", "`?")
        .replace("[", "`[")
        .replace("]", "`]")
    )


# ---------------------------------------------------------------------------
# PowerShell backend (VirtualDesktop module by MScholtes)
# ---------------------------------------------------------------------------
# The module is loaded via Install-Module VirtualDesktop -Scope CurrentUser.
# We do NOT auto-install; if missing, endpoints return an actionable error.

_PS_PREAMBLE = (
    "$ErrorActionPreference = 'Stop';"
    "try { Import-Module VirtualDesktop -ErrorAction Stop -DisableNameChecking -WarningAction SilentlyContinue } catch {"
    " Write-Output ('{\"error\":\"VirtualDesktop module not installed. Run:"
    " Install-Module VirtualDesktop -Scope CurrentUser\"}'); exit 2 };"
)


def _run_powershell(script, timeout=_DEFAULT_TIMEOUT):
    """Run an ASCII PowerShell snippet and return (stdout, stderr, returncode)."""
    exe = _find_powershell()
    cmd = [
        exe,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", script,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "timeout", 124
    except FileNotFoundError as exc:
        return "", f"powershell not found: {exc}", 127
    return proc.stdout or "", proc.stderr or "", proc.returncode


def _ps_list_desktops():
    script = _PS_PREAMBLE + (
        "$desks = Get-DesktopList;"
        "$current = (Get-CurrentDesktop).Number;"
        "$out = @();"
        "foreach ($d in $desks) {"
        " $out += [ordered]@{ index = [int]$d.Number;"
        " name = [string]$d.Name;"
        " visible = ([int]$d.Number -eq [int]$current) };"
        "}"
        "ConvertTo-Json -InputObject @{ current = [int]$current; desktops = $out } -Depth 4 -Compress"
    )
    stdout, stderr, rc = _run_powershell(script)
    return stdout, stderr, rc


def _ps_create_desktop(name=None, switch=False):
    body = "$d = New-Desktop;"
    if isinstance(name, str) and name.strip():
        safe = name.replace('"', ' ').replace("'", " ")
        body += " Set-DesktopName -Desktop $d -Name '" + safe + "';"
    if switch:
        body += " Switch-Desktop -Desktop $d;"
    body += (
        " ConvertTo-Json -InputObject @{ index = [int]$d.Number;"
        " name = [string]$d.Name } -Depth 3 -Compress"
    )
    return _run_powershell(_PS_PREAMBLE + body)


def _ps_switch_desktop(index=None, name=None):
    if index is not None:
        body = (
            "$d = Get-Desktop -Index " + str(int(index)) + ";"
            "if ($null -eq $d) { Write-Output '{\"error\":\"desktop not found\"}';"
            " exit 3 }; Switch-Desktop -Desktop $d;"
        )
    elif isinstance(name, str) and name.strip():
        safe = name.replace('"', ' ').replace("'", " ")
        body = (
            "$d = Get-Desktop -Name '" + safe + "';"
            "if ($null -eq $d) { Write-Output '{\"error\":\"desktop not found\"}';"
            " exit 3 }; Switch-Desktop -Desktop $d;"
        )
    else:
        return "", "missing index or name", 22
    body += (
        " $c = Get-CurrentDesktop;"
        " ConvertTo-Json -InputObject @{ index = [int]$c.Number;"
        " name = [string]$c.Name } -Depth 3 -Compress"
    )
    return _run_powershell(_PS_PREAMBLE + body)


def _ps_move_window(hwnd=None, title=None, index=None, name=None):
    if hwnd is not None:
        target = "$h = [IntPtr]" + str(int(hwnd)) + ";"
    elif isinstance(title, str) and title.strip():
        safe = _escape_like_wildcards(title.replace('"', ' ').replace("'", " "))
        target = (
            "$p = Get-Process | Where-Object { $_.MainWindowTitle -like '*"
            + safe + "*' -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1;"
            "if ($null -eq $p) { Write-Output '{\"error\":\"window not found\"}';"
            " exit 4 }; $h = $p.MainWindowHandle;"
        )
    else:
        return "", "missing hwnd or title", 22

    if index is not None:
        dest = "$d = Get-Desktop -Index " + str(int(index)) + ";"
    elif isinstance(name, str) and name.strip():
        safe_n = name.replace('"', ' ').replace("'", " ")
        dest = "$d = Get-Desktop -Name '" + safe_n + "';"
    else:
        return "", "missing desktop index or name", 22

    body = (
        target + dest +
        "if ($null -eq $d) { Write-Output '{\"error\":\"desktop not found\"}';"
        " exit 3 }; Move-Window -Desktop $d -Hwnd $h;"
        " ConvertTo-Json -InputObject @{ hwnd = [int64]$h;"
        " desktop_index = [int]$d.Number;"
        " desktop_name = [string]$d.Name } -Depth 3 -Compress"
    )
    return _run_powershell(_PS_PREAMBLE + body)


# ---------------------------------------------------------------------------
# COM fallback (IVirtualDesktopManager) - only supports move + query
# ---------------------------------------------------------------------------
_CLSID_VirtualDesktopManager = "{AA509086-5CA9-4C25-8F95-589D3C07B48A}"
_IID_IVirtualDesktopManager = "{A5CD92FF-29BE-454C-8D04-D82879FB3F1B}"


def _get_desktop_manager():
    """Return an IVirtualDesktopManager COM object or None."""
    if not _COM_AVAILABLE:
        return None
    try:
        import comtypes  # type: ignore
        import comtypes.client  # type: ignore
        from ctypes import HRESULT, POINTER  # noqa: F401
        from ctypes.wintypes import BOOL, HWND  # noqa: F401

        # CoCreateInstance via comtypes: use GUID objects.
        clsid = comtypes.GUID(_CLSID_VirtualDesktopManager)
        iid = comtypes.GUID(_IID_IVirtualDesktopManager)
        return comtypes.CoCreateInstance(clsid, interface=None, clsctx=1, iid=iid)
    except Exception as exc:  # noqa: BLE001
        _log(f"vdesk: COM init failed: {exc}")
        return None


def _com_is_window_on_current(hwnd):
    mgr = _get_desktop_manager()
    if mgr is None:
        return None
    try:
        return bool(mgr.IsWindowOnCurrentVirtualDesktop(hwnd))
    except Exception as exc:  # noqa: BLE001
        _log(f"vdesk: IsWindowOnCurrentVirtualDesktop failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------
def _parse_ps_json(stdout, stderr, rc):
    text = (stdout or "").strip()
    if rc != 0:
        # Try to surface an inline JSON error emitted by the script.
        if text.startswith("{"):
            try:
                payload = _json.loads(text)
                if isinstance(payload, dict) and "error" in payload:
                    return payload, 400
            except Exception:  # noqa: BLE001
                pass
        return {
            "error": "powershell failed",
            "rc": rc,
            "stderr": (stderr or "").strip()[:2000],
            "stdout": text[:2000],
        }, 500
    if not text:
        return {"error": "empty response"}, 500
    try:
        return _json.loads(text), 200
    except Exception:  # noqa: BLE001
        return {"raw": text}, 200


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def register_routes(app, state, require_auth):

    @app.route("/vdesk/list", methods=["GET", "POST"])
    @require_auth
    def route_vdesk_list():
        if os.name != "nt":
            return _windows_only()
        stdout, stderr, rc = _ps_list_desktops()
        payload, status = _parse_ps_json(stdout, stderr, rc)
        if status == 200 and isinstance(payload, dict) and "desktops" in payload:
            payload["backend"] = "powershell:VirtualDesktop"
        return jsonify(payload), status

    @app.route("/vdesk/create", methods=["POST"])
    @require_auth
    def route_vdesk_create():
        if os.name != "nt":
            return _windows_only()
        body = _json_body() or {}
        if not isinstance(body, dict):
            body = {}
        name = body.get("name") if isinstance(body.get("name"), str) else None
        raw_switch = body.get("switch")
        if isinstance(raw_switch, bool):
            switch = raw_switch
        else:
            switch = str(raw_switch).strip().lower() in ("1", "true", "yes", "on")
        stdout, stderr, rc = _ps_create_desktop(name=name, switch=switch)
        payload, status = _parse_ps_json(stdout, stderr, rc)
        if status == 200 and isinstance(payload, dict):
            payload["switched"] = switch
            _log(f"vdesk/create name={name!r} switch={switch} -> {payload}")
        return jsonify(payload), status

    @app.route("/vdesk/switch", methods=["POST"])
    @require_auth
    def route_vdesk_switch():
        if os.name != "nt":
            return _windows_only()
        body = _json_body() or {}
        if not isinstance(body, dict):
            body = {}
        index = body.get("index")
        name = body.get("name")
        if index is None and not (isinstance(name, str) and name.strip()):
            return _missing_field("index")
        try:
            idx = int(index) if index is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "index must be an integer"}), 400
        stdout, stderr, rc = _ps_switch_desktop(index=idx, name=name)
        payload, status = _parse_ps_json(stdout, stderr, rc)
        if status == 200:
            _log(f"vdesk/switch index={idx} name={name!r} -> {payload}")
        return jsonify(payload), status

    @app.route("/vdesk/move", methods=["POST"])
    @require_auth
    def route_vdesk_move():
        if os.name != "nt":
            return _windows_only()
        body = _json_body() or {}
        if not isinstance(body, dict):
            body = {}
        hwnd = body.get("hwnd")
        title = body.get("title")
        index = body.get("index")
        name = body.get("name")

        if hwnd is None and not (isinstance(title, str) and title.strip()):
            return _missing_field("hwnd")
        if index is None and not (isinstance(name, str) and name.strip()):
            return _missing_field("index")

        try:
            hwnd_i = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "hwnd must be an integer"}), 400
        try:
            idx = int(index) if index is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "index must be an integer"}), 400

        stdout, stderr, rc = _ps_move_window(
            hwnd=hwnd_i, title=title, index=idx, name=name
        )
        payload, status = _parse_ps_json(stdout, stderr, rc)
        if status == 200:
            _log(
                f"vdesk/move hwnd={hwnd_i} title={title!r} "
                f"index={idx} name={name!r} -> {payload}"
            )
        return jsonify(payload), status
