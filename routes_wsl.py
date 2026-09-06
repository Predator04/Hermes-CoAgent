"""WSL (Windows Subsystem for Linux) workload management (issue #1565).

Manage WSL distros directly from CoAgent: list distros and their state,
run arbitrary commands inside a distro (capturing stdout + exit code), start /
terminate / shut down distros, and list listening TCP ports inside a distro.

Endpoints:
    GET  /wsl/distros  - list distros (name, state, version, is_default)
    POST /wsl/run      - run a command in a distro, capture stdout/stderr/exit
    POST /wsl/start    - ensure a distro is running
    POST /wsl/shutdown - shutdown all distros, or terminate one (distro field)
    GET  /wsl/ports    - list listening TCP ports inside a distro

Wraps `wsl.exe` via subprocess (list form, so no Windows shell interpolation).
The command body is passed as a single argv element to `sh -c` inside the
distro, which is the intended semantic (agent-supplied shell command). Distro
names are regex-validated. Returns HTTP 501 when WSL is unavailable or on
non-Windows hosts, so the Linux syntax-check CI stays green.
"""

import os
import re
import shutil
import subprocess

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

_DISTRO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MAX_OUTPUT = 200_000  # cap captured stdout/stderr per run


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (WSL unavailable)"}
    if detail:
        payload["detail"] = str(detail)[:300]
    return jsonify(payload), 501


def _run(args, timeout=60, encoding=None):
    """Run a subprocess list. Returns (rc, stdout, stderr).

    ``encoding`` overrides output decoding: wsl.exe list output is UTF-16,
    while commands run inside a distro emit UTF-8 (the default here).
    """
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        out = _decode(r.stdout, encoding)
        err = _decode(r.stderr, encoding)
        return r.returncode, out, err
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", "wsl.exe not found"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def _decode(data, encoding=None):
    """Decode subprocess output bytes, preferring ``encoding`` then UTF-8."""
    if not data:
        return ""
    if encoding:
        try:
            return data.decode(encoding, errors="replace")[:_MAX_OUTPUT]
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")[:_MAX_OUTPUT]


def _wsl_available():
    if os.name != "nt":
        return False, "not Windows"
    if shutil.which("wsl.exe") is None and shutil.which("wsl") is None:
        return False, "wsl.exe not on PATH"
    rc, out, err = _run(["wsl.exe", "--list", "--quiet"], timeout=20)
    if rc != 0:
        return False, (err or out or "wsl.exe --list failed").strip()
    return True, ""


def _parse_distro_list(out):
    """Parse `wsl.exe --list --verbose` output into a list of distro dicts."""
    distros = []
    in_header = True
    for raw in out.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if in_header:
            # Header line looks like "  NAME            STATE           VERSION"
            if "NAME" in line.upper() and "STATE" in line.upper():
                in_header = False
            continue
        m = re.match(r"^\s*(\*?)\s+(.+?)\s+(Running|Stopped|Converting|Uninstalling|Installing|InstallFailed|Unknown)\s+(\d+)\s*$", line)
        if not m:
            continue
        star, name, state, version = m.groups()
        distros.append({
            "name": name.strip(),
            "state": state,
            "version": int(version),
            "is_default": star == "*",
        })
    return distros


def _valid_distro(name):
    return isinstance(name, str) and bool(_DISTRO_RE.fullmatch(name))


def _resolve_distro(payload):
    """Return a validated distro name, or None for the default distro."""
    name = (payload or {}).get("distro")
    if name in (None, ""):
        return None
    if not _valid_distro(name):
        return _missing_field("distro")
    return name


