"""Hyper-V virtual machine lifecycle routes (issue #1182).

Endpoints:
  GET  /vm/list             - list VMs (name, state, generation, cpu/mem)
  POST /vm/status           - inspect a single VM by name
  POST /vm/start            - start a VM
  POST /vm/stop             - turn off a VM (force)
  POST /vm/shutdown         - graceful guest shutdown
  POST /vm/save             - save VM state
  POST /vm/pause            - pause (suspend) a VM
  POST /vm/resume           - resume a paused/saved VM
  POST /vm/checkpoint       - create a checkpoint
  POST /vm/restore          - restore a VM to a checkpoint (snapshot rollback)
  GET  /vm/checkpoints      - list checkpoints for a VM
  POST /vm/checkpoint/remove - delete a checkpoint

Wraps the Windows Hyper-V PowerShell module. Returns HTTP 501 when the Hyper-V
feature is unavailable (or on non-Windows hosts), so the Linux syntax-check CI
stays green. VM/checkpoint names are passed via environment variables rather
than inline string interpolation to avoid command injection.
"""

import os
import re
import subprocess

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

_VM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,127}$")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (Hyper-V unavailable)"}
    if detail:
        payload["detail"] = detail[:300]
    return jsonify(payload), 501


def _valid_vm_name(name):
    return isinstance(name, str) and bool(_VM_NAME_RE.fullmatch(name))


def _run_ps(script, extra_env=None, timeout=90):
    """Run a PowerShell -Command snippet. Returns (rc, stdout, stderr)."""
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", script]
    env = None
    if extra_env:
        env = dict(os.environ)
        env.update(extra_env)
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "", "timed out"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def _hyperv_available():
    """Return (ok, detail). ok is True when the Hyper-V module is usable."""
    if os.name != "nt":
        return False, "not Windows"
    rc, out, err = _run_ps(
        "if(Get-Command Get-VM -ErrorAction SilentlyContinue){'yes'}else{'no'}"
    )
    return out.strip().lower() == "yes", (err or "").strip()


def _vm_info_script():
    return (
        "Get-VM -Name $env:COAGENT_VM | Select-Object Name,State,Generation,Status,"
        "@{n='ProcessorCount';e={$_.ProcessorCount}},"
        "@{n='MemoryStartup';e={[long]$_.MemoryStartup}},"
        "@{n='Uptime';e={$_.Uptime}} | ConvertTo-Json -Compress"
    )


def _parse_vm_json(out):
    import json as _json
    text = (out or "").strip()
    if not text:
        return []
    try:
        return _json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _run_vm_action(script, extra_env=None, timeout=90):
    rc, out, err = _run_ps(script, extra_env=extra_env, timeout=timeout)
    if rc != 0:
        return False, (err or out).strip()[:400]
    return True, (out or "").strip()


