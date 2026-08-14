# Auto-added feature: hasherezade/pe-sieve (3853 stars)
# Process scanner that detects and dumps malware implants (process hollowing, injected PEs, hooks, shellcode)
# Source: https://github.com/hasherezade/pe-sieve
# Install: no winget/scoop — download pe-sieve.exe + libs from https://github.com/hasherezade/pe-sieve/releases

import glob
import os
import re
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "hasherezade/pe-sieve",
    "stars": 3853,
    "desc": "PE-sieve is a lightweight process scanner that detects malware running on the system and dumps the malicious material for analysis. It recognizes and dumps replaced/injected PEs, shellcode, inline hooks, and other in-memory patches — including process hollowing, process doppelgaenging, and reflective DLL injection. Runs as a single-process scanner (EXE) or embeddable DLL. Emits a JSON report with /json.",
    "url": "https://github.com/hasherezade/pe-sieve",
    "added": "2026-08-13",
    "command": "pe-sieve.exe /pid <PID> [/json] [/dmode <A|D|V|U|R|N>] [/quiet] [/minidmp] [/dir <out>]",
    "install": {
        "manual": "Download pe-sieve64.zip from https://github.com/hasherezade/pe-sieve/releases and extract to a folder on PATH (or C:\\tools\\pe-sieve)",
        "note": "Not published on winget or scoop. Best-effort: place pe-sieve.exe in a PATH dir.",
    },
    "endpoints": {
        "/auto/pe_sieve/info": "Feature metadata, install status, version",
        "/auto/pe_sieve/ping": "Health check",
        "/auto/pe_sieve/scan": "POST — scan a live process by PID for implants/injections (json, dmode, quiet, minidump, dir)",
    },
}

_DMODE_WHITELIST = {"A", "D", "V", "U", "R", "N"}


def _find_pesieve():
    """Locate pe-sieve.exe on this system."""
    for name in ("pe-sieve.exe", "pe-sieve"):
        exe = shutil.which(name)
        if exe:
            return exe
    candidates = [
        r"C:\tools\pe-sieve\pe-sieve.exe",
        r"C:\pe-sieve\pe-sieve.exe",
        os.path.expandvars(r"%USERPROFILE%\Downloads\pe-sieve\pe-sieve.exe"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\pe-sieve64\pe-sieve.exe"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\pe-sieve\pe-sieve.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\pe-sieve\pe-sieve.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    """pe-sieve has no --version flag; extract from its banner."""
    for flag in ("--version", "/version"):
        try:
            r = subprocess.run([exe, flag], capture_output=True, text=True, timeout=5)
            out = (r.stdout.strip() or r.stderr.strip())
            if out:
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out)
                if m:
                    return m.group(1)
        except Exception:
            pass
    # Fallback: run bare and regex the banner
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        m = re.search(r"[Vv]ersion[:\s]+(\d+\.\d+(?:\.\d+)?)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "unknown"


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def register_routes(app, state, require_auth):
    @app.route("/auto/pe_sieve/info", methods=["GET"])
    @require_auth
    def route_auto_pe_sieve_info():
        info = dict(FEATURE_INFO)
        exe = _find_pesieve()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/pe_sieve/ping", methods=["GET"])
    @require_auth
    def route_auto_pe_sieve_ping():
        exe = _find_pesieve()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "hasherezade/pe-sieve",
            "path": exe,
        })

    @app.route("/auto/pe_sieve/scan", methods=["POST"])
    @require_auth
    def route_auto_pe_sieve_scan():
        """Scan a live process for implants/injections.
        Body: {"pid": 1234, "json": true, "dmode": "A", "quiet": false, "minidump": false, "dir": "C:\\out"}
        """
        body = _json_body()
        if not isinstance(body, dict):
            return _missing_field("pid")
        pid = body.get("pid")
        if pid is None:
            return _missing_field("pid")

        try:
            pid = int(pid)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid PID: {pid}"}), 400

        if pid <= 0:
            return jsonify({"error": "PID must be a positive integer"}), 400

        json_out = _as_bool(body.get("json"), True)
        quiet = _as_bool(body.get("quiet"), False)
        minidump = _as_bool(body.get("minidump"), False)
        dmode = str(body.get("dmode") or "A").strip().upper()
        out_dir = body.get("dir", "")
        if out_dir is not None:
            out_dir = str(out_dir)
            if any(ord(c) < 32 for c in out_dir):
                return jsonify({"error": "dir cannot contain control characters"}), 400
            if out_dir.startswith("-") or out_dir.startswith("/"):
                return jsonify({"error": "dir must be a directory path, not a CLI flag"}), 400

        if dmode and dmode not in _DMODE_WHITELIST:
            return jsonify({
                "error": f"Invalid dmode '{dmode}'. Allowed: {', '.join(sorted(_DMODE_WHITELIST))}",
            }), 400

        exe = _find_pesieve()
        if not exe:
            return jsonify({
                "error": "pe-sieve not installed",
                "hint": "Download from https://github.com/hasherezade/pe-sieve/releases and place pe-sieve.exe on PATH",
            }), 503

        try:
            cmd = [exe, "/pid", str(pid)]
            if json_out:
                cmd.append("/json")
            if dmode:
                cmd.extend(["/dmode", dmode])
            if quiet:
                cmd.append("/quiet")
            if minidump:
                cmd.append("/minidmp")
            if out_dir:
                cmd.extend(["/dir", str(out_dir)])

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

            output = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            # pe-sieve returns non-zero when no suspicious content is found in
            # some modes, or when the process can't be opened without admin.
            return jsonify({
                "pid": pid,
                "exit_code": r.returncode,
                "dmode": dmode,
                "json_requested": json_out,
                "minidump": minidump,
                "report": output.strip() or "(no output)",
            })
        except subprocess.TimeoutExpired:
            _log("pe_sieve_scan", f"scan of PID {pid} timed out")
            return jsonify({"error": "pe-sieve scan timed out after 90s", "pid": pid}), 504
        except Exception as e:
            _log("pe_sieve_scan", f"Error scanning PID {pid}: {e}")
            return jsonify({"error": str(e), "pid": pid}), 500
