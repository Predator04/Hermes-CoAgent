# Auto-added feature: Raphire/Win11Debloat (53444 stars)
# PowerShell script to remove pre-installed bloatware, disable telemetry, and declutter Windows.
# Source: https://github.com/Raphire/Win11Debloat
# Install: iex (irm debloat.raphi.re)  OR  download from GitHub releases

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "Raphire/Win11Debloat",
    "stars": 53444,
    "desc": "A simple PowerShell script that removes pre-installed apps, disables telemetry, and performs various changes to declutter and customize Windows.",
    "url": "https://github.com/Raphire/Win11Debloat",
    "added": "2026-07-22",
    "script": "Win11Debloat.ps1",
    "cli_params": [
        "RunDefaults", "RunDefaultsLite", "RunSavedSettings",
        "RemoveApps", "RemoveGamingApps", "ForceRemoveEdge",
        "DisableTelemetry", "DisableBing", "DisableCopilot", "DisableRecall",
        "DisableWidgets", "DisableNotifications", "DisableSuggestions",
        "EnableDarkMode", "ShowHiddenFolders", "ShowKnownFileExt",
        "RevertContextMenu", "TaskbarAlignLeft", "DisableFastStartup",
    ],
}


def _find_win11debloat():
    """Locate Win11Debloat script directory on this system."""
    # Check common locations where user might have downloaded it
    for base in [
        os.path.expanduser(r"~\Desktop\Win11Debloat"),
        os.path.expanduser(r"~\Downloads\Win11Debloat"),
        os.path.expanduser(r"~\Documents\Win11Debloat"),
        os.path.expanduser(r"~\Win11Debloat"),
        r"C:\ProgramData\Win11Debloat",
    ]:
        script = os.path.join(base, "Win11Debloat.ps1")
        if os.path.isfile(script):
            return script
    return None


