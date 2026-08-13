# Auto-added feature: Genymobile/scrcpy (147497 stars)
# Display and control your Android device from Windows
# Source: https://github.com/Genymobile/scrcpy
# Install: winget install Genymobile.scrcpy  OR  scoop install scrcpy

import glob
import shutil
import subprocess
import os
import tempfile
import json
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "Genymobile/scrcpy",
    "stars": 147497,
    "desc": "scrcpy provides display and control of Android devices connected via USB or TCP/IP. Mirror your phone screen, record video, use the device camera as a webcam, and automate interactions — all from the command line. Supports headless operation with --no-window for server-side automation.",
    "url": "https://github.com/Genymobile/scrcpy",
    "added": "2026-08-12",
    "command": "scrcpy [--list-displays] [--no-window] [--record=file.mp4] [--video-source=camera]",
    "install": {
        "winget": "winget install Genymobile.scrcpy",
        "scoop": "scoop install scrcpy",
    },
    "endpoints": {
        "/auto/scrcpy/info": "Feature metadata, install status, version",
        "/auto/scrcpy/ping": "Health check",
        "/auto/scrcpy/devices": "GET — list connected Android devices via adb",
        "/auto/scrcpy/displays": "GET — list available displays on connected device",
        "/auto/scrcpy/record": "POST — start/stop headless screen recording",
    },
}

def _find_scrcpy():
    """Locate scrcpy on this system."""
    exe = shutil.which("scrcpy")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Genymobile.scrcpy_*\scrcpy.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\scrcpy.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\scrcpy\current\scrcpy.exe"),
    ]
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None


