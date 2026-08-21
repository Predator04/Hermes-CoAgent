"""Safety checkpoint & one-click rollback for autonomous runs.

Ties together the raw ingredients CoAgent already ships (vssadmin, config
backup, undo) into a pre-run checkpoint workflow: create a System Restore Point
(and optionally a VSS shadow copy) before a risky goal run, then list and
roll back from the dashboard if the run goes wrong.

Endpoints:
    POST /checkpoint/create   — create a System Restore Point (+ optional VSS shadow)
    GET  /checkpoint/list     — list recent restore points
    POST /checkpoint/rollback — restore to a point (requires confirm:true + sequence)
"""

import json
import re
import subprocess

from flask import jsonify

from shared import _json_body, _log


def _ps(script, timeout=120):
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found (not on Windows?)", -1


def _create_restore_point(description):
    desc = description or "CoAgent pre-run checkpoint"
    if len(desc) > 256:
        desc = desc[:256]
    desc = desc.replace("'", "''")
    script = "Checkpoint-Computer -Description '%s' -RestorePointType 'APPLICATION_INSTALL'" % desc
    out, err, code = _ps(script, timeout=180)
    if code != 0:
        return False, (err or out or "exit code %d" % code)
    return True, out


def _create_shadow(volume="C:"):
    if not re.fullmatch(r"[A-Za-z]:", volume or ""):
        return False, "invalid volume (expected a single drive letter, e.g. 'C:')"
    script = "vssadmin create shadow /for=%s" % volume
    out, err, code = _ps(script, timeout=120)
    if code != 0:
        return False, (err or out or "exit code %d" % code)
    return True, out


def _list_restore_points():
    script = "Get-ComputerRestorePoint | Select-Object SequenceNumber, Description, CreationTime | ConvertTo-Json"
    out, err, code = _ps(script, timeout=60)
    if code != 0:
        return None, (err or out or "exit code %d" % code)
    return out, None


def _rollback(sequence):
    try:
        seq = int(sequence)
    except (TypeError, ValueError):
        return False, "invalid sequence number"
    if seq <= 0:
        return False, "sequence number must be positive"
    script = "Restore-Computer -RestorePoint %d -Confirm:$false" % seq
    out, err, code = _ps(script, timeout=60)
    if code != 0:
        return False, (err or out or "exit code %d" % code)
    return True, out


def register_routes(app, state, require_auth):
    @app.route("/checkpoint/create", methods=["POST"])
    @require_auth
    def route_checkpoint_create():
        data = _json_body() or {}
        description = data.get("description") or "CoAgent pre-run checkpoint"
        do_shadow = bool(data.get("shadow", False))
        volume = data.get("volume") or "C:"
        ok, msg = _create_restore_point(description)
        result = {"restore_point": {"ok": ok, "detail": msg}}
        if do_shadow:
            sok, smsg = _create_shadow(volume)
            result["shadow_copy"] = {"ok": sok, "detail": smsg, "volume": volume}
        _log("checkpoint: create -> restore_point_ok=%s" % ok)
        return jsonify(result), (200 if ok else 500)

    @app.route("/checkpoint/list", methods=["GET"])
    @require_auth
    def route_checkpoint_list():
        raw, err = _list_restore_points()
        if err:
            return jsonify({"error": err, "raw": raw}), 500
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                parsed = [parsed]
        except Exception:
            parsed = raw
        return jsonify({"restore_points": parsed, "raw": raw})

    @app.route("/checkpoint/rollback", methods=["POST"])
    @require_auth
    def route_checkpoint_rollback():
        data = _json_body() or {}
        confirm = bool(data.get("confirm", False))
        sequence = data.get("sequence")
        if not confirm:
            return jsonify({"error": "rollback requires confirm:true (system restart + irreversible)"}), 400
        if sequence is None:
            return jsonify({"error": "sequence number is required"}), 400
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            return jsonify({"error": "sequence number must be an integer"}), 400
        if sequence <= 0:
            return jsonify({"error": "sequence number must be positive"}), 400
        ok, msg = _rollback(sequence)
        _log("checkpoint: rollback sequence=%s -> ok=%s" % (sequence, ok))
        return jsonify({"ok": ok, "detail": msg, "note": "System Restore will reboot the machine if it succeeds."}), (200 if ok else 500)