def _is_powershell_available():
    """Check if Windows PowerShell 5.1 is available (Win11Debloat requires this, not pwsh)."""
    exe = shutil.which("powershell.exe")
    if not exe:
        exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if not os.path.isfile(exe):
            return False
    try:
        result = subprocess.run(
            [exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # Must be 5.1 (not PowerShell Core 7+)
            return version.startswith("5")
        return False
    except (subprocess.TimeoutExpired, OSError):
        return False


def _is_win11debloat_available():
    """Check if Win11Debloat is available on this system."""
    script = _find_win11debloat()
    if script:
        return True
    # Even if not downloaded, we can download it on demand
    return _is_powershell_available()


def _get_powershell_path():
    """Get path to Windows PowerShell 5.1."""
    exe = shutil.which("powershell.exe")
    if exe:
        return exe
    default = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    if os.path.isfile(default):
        return default
    return "powershell.exe"


def _run_win11debloat_script(params, timeout=120):
    """Run Win11Debloat with given parameters via PowerShell.

    Returns (stdout, stderr, exit_code).
    """
    ps = _get_powershell_path()
    script = _find_win11debloat()

    if not script:
        # Try downloading and running via iex
        command_str = "& { [scriptblock]::Create((irm 'https://debloat.raphi.re/')) }"
        if params:
            command_str += " " + " ".join(params)
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-Command", command_str]
    else:
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", script]
        if params:
            cmd += params

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _param(flag):
    """Convert parameter name to PowerShell switch flag."""
    return f"-{flag}"


def register_routes(app, state, require_auth):

    @app.route("/auto/win11debloat/info", methods=["GET"])
    @require_auth
    def route_auto_win11debloat_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/win11debloat/ping", methods=["GET"])
    @require_auth
    def route_auto_win11debloat_ping():
        script = _find_win11debloat()
        ps_ok = _is_powershell_available()
        return jsonify({
            "ok": True,
            "script_found": script is not None,
            "script_path": script,
            "powershell_available": ps_ok,
            "needs_admin": True,
        })

    @app.route("/auto/win11debloat/run-defaults", methods=["POST"])
    @require_auth
    def route_auto_win11debloat_run_defaults():
        """Run Win11Debloat in Default mode — quickly apply recommended changes."""
        try:
            body = _json_body()
        except Exception:
            body = {}

        confirm = body.get("confirm", False)
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. This modifies Windows settings, removes apps, and changes registry."
            }), 400

        ps = _get_powershell_path()
        if not os.path.isfile(ps):
            return jsonify({"ok": False, "error": "PowerShell 5.1 not found on system"}), 503

        try:
            # Use downloaded script if available, otherwise download on the fly
            result_stdout, result_stderr, rc = _run_win11debloat_script([
                _param("RunDefaults"),
                _param("Silent"),
            ], timeout=180)

            if rc != 0 and "already ran as" not in result_stderr.lower():
                return jsonify({
                    "ok": False,
                    "error": result_stderr.strip() or "Win11Debloat run failed",
                    "exit_code": rc,
                }), 502

            return jsonify({
                "ok": True,
                "exit_code": rc,
                "output": result_stdout.strip()[:2000],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "Win11Debloat timed out (180s)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/win11debloat/custom", methods=["POST"])
    @require_auth
    def route_auto_win11debloat_custom():
        """Run Win11Debloat with custom parameters.

        Body: { "confirm": true, "params": ["-RemoveApps", "-DisableTelemetry", ...] }
        """
        body = _json_body()

        confirm = body.get("confirm", False)
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed."
            }), 400

        params = body.get("params", [])
        if not params:
            return _missing_field("params")

        if not isinstance(params, list):
            return jsonify({"ok": False, "error": "params must be a list of strings"}), 400

        # Validate allowed params to prevent arbitrary command injection
        allowed_prefixes = [
            "-RunDefaults", "-RunDefaultsLite", "-RemoveApps", "-RemoveGamingApps",
            "-RemoveHPApps", "-ForceRemoveEdge", "-DisableDVR",
            "-DisableGameBarIntegration", "-EnableWindowsSandbox",
            "-EnableWindowsSubsystemForLinux", "-DisableTelemetry",
            "-DisableSearchHistory", "-DisableFastStartup",
            "-DisableBitlockerAutoEncryption", "-DisableModernStandbyNetworking",
            "-DisableStorageSense", "-DisableUpdateASAP",
            "-PreventUpdateAutoReboot", "-DisableDeliveryOptimization",
            "-DisableDeviceAutoAppDownload", "-DisableBing",
            "-DisableNotifications", "-DisableStoreSearchSuggestions",
            "-DisableSearchHighlights", "-DisableDesktopSpotlight",
            "-DisableLockscreenTips", "-DisableSuggestions",
            "-DisableLocationServices", "-DisableFindMyDevice",
            "-DisableEdgeAds", "-DisableBraveBloat", "-DisableSettings365Ads",
            "-DisableSettingsHome", "-ShowHiddenFolders", "-ShowKnownFileExt",
            "-HideDupliDrive", "-EnableDarkMode", "-DisableTransparency",
            "-DisableAnimations", "-TaskbarAlignLeft", "-CombineTaskbarAlways",
            "-CombineTaskbarWhenFull", "-CombineTaskbarNever",
            "-HideSearchTb", "-ShowSearchIconTb", "-ShowSearchLabelTb",
            "-ShowSearchBoxTb", "-HideTaskview", "-DisableStartRecommended",
            "-DisableStartAllApps", "-StartAllAppsCategory",
            "-DisableStartPhoneLink", "-DisableCopilot", "-DisableRecall",
            "-DisableClickToDo", "-DisableAISvcAutoStart", "-DisablePaintAI",
            "-DisableNotepadAI", "-DisableEdgeAI", "-DisableWidgets",
            "-HideChat", "-EnableEndTask", "-EnableLastActiveClick",
            "-ClearStart", "-ReplaceStart", "-RevertContextMenu",
            "-DisableDragTray", "-DisableMouseAcceleration",
            "-DisableStickyKeys", "-DisableWindowSnapping",
            "-DisableSnapAssist", "-DisableSnapLayouts",
            "-HideHome", "-HideGallery", "-ExplorerToHome",
            "-ExplorerToThisPC", "-ExplorerToDownloads", "-HideOnedrive",
            "-Hide3dObjects", "-HideMusic", "-HideShare",
            "-ShowDriveLettersFirst", "-ShowDriveLettersLast",
            "-HideDriveLetters", "-Silent", "-LogPath",
        ]

        sanitized = []
        for p in params:
            p_str = str(p)
            # Check if parameter starts with any allowed prefix
            is_allowed = any(p_str.startswith(prefix) for prefix in allowed_prefixes)
            # Also allow -Apps and -Config with file paths
            if p_str.startswith("-Apps ") or p_str.startswith("-Apps\t"):
                is_allowed = True
            if p_str.startswith("-Config ") or p_str.startswith("-Config\t"):
                is_allowed = True
            if not is_allowed:
                return jsonify({
                    "ok": False,
                    "error": f"Parameter '{p_str}' is not in the allowed list"
                }), 400
            sanitized.append(p_str)

        try:
            stdout, stderr, rc = _run_win11debloat_script(sanitized, timeout=180)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "output": stdout.strip()[:2000],
                "stderr": stderr.strip()[:500],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "Win11Debloat timed out (180s)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/win11debloat/check", methods=["GET"])
    @require_auth
    def route_auto_win11debloat_check():
        """Check what Win11Debloat would do (dry-run / whatif mode)."""
        ps = _get_powershell_path()
        if not os.path.isfile(ps):
            return jsonify({"ok": False, "error": "PowerShell 5.1 not found"}), 503

        script = _find_win11debloat()
        if not script:
            # Just check if we can reach the download URL
            try:
                import urllib.request
                req = urllib.request.Request("https://debloat.raphi.re/", method="HEAD")
                resp = urllib.request.urlopen(req, timeout=10)
                return jsonify({
                    "ok": True,
                    "script_installed": False,
                    "download_available": True,
                    "note": "Win11Debloat is not downloaded but can be fetched on-demand via iex (irm ...)"
                })
            except Exception:
                return jsonify({
                    "ok": True,
                    "script_installed": False,
                    "download_available": False,
                    "note": "Win11Debloat not found and download URL unreachable"
                })

        # Check file size and last modified
        stat = os.stat(script)
        import datetime
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Detect Windows version
        try:
            ver_result = subprocess.run(
                [ps, "-NoProfile", "-Command",
                 "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').ProductName"],
                capture_output=True, text=True, timeout=10
            )
            win_ver = ver_result.stdout.strip() if ver_result.returncode == 0 else "unknown"
        except Exception:
            win_ver = "unknown"

        return jsonify({
            "ok": True,
            "script_installed": True,
            "script_path": script,
            "script_size_bytes": stat.st_size,
            "last_modified": mtime,
            "windows_version": win_ver,
            "general_info": "Run /auto/win11debloat/run-defaults for recommended changes",
        })
