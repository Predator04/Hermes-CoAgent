"""UAC (User Account Control) automation endpoints.

Endpoints:
  POST /system/uac/status                 — read current UAC registry settings
  POST /system/uac/disable-secure-desktop — PromptOnSecureDesktop=0 (UAC on regular desktop)
  POST /system/uac/enable-secure-desktop  — PromptOnSecureDesktop=1 (restore secure desktop)
  POST /system/uac/click                  — vision+Win32 click Yes/No on UAC dialog
  POST /system/elevated-exec              — launch command via scheduled task (bypasses UAC prompt)
  GET  /system/uac/uiaccess-info          — info on UIAccess helper (Option C, experimental)

Strategy A (registry toggle) lets CoAgent's screen capture and mouse reach the UAC dialog.
Strategy D (elevated-exec via scheduled task) avoids the UAC prompt entirely by using
Task Scheduler's RunLevel=HighestAvailable, which executes without a consent prompt when
the current user is already an administrator.
"""

import os
import shutil
import subprocess
import tempfile
import time
import uuid

from flask import jsonify

from shared import _json_body, _log, _missing_field, _interactive_task_xml, COAGENT_DIR

_UAC_REG_KEY = r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"

# UIAccess helper binary path (Option C — must be built and installed separately)
_UIACCESS_HELPER = os.path.join(str(COAGENT_DIR), "uiaccess_helper.exe")


# ---------------------------------------------------------------------------
# PowerShell / registry helpers
# ---------------------------------------------------------------------------

def _ps(script, timeout=10):
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found", -1


def _reg_read_dword(value_name):
    out, _err, rc = _ps(
        f"(Get-ItemProperty -Path '{_UAC_REG_KEY}'"
        f" -Name '{value_name}' -ErrorAction SilentlyContinue).'{value_name}'"
    )
    if rc == 0 and out:
        try:
            return int(out.strip())
        except ValueError:
            pass
    return None


def _reg_set_dword(value_name, value):
    _out, err, rc = _ps(
        f"Set-ItemProperty -Path '{_UAC_REG_KEY}'"
        f" -Name '{value_name}' -Value {int(value)} -Type DWord"
    )
    return rc == 0, err


# ---------------------------------------------------------------------------
# Elevated-exec via scheduled task
# ---------------------------------------------------------------------------

def _find_schtasks():
    exe = shutil.which("schtasks") or shutil.which("schtasks.exe")
    if exe:
        return exe
    for p in [r"C:\Windows\system32\schtasks.exe", r"C:\Windows\SysWOW64\schtasks.exe"]:
        if os.path.isfile(p):
            return p
    return None


def _run_elevated_via_task(command, arguments="", working_dir=None):
    """Create an elevated scheduled task via PowerShell and run it.

    Uses Register-ScheduledTask with RunLevel=Highest, which bypasses the UAC
    consent prompt when the current user has admin rights.
    Returns a dict; 'error' key present on failure.
    """
    task_name = f"CoAgent_Elevate_{uuid.uuid4().hex[:12]}"

    def _psq(s):
        return "'" + str(s).replace("'", "''") + "'"

    action_part = f"$action=New-ScheduledTaskAction -Execute {_psq(command)}"
    if arguments:
        action_part += f" -Argument {_psq(arguments)}"
    if working_dir:
        action_part += f" -WorkingDirectory {_psq(working_dir)}"

    ps_cmd = (
        f"{action_part}; "
        f"Register-ScheduledTask -TaskName {_psq(task_name)} -Action $action "
        f"-Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(1)) "
        f"-Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest) "
        f"-Settings (New-ScheduledTaskSettingsSet -DeleteExpiredTaskAfter (New-TimeSpan -Seconds 60) -ExecutionTimeLimit (New-TimeSpan -Minutes 10)) "
        f"-Force | Out-Null; "
        f"Start-ScheduledTask -TaskName {_psq(task_name)}"
    )

    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return {
                "error": "Failed to create/start elevated task",
                "detail": (r.stderr or r.stdout).strip(),
                "task_name": task_name,
                "hint": "CoAgent may need to run as administrator",
            }
        return {
            "task_name": task_name,
            "created": True,
            "started": True,
            "command": command,
            "arguments": arguments,
            "detail": r.stdout.strip(),
        }
    except Exception as exc:
        _log(f"[uac] elevated-exec error: {exc}")
        return {"error": str(exc), "task_name": task_name}