def register_routes(app, state, require_auth):

    @app.route("/vm/list", methods=["GET"])
    @require_auth
    def route_vm_list():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        script = (
            "Get-VM | Select-Object Name,State,Generation,Status,"
            "@{n='ProcessorCount';e={$_.ProcessorCount}},"
            "@{n='MemoryStartup';e={[long]$_.MemoryStartup}},"
            "@{n='Uptime';e={$_.Uptime}} | ConvertTo-Json -Compress"
        )
        rc, out, err = _run_ps(script)
        if rc != 0:
            return jsonify({"error": (err or out).strip()[:400]}), 500
        data = _parse_vm_json(out)
        if data is None:
            return jsonify({"error": "unexpected VM list output",
                            "detail": (out or "").strip()[:400]}), 500
        vms = []
        if isinstance(data, dict):
            vms = [data]
        elif isinstance(data, list):
            vms = data
        return jsonify({"count": len(vms), "vms": vms})

    @app.route("/vm/status", methods=["POST"])
    @require_auth
    def route_vm_status():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        rc, out, err = _run_ps(_vm_info_script(), extra_env={"COAGENT_VM": name})
        if rc != 0:
            return jsonify({"error": (err or out).strip()[:400]}), 500
        data = _parse_vm_json(out)
        if data is None:
            return jsonify({"error": "unexpected VM status output",
                            "detail": (out or "").strip()[:400]}), 500
        return jsonify({"vm": data})

    @app.route("/vm/start", methods=["POST"])
    @require_auth
    def route_vm_start():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Start-VM -Name $env:COAGENT_VM",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "start", "vm": name})

    @app.route("/vm/stop", methods=["POST"])
    @require_auth
    def route_vm_stop():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Stop-VM -Name $env:COAGENT_VM -TurnOff -Force",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "stop", "vm": name})

    @app.route("/vm/shutdown", methods=["POST"])
    @require_auth
    def route_vm_shutdown():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Stop-VM -Name $env:COAGENT_VM -Force",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "shutdown", "vm": name})

    @app.route("/vm/save", methods=["POST"])
    @require_auth
    def route_vm_save():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Save-VM -Name $env:COAGENT_VM",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "save", "vm": name})

    @app.route("/vm/pause", methods=["POST"])
    @require_auth
    def route_vm_pause():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Suspend-VM -Name $env:COAGENT_VM",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "pause", "vm": name})

    @app.route("/vm/resume", methods=["POST"])
    @require_auth
    def route_vm_resume():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        ok2, detail = _run_vm_action("Resume-VM -Name $env:COAGENT_VM",
                                     extra_env={"COAGENT_VM": name})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "resume", "vm": name})

    @app.route("/vm/checkpoint", methods=["POST"])
    @require_auth
    def route_vm_checkpoint():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        snap = body.get("snapshot") or body.get("snapshot_name") or ""
        if not isinstance(snap, str) or len(snap) > 160:
            return jsonify({"error": "invalid snapshot name"}), 400
        if not snap:
            import time as _time
            import secrets as _secrets
            snap = ("CoAgent " + _time.strftime("%Y-%m-%d %H-%M-%S")
                    + "-" + _secrets.token_hex(2))
        script = ("Checkpoint-VM -Name $env:COAGENT_VM -SnapshotName $env:COAGENT_CP "
                  "-Confirm:$false")
        ok2, detail = _run_vm_action(
            script, extra_env={"COAGENT_VM": name, "COAGENT_CP": snap})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "checkpoint", "vm": name,
                        "snapshot": snap})

    @app.route("/vm/restore", methods=["POST"])
    @require_auth
    def route_vm_restore():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        snap = body.get("snapshot") or body.get("snapshot_name")
        if not isinstance(snap, str) or not snap:
            return _missing_field("snapshot")
        script = ("Restore-VMCheckpoint -Name $env:COAGENT_CP -VMName $env:COAGENT_VM "
                  "-Confirm:$false")
        ok2, detail = _run_vm_action(
            script, extra_env={"COAGENT_VM": name, "COAGENT_CP": snap})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "restore", "vm": name,
                        "snapshot": snap})

    @app.route("/vm/checkpoints", methods=["GET", "POST"])
    @require_auth
    def route_vm_checkpoints():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        name = None
        if request.method == "POST":
            body = _json_body()
            name = body.get("name") or body.get("vm")
        else:
            name = request.args.get("name") or request.args.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        script = (
            "Get-VMCheckpoint -VMName $env:COAGENT_VM | "
            "Select-Object Name,SnapshotType,CreationTime,@{n='Path';e={$_.Path}} | "
            "ConvertTo-Json -Compress"
        )
        rc, out, err = _run_ps(script, extra_env={"COAGENT_VM": name})
        if rc != 0:
            return jsonify({"error": (err or out).strip()[:400]}), 500
        data = _parse_vm_json(out)
        if data is None:
            return jsonify({"error": "unexpected checkpoint list output",
                            "detail": (out or "").strip()[:400]}), 500
        cps = []
        if isinstance(data, dict):
            cps = [data]
        elif isinstance(data, list):
            cps = data
        return jsonify({"count": len(cps), "checkpoints": cps})

    @app.route("/vm/checkpoint/remove", methods=["POST"])
    @require_auth
    def route_vm_checkpoint_remove():
        ok, err = _hyperv_available()
        if not ok:
            return _windows_only(err)
        body = _json_body()
        name = body.get("name") or body.get("vm")
        if not _valid_vm_name(name):
            return jsonify({"error": "invalid vm name"}), 400
        snap = body.get("snapshot") or body.get("snapshot_name")
        if not isinstance(snap, str) or not snap:
            return _missing_field("snapshot")
        script = ("Remove-VMCheckpoint -Name $env:COAGENT_CP -VMName $env:COAGENT_VM "
                  "-Confirm:$false")
        ok2, detail = _run_vm_action(
            script, extra_env={"COAGENT_VM": name, "COAGENT_CP": snap})
        if not ok2:
            return jsonify({"error": detail}), 500
        return jsonify({"status": "ok", "action": "remove_checkpoint", "vm": name,
                        "snapshot": snap})

    _log("Hyper-V VM routes registered")