def register_routes(app, state=None, require_auth=None):
    @app.route("/wsl/distros", methods=["GET"])
    @require_auth
    def wsl_distros():
        ok, detail = _wsl_available()
        if not ok:
            return _windows_only(detail)
        rc, out, err = _run(["wsl.exe", "--list", "--verbose"], timeout=30, encoding="utf-16")
        if rc != 0:
            return jsonify({"error": "Failed to list WSL distros", "detail": (err or out).strip()}), 500
        return jsonify({"distros": _parse_distro_list(out)})

    @app.route("/wsl/run", methods=["POST"])
    @require_auth
    def wsl_run():
        ok, detail = _wsl_available()
        if not ok:
            return _windows_only(detail)
        payload = _json_body()
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            return _missing_field("command")
        distro = _resolve_distro(payload)
        if isinstance(distro, tuple):
            return distro
        timeout = payload.get("timeout")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not (1 <= timeout <= 600):
            timeout = 120

        args = ["wsl.exe"]
        if distro:
            args += ["-d", distro]
        args += ["--", "sh", "-c", command]
        rc, out, err = _run(args, timeout=timeout)
        return jsonify({
            "ok": rc == 0,
            "exit_code": rc,
            "stdout": out,
            "stderr": err,
        })

    @app.route("/wsl/start", methods=["POST"])
    @require_auth
    def wsl_start():
        ok, detail = _wsl_available()
        if not ok:
            return _windows_only(detail)
        payload = _json_body()
        distro = _resolve_distro(payload)
        if isinstance(distro, tuple):
            return distro
        args = ["wsl.exe"]
        if distro:
            args += ["-d", distro]
        args += ["--", "sh", "-c", "true"]
        rc, out, err = _run(args, timeout=90)
        return jsonify({"ok": rc == 0, "exit_code": rc, "detail": (err or out).strip()})

    @app.route("/wsl/shutdown", methods=["POST"])
    @require_auth
    def wsl_shutdown():
        ok, detail = _wsl_available()
        if not ok:
            return _windows_only(detail)
        payload = _json_body()
        distro = (payload or {}).get("distro")
        if distro in (None, ""):
            rc, out, err = _run(["wsl.exe", "--shutdown"], timeout=90)
            return jsonify({"ok": rc == 0, "exit_code": rc, "detail": (err or out).strip()})
        if not _valid_distro(distro):
            return _missing_field("distro")
        rc, out, err = _run(["wsl.exe", "--terminate", distro], timeout=90)
        return jsonify({"ok": rc == 0, "exit_code": rc, "detail": (err or out).strip()})

    @app.route("/wsl/ports", methods=["GET"])
    @require_auth
    def wsl_ports():
        ok, detail = _wsl_available()
        if not ok:
            return _windows_only(detail)
        distro = request.args.get("distro") or ""
        if distro and not _valid_distro(distro):
            return _missing_field("distro")
        args = ["wsl.exe"]
        if distro:
            args += ["-d", distro]
        # ss is present on modern distros; fall back to netstat otherwise.
        args += ["--", "sh", "-c", "ss -tlnH 2>/dev/null || netstat -tln 2>/dev/null"]
        rc, out, err = _run(args, timeout=60)
        if rc != 0:
            return jsonify({"error": "Failed to list ports", "detail": (err or out).strip()}), 500
        return jsonify({"ports": _parse_ports(out)})


def _parse_ports(out):
    """Parse `ss -tlnH` / `netstat -tln` output into [{proto, port, local}]."""
    ports = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        # ss -tlnH:  LISTEN 0 128 127.0.0.1:6379 0.0.0.0:*
        # netstat:   tcp    0 0   0.0.0.0:8080  0.0.0.0:* LISTEN
        # Both put the Local Address:Port in the 4th column (index 3).
        m = re.search(r":(\d{1,5})\s+\S+:\*", line)
        if not m:
            continue
        tokens = line.split()
        if len(tokens) < 4:
            continue
        proto = "udp" if tokens[0].lower().startswith("udp") else "tcp"
        ports.append({
            "proto": proto,
            "port": int(m.group(1)),
            "local": tokens[3],
        })
    # Dedupe on (proto, port) while preserving order.
    seen = set()
    unique = []
    for p in ports:
        key = (p["proto"], p["port"])
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