def _find_adb():
    """Locate adb — scrcpy ships its own or uses system adb."""
    exe = shutil.which("adb")
    if exe:
        return exe
    # scrcpy bundles adb in its install dir
    scrcpy = _find_scrcpy()
    if scrcpy:
        adb_dir = os.path.join(os.path.dirname(scrcpy), "adb.exe")
        if os.path.isfile(adb_dir):
            return adb_dir
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\adb.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):
    @app.route("/auto/scrcpy/info", methods=["GET"])
    @require_auth
    def route_auto_scrcpy_info():
        info = dict(FEATURE_INFO)
        exe = _find_scrcpy()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        adb = _find_adb()
        info["adb_available"] = adb is not None
        if adb:
            info["adb_path"] = adb
        return jsonify(info)

    @app.route("/auto/scrcpy/ping", methods=["GET"])
    @require_auth
    def route_auto_scrcpy_ping():
        exe = _find_scrcpy()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "Genymobile/scrcpy",
            "path": exe,
        })

    @app.route("/auto/scrcpy/devices", methods=["GET"])
    @require_auth
    def route_auto_scrcpy_devices():
        """List connected Android devices via adb."""
        adb = _find_adb()
        if not adb:
            return jsonify({
                "error": "adb not found — install Android SDK platform-tools or install scrcpy",
                "devices": [],
                "count": 0,
            }), 200

        try:
            r = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=10)
            lines = r.stdout.strip().split("\n")[1:]  # skip header
            devices = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    status = parts[1]
                    props = {}
                    for p in parts[2:]:
                        if ":" in p:
                            k, v = p.split(":", 1)
                            props[k] = v
                    devices.append({"serial": serial, "status": status, "properties": props})

            return jsonify({
                "devices": devices,
                "count": len(devices),
                "connected": any(d["status"] == "device" for d in devices),
            })
        except subprocess.TimeoutExpired:
            _log("scrcpy_devices", "adb devices timed out")
            return jsonify({"error": "adb timed out", "devices": [], "count": 0}), 504
        except Exception as e:
            _log("scrcpy_devices", f"Error: {e}")
            return jsonify({"error": str(e), "devices": [], "count": 0}), 500

    @app.route("/auto/scrcpy/displays", methods=["GET"])
    @require_auth
    def route_auto_scrcpy_displays():
        """List available displays on the first connected device."""
        scrcpy = _find_scrcpy()
        if not scrcpy:
            return jsonify({"error": "scrcpy not installed", "displays": [], "count": 0}), 200

        try:
            r = subprocess.run(
                [scrcpy, "--list-displays"],
                capture_output=True, text=True, timeout=15
            )
            output = r.stdout.strip()
            displays = []
            for line in output.split("\n"):
                line = line.strip()
                if line and "display" in line.lower():
                    displays.append(line)

            return jsonify({
                "displays": displays,
                "count": len(displays),
                "raw": output[:2000],
            })
        except subprocess.TimeoutExpired:
            _log("scrcpy_displays", "scrcpy --list-displays timed out (no device connected?)")
            return jsonify({"error": "Timed out — is a device connected and USB debugging enabled?", "displays": [], "count": 0}), 504
        except Exception as e:
            _log("scrcpy_displays", f"Error: {e}")
            return jsonify({"error": str(e), "displays": [], "count": 0}), 500

    @app.route("/auto/scrcpy/record", methods=["POST"])
    @require_auth
    def route_auto_scrcpy_record():
        """Start or stop headless screen recording.

        Body: {"action": "start"|"stop", "duration": <seconds>, "output": "<path>"}
        Start: launches scrcpy --no-window --record=<output> in the background.
        Stop: kills the running scrcpy recording process.
        """
        body = _json_body()
        if body is None:
            return jsonify({"error": "JSON body required"}), 400

        action = body.get("action", "")
        if action not in ("start", "stop"):
            return jsonify({"error": "action must be 'start' or 'stop'"}), 400

        scrcpy = _find_scrcpy()
        if not scrcpy:
            return jsonify({"error": "scrcpy not installed"}), 500

        # Check for connected device
        adb = _find_adb()
        if adb:
            try:
                r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
                device_lines = [l for l in r.stdout.strip().split("\n")[1:] if l.strip() and "\tdevice" in l]
                if not device_lines:
                    return jsonify({"error": "No device connected — connect via USB and enable USB debugging"}), 400
            except Exception:
                pass

        if action == "start":
            raw_duration = body.get("duration", 30)
            try:
                duration = int(raw_duration)
            except (TypeError, ValueError):
                return jsonify({"error": "duration must be an integer number of seconds"}), 400
            # Clamp to a bounded range: --time-limit=0 disables auto-stop, and
            # huge values can pin the recorder indefinitely.
            duration = max(1, min(duration, 3600))

            # Sandbox the output to the temp dir (basename only) so a caller
            # can't direct scrcpy to overwrite arbitrary files via `output`.
            raw_output = body.get("output")
            output_name = os.path.basename(str(raw_output)) if raw_output else "scrcpy_record.mp4"
            if output_name in ("", ".", ".."):
                output_name = "scrcpy_record.mp4"
            output_path = os.path.join(tempfile.gettempdir(), output_name)

            try:
                # Build command
                cmd = [
                    scrcpy,
                    "--no-window",
                    "--no-playback",
                    f"--record={output_path}",
                    f"--time-limit={duration}",
                ]
                # Launch in background via CREATE_NEW_PROCESS_GROUP
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                _log("scrcpy_record", f"Started recording to {output_path} for {duration}s (PID {proc.pid})")
                return jsonify({
                    "status": "recording",
                    "pid": proc.pid,
                    "output": output_path,
                    "duration": duration,
                    "note": f"Recording will auto-stop after {duration}s. Kill PID {proc.pid} to stop early.",
                })
            except Exception as e:
                _log("scrcpy_record", f"Failed to start: {e}")
                return jsonify({"error": f"Failed to start recording: {e}"}), 500

        elif action == "stop":
            # Kill scrcpy processes
            try:
                if os.name == "nt":
                    r = subprocess.run(
                        ["taskkill", "/f", "/im", "scrcpy.exe"],
                        capture_output=True, text=True, timeout=10
                    )
                else:
                    r = subprocess.run(
                        ["pkill", "-f", "scrcpy"],
                        capture_output=True, text=True, timeout=10
                    )
                _log("scrcpy_record", f"Stopped recording: {r.stdout.strip()}")
                return jsonify({
                    "status": "stopped",
                    "detail": r.stdout.strip() or "scrcpy processes terminated",
                })
            except Exception as e:
                _log("scrcpy_record", f"Failed to stop: {e}")
                return jsonify({"error": f"Failed to stop: {e}"}), 500
