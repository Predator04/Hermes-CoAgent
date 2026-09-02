"""Smart application launcher routes.

Endpoint:
  POST /launch/app - launch executables, documents, shortcuts (.lnk), or
                     URLs with optional arguments, working directory, and
                     window state (normal / maximized / minimized / hidden).

Windows-only. Uses subprocess.Popen, os.startfile, and ShellExecuteW so the
OS resolves file associations and honors the requested nCmdShow flag. The
ctypes import is guarded so the Linux syntax-check CI stays green.
"""

import math
import os
import shlex
import subprocess
import webbrowser
from urllib.parse import urlparse

from flask import jsonify

from shared import _json_body, _log, _missing_field


try:
    import ctypes
    _HAS_CTYPES = True
except Exception:
    ctypes = None
    _HAS_CTYPES = False


# Standard Win32 ShowWindow / nCmdShow constants.
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3

_WINDOW_STATE_MAP = {
    "normal": SW_SHOWNORMAL,
    "default": SW_SHOWNORMAL,
    "show": SW_SHOWNORMAL,
    "maximized": SW_SHOWMAXIMIZED,
    "maximize": SW_SHOWMAXIMIZED,
    "max": SW_SHOWMAXIMIZED,
    "minimized": SW_SHOWMINIMIZED,
    "minimize": SW_SHOWMINIMIZED,
    "min": SW_SHOWMINIMIZED,
    "hidden": SW_HIDE,
    "hide": SW_HIDE,
}

_URL_SCHEMES = {"http", "https", "mailto", "ftp", "ftps", "file", "steam", "spotify"}
_EXE_SUFFIXES = (".exe", ".bat", ".cmd", ".com")


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _is_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    scheme = parsed.scheme.lower()
    if scheme not in _URL_SCHEMES:
        return False
    # Reject Windows drive-letter paths ("C:\\foo" parses scheme "c").
    if len(scheme) == 1 and "://" not in value:
        return False
    return True


def _normalize_args(raw):
    """Accept a list of args or a shell-style string; return list[str]."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(a) for a in raw]
    if isinstance(raw, str):
        try:
            return shlex.split(raw, posix=False)
        except ValueError:
            return [raw]
    return [str(raw)]


def _resolve_window_state(raw):
    """Return (nCmdShow int, label str)."""
    if raw is None or raw == "":
        return SW_SHOWNORMAL, "normal"
    if isinstance(raw, bool):
        return SW_SHOWNORMAL, "normal"
    if isinstance(raw, int):
        return int(raw), str(raw)
    key = str(raw).strip().lower()
    if key in _WINDOW_STATE_MAP:
        return _WINDOW_STATE_MAP[key], key
    return SW_SHOWNORMAL, "normal"


def _shell_execute(path, args, cwd, show):
    """Wrap ShellExecuteW. Returns (hInstance_int, error_or_none).

    hInstance > 32 means success per the Win32 docs.
    """
    if not _HAS_CTYPES:
        return 0, "ctypes not available"
    params = subprocess.list2cmdline(args) if args else None
    try:
        h = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            path,
            params,
            cwd,
            int(show),
        )
        h = int(h)
    except Exception as exc:
        return 0, str(exc)
    if h <= 32:
        return h, f"ShellExecute failed (hinstance={h})"
    return h, None


def register_routes(app, state, require_auth):

    @app.route("/launch/app", methods=["POST"])
    @require_auth
    def route_launch_app():
        if os.name != "nt":
            return _windows_only()

        body = _json_body() or {}
        target = (
            body.get("app")
            or body.get("path")
            or body.get("target")
            or body.get("url")
            or ""
        )
        target = str(target).strip()
        if not target:
            return _missing_field("app")

        args = _normalize_args(body.get("args"))
        cwd_raw = body.get("cwd")
        cwd = str(cwd_raw) if cwd_raw else None
        if cwd is not None and not os.path.isdir(cwd):
            return jsonify({"error": f"cwd not a directory: {cwd}"}), 400

        show, window_label = _resolve_window_state(body.get("window"))
        wait = bool(body.get("wait", False))
        timeout_raw = body.get("timeout")
        try:
            wait_timeout = float(timeout_raw) if timeout_raw is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "timeout must be numeric"}), 400
        if wait_timeout is not None and (not math.isfinite(wait_timeout) or wait_timeout < 0):
            return jsonify({"error": "timeout must be a finite non-negative number"}), 400

        response = {
            "status": "launched",
            "target": target,
            "args": args,
            "window": window_label,
            "cwd": cwd,
        }

        # 1) URLs -> default browser / URL protocol handler.
        if _is_url(target):
            try:
                webbrowser.open_new_tab(target)
                response["mode"] = "url"
                _log(f"launch/app url {target}")
                return jsonify(response)
            except Exception as exc:
                return jsonify({"error": f"URL open failed: {exc}"}), 500

        low = target.lower()
        is_shortcut = low.endswith(".lnk")
        is_executable = low.endswith(_EXE_SUFFIXES)
        exists = os.path.exists(target)

        # 2) Shortcuts, documents, or non-exe targets -> ShellExecuteW so the
        # OS resolves the association and applies nCmdShow.
        if is_shortcut or (exists and not is_executable):
            # Fast path: os.startfile handles plain document opens without args.
            if not args and show == SW_SHOWNORMAL and not is_shortcut:
                try:
                    os.startfile(target)
                    response["mode"] = "startfile"
                    _log(f"launch/app startfile {target}")
                    return jsonify(response)
                except OSError as exc:
                    return jsonify({"error": f"startfile failed: {exc}"}), 500

            h, err = _shell_execute(target, args, cwd, show)
            if err:
                return jsonify({"error": err, "hinstance": h}), 500
            response["mode"] = "shellexecute"
            response["hinstance"] = h
            _log(f"launch/app shellexecute {target} show={show}")
            return jsonify(response)

        # 3) Executables (or bare command names resolved via PATH) -> Popen
        # so we can capture the PID and honor wait/timeout. wShowWindow is
        # supplied via STARTUPINFO. _show_window=True stops the shared.py
        # Popen wrapper from forcing CREATE_NO_WINDOW / SW_HIDE.
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = int(show)

            cmd = [target] + args
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                startupinfo=startupinfo,
                _show_window=(show != SW_HIDE),
            )
            response["mode"] = "popen"
            response["pid"] = proc.pid

            if wait:
                try:
                    response["returncode"] = proc.wait(timeout=wait_timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    return jsonify({"error": "process timed out", "pid": proc.pid}), 504

            _log(f"launch/app popen {target} pid={proc.pid} show={show}")
            return jsonify(response)
        except FileNotFoundError as exc:
            return jsonify({"error": f"not found: {exc}"}), 404
        except OSError as exc:
            return jsonify({"error": f"launch failed: {exc}"}), 500