# ---------------------------------------------------------------------------
# UAC dialog click helpers
# ---------------------------------------------------------------------------

_YES_LABELS = ["Yes", "Allow", "是", "はい", "Ja", "Oui", "Sí", "Si", "Да"]
_NO_LABELS  = ["No", "Cancel", "否", "いいえ", "Nein", "Non", "Отмена"]

# Window titles that identify a UAC consent dialog
_UAC_TITLES = ["User Account Control"]


def _click_point(x, y):
    """Click at absolute screen coordinates. Returns True on success."""
    try:
        import pyautogui
        pyautogui.click(x, y)
        return True
    except Exception:
        pass
    try:
        import win32api
        import win32con
        win32api.SetCursorPos((int(x), int(y)))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        return True
    except Exception as e:
        _log(f"[uac] click({x},{y}) failed: {e}")
        return False


def _try_click_win32(button_target):
    """Primary strategy: find UAC window via Win32 API and click the button."""
    try:
        import win32gui

        target_labels = _YES_LABELS if button_target == "yes" else _NO_LABELS
        found_hwnd = None

        def _enum_top(hwnd, _):
            nonlocal found_hwnd
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if any(t in title for t in _UAC_TITLES):
                found_hwnd = hwnd
            return True

        win32gui.EnumWindows(_enum_top, None)

        if not found_hwnd:
            return {"clicked": False, "reason": "UAC window not found via win32gui"}

        button_hwnd = None

        def _enum_children(child, _):
            nonlocal button_hwnd
            if button_hwnd:
                return True
            cls = win32gui.GetClassName(child)
            if cls in ("Button", "CCPushButton"):
                text = win32gui.GetWindowText(child)
                if any(lbl.lower() in text.lower() for lbl in target_labels):
                    button_hwnd = child
            return True

        win32gui.EnumChildWindows(found_hwnd, _enum_children, None)

        if not button_hwnd:
            return {
                "clicked": False,
                "reason": f"UAC window found (hwnd={found_hwnd}) but '{button_target}' button not found",
            }

        rect = win32gui.GetWindowRect(button_hwnd)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        ok = _click_point(cx, cy)
        return {
            "clicked": ok,
            "method": "win32_button",
            "button": button_target,
            "click_point": {"x": cx, "y": cy},
            "window_hwnd": found_hwnd,
        }
    except ImportError:
        return {"clicked": False, "reason": "win32gui not available (install pywin32)"}
    except Exception as exc:
        return {"clicked": False, "reason": f"win32 error: {exc}"}


def _try_click_ocr(button_target):
    """Fallback: capture screen, run OCR, click matching button text."""
    target_labels = _YES_LABELS if button_target == "yes" else _NO_LABELS
    target_lower = {lbl.lower() for lbl in target_labels}

    # Capture screen
    img = None
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception:
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                mon = sct.monitors[0]
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception:
            return {"clicked": False, "reason": "Screen capture failed (PIL/mss unavailable)"}

    if img is None:
        return {"clicked": False, "reason": "Screen capture returned None"}

    # Try Windows OCR via routes_ocr helper
    try:
        from routes_ocr import _windows_ocr as _win_ocr
        ocr_result = _win_ocr(img)
        if ocr_result and ocr_result.get("success"):
            for word_info in ocr_result.get("words", []):
                word_text = (word_info.get("text") or "").strip().lower()
                if word_text in target_lower:
                    # bbox is [x, y, w, h] list (or dict) from _windows_ocr
                    bbox = word_info.get("bbox") or []
                    if isinstance(bbox, list) and len(bbox) >= 4:
                        x = int(bbox[0] + bbox[2] / 2)
                        y = int(bbox[1] + bbox[3] / 2)
                    elif isinstance(bbox, dict):
                        x = int(bbox.get("x", 0) + bbox.get("w", 50) / 2)
                        y = int(bbox.get("y", 0) + bbox.get("h", 20) / 2)
                    else:
                        continue
                    ok = _click_point(x, y)
                    return {
                        "clicked": ok,
                        "method": "win_ocr_text",
                        "button": button_target,
                        "matched_text": word_info.get("text"),
                        "click_point": {"x": x, "y": y},
                    }
    except Exception:
        pass

    return {"clicked": False, "reason": "OCR did not find UAC button text on screen"}


def _try_click_uac_button(button_target):
    """Try all strategies to click a UAC button. Returns first success."""
    result = _try_click_win32(button_target)
    if result.get("clicked"):
        return result
    result2 = _try_click_ocr(button_target)
    if result2.get("clicked"):
        return result2
    # Merge reasons for diagnostics
    return {
        "clicked": False,
        "reason": "no strategy succeeded",
        "win32": result.get("reason"),
        "ocr": result2.get("reason"),
    }


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/system/uac/status", methods=["POST"])
    @require_auth
    def route_uac_status():
        """Return current UAC policy registry values.

        No body required.
        Returns {uac_enabled, secure_desktop_enabled, consent_prompt_behavior, raw, notes}.
        """
        enable_lua   = _reg_read_dword("EnableLUA")
        secure_desk  = _reg_read_dword("PromptOnSecureDesktop")
        consent_beh  = _reg_read_dword("ConsentPromptBehaviorAdmin")

        return jsonify({
            "status": "ok",
            "uac_enabled": (enable_lua != 0) if enable_lua is not None else None,
            "secure_desktop_enabled": (secure_desk != 0) if secure_desk is not None else None,
            "consent_prompt_behavior": consent_beh,
            "raw": {
                "EnableLUA": enable_lua,
                "PromptOnSecureDesktop": secure_desk,
                "ConsentPromptBehaviorAdmin": consent_beh,
            },
            "notes": {
                "EnableLUA": "1=UAC on (default), 0=UAC fully disabled",
                "PromptOnSecureDesktop": "1=secure desktop (default), 0=regular desktop",
                "ConsentPromptBehaviorAdmin": "0=no prompt, 2=consent, 5=consent (non-Windows binaries)",
            },
        })

    @app.route("/system/uac/disable-secure-desktop", methods=["POST"])
    @require_auth
    def route_uac_disable_secure_desktop():
        """Set PromptOnSecureDesktop=0 so UAC prompts appear on the regular desktop.

        After this call CoAgent can screen-capture and mouse-click the UAC dialog.
        Requires admin privileges. Pair with /system/uac/click or restore with
        /system/uac/enable-secure-desktop when done.

        No body required.
        """
        ok, err = _reg_set_dword("PromptOnSecureDesktop", 0)
        if not ok:
            return jsonify({
                "status": "error",
                "error": "Registry write failed — CoAgent must run as administrator",
                "detail": err,
                "hint": (
                    "Start CoAgent elevated, or use /system/elevated-exec to run "
                    "reg.exe add HKLM\\...\\System /v PromptOnSecureDesktop /t REG_DWORD /d 0 /f"
                ),
            }), 500

        new_val = _reg_read_dword("PromptOnSecureDesktop")
        return jsonify({
            "status": "ok",
            "secure_desktop_enabled": False,
            "PromptOnSecureDesktop": new_val,
            "note": "UAC prompts now appear on regular desktop. Use /system/uac/click to auto-click Yes.",
        })

    @app.route("/system/uac/enable-secure-desktop", methods=["POST"])
    @require_auth
    def route_uac_enable_secure_desktop():
        """Restore PromptOnSecureDesktop=1 (Windows default, most secure).

        No body required.
        """
        ok, err = _reg_set_dword("PromptOnSecureDesktop", 1)
        if not ok:
            return jsonify({
                "status": "error",
                "error": "Registry write failed — CoAgent must run as administrator",
                "detail": err,
            }), 500

        new_val = _reg_read_dword("PromptOnSecureDesktop")
        return jsonify({
            "status": "ok",
            "secure_desktop_enabled": True,
            "PromptOnSecureDesktop": new_val,
        })

    @app.route("/system/uac/click", methods=["POST"])
    @require_auth
    def route_uac_click():
        """Find and click the UAC Yes/No button on the current desktop.

        Only works when PromptOnSecureDesktop=0 (call /system/uac/disable-secure-desktop first).
        Strategy 1: Win32 window enumeration + button click (most reliable).
        Strategy 2: Screen OCR + coordinate click (fallback).

        Body (all optional):
          button  — "yes" (default) or "no"
          timeout — seconds to wait for dialog (default 5, max 30)
        Returns {clicked, method, button, click_point, ...}.
        """
        d = _json_body() or {}
        button_target = (d.get("button") or "yes").strip().lower()
        wait_sec = min(float(d.get("timeout", 5)), 30.0)

        if button_target not in ("yes", "no"):
            return jsonify({"error": "button must be 'yes' or 'no'"}), 400

        # Warn if secure desktop is still on
        secure_desk = _reg_read_dword("PromptOnSecureDesktop")
        if secure_desk != 0:
            return jsonify({
                "status": "warning",
                "clicked": False,
                "reason": "secure_desktop_still_enabled",
                "PromptOnSecureDesktop": secure_desk,
                "hint": "Call /system/uac/disable-secure-desktop first",
            }), 400

        deadline = time.time() + wait_sec
        last_result = {}
        while time.time() < deadline:
            last_result = _try_click_uac_button(button_target)
            if last_result.get("clicked"):
                return jsonify({"status": "ok", **last_result})
            time.sleep(0.4)

        return jsonify({
            "status": "not_found",
            "clicked": False,
            "hint": "Ensure a UAC dialog is visible and PromptOnSecureDesktop=0",
            **last_result,
        }), 404

    @app.route("/system/elevated-exec", methods=["POST"])
    @require_auth
    def route_elevated_exec():
        """Launch a command with highest privileges via Windows Task Scheduler.

        Creates a one-shot task with RunLevel=HighestAvailable, runs it, then
        deletes it. When the current user has admin rights this executes the
        target process elevated WITHOUT showing a UAC consent prompt.

        Body:
          command     — full path to executable (required), e.g. "C:\\setup.exe"
          arguments   — command-line arguments string (optional)
          working_dir — working directory (optional)

        Returns {status, task_name, created, started, command, arguments, detail}.
        Note: stdout/stderr are NOT captured (process runs detached). To capture
        output, redirect inside arguments: '/c myapp.exe > C:\\out.txt 2>&1'
        and use cmd.exe as the command.
        """
        d = _json_body() or {}
        command = (d.get("command") or "").strip()
        if not command:
            return _missing_field("command")

        arguments   = (d.get("arguments") or "").strip()
        working_dir = (d.get("working_dir") or "").strip() or None

        result = _run_elevated_via_task(command, arguments, working_dir)
        if "error" in result:
            return jsonify({"status": "error", **result}), 500
        return jsonify({"status": "ok", **result})

    @app.route("/system/uac/uiaccess-info", methods=["GET"])
    @require_auth
    def route_uac_uiaccess_info():
        """Return info about the UIAccess helper (Option C — experimental).

        UIAccess processes can interact with elevated/secure-desktop windows even
        when PromptOnSecureDesktop=1, but they require a signed executable placed
        in a trusted location (C:\\Program Files\\...).

        Returns helper availability status and build instructions.
        """
        helper_exists = os.path.isfile(_UIACCESS_HELPER)
        helper_dir = str(COAGENT_DIR)

        return jsonify({
            "status": "ok",
            "experimental": True,
            "helper_path": _UIACCESS_HELPER,
            "helper_exists": helper_exists,
            "description": (
                "A UIAccess process has uiAccess=true in its manifest and is placed "
                "in a trusted location (C:\\Program Files\\...). It can see and click "
                "windows on the secure desktop without disabling PromptOnSecureDesktop."
            ),
            "requirements": [
                "Executable must have uiAccess=\"true\" in its application manifest",
                "Executable must be placed in C:\\Program Files\\ or C:\\Windows\\",
                "Executable must be Authenticode-signed OR user must accept the trust prompt",
                "Helper source: scripts/uiaccess_helper.py in the CoAgent repo",
            ],
            "build_steps": [
                "1. pip install pyinstaller",
                "2. cd <coagent-repo>/scripts",
                "3. pyinstaller --onefile --manifest uiaccess_manifest.xml uiaccess_helper.py",
                f"4. Copy dist/uiaccess_helper.exe to {helper_dir}\\uiaccess_helper.exe",
                "5. Sign the exe with a trusted certificate (or accept the trust dialog once)",
            ],
            "alternative": "Use /system/uac/disable-secure-desktop + /system/uac/click (simpler, no signing needed)",
        })
