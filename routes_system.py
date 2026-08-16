"""System control routes: volume, brightness, mute, monitor, media playback,
   Wi-Fi, Bluetooth, night light, audio output, DND, camera, microphone,
   proxy, VPN, dark mode, power mode, keyboard backlight, battery info."""
import os
import re
import subprocess
import ctypes
import time
import json as _json
from flask import jsonify
from datetime import datetime
from shared import _json_body, _log, _missing_field, COAGENT_DIR

# ── PowerShell helper ─────────────────────────────────────────
def _ps(script, timeout=10):
    """Run a PowerShell command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found (not on Windows?)", -1

def _coerce_int(val, default=50, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError, OverflowError):
        return default

# ── Audio helpers ─────────────────────────────────────────────
_VOLUME_MIN = 0
_VOLUME_MAX = 100

def _ps_get_volume():
    """Get current master volume level (0-100) and mute state."""
    # Use waveOutGetVolume (the legacy wave mapper, which maps to the default
    # output device) rather than Sapi.SpSharedRecognizer — the latter controls
    # the speech recognizer's *microphone* input, not the system output volume.
    script = r"""
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public class AudioVol {
    [DllImport("winmm.dll")] public static extern int waveOutGetVolume(System.IntPtr h, out uint v);
    public static int GetLevel() {
        uint v; waveOutGetVolume(System.IntPtr.Zero, out v);
        uint left = v & 0xFFFF;
        uint right = (v >> 16) & 0xFFFF;
        return (int)System.Math.Round(((left + right) / 2.0) / 65535.0 * 100);
    }
}
'@
Write-Output ([AudioVol]::GetLevel())
"""
    out, _, rc = _ps(script)
    if rc == 0 and out.strip():
        try:
            return _coerce_int(out.strip(), 50, 0, 100), False
        except (TypeError, ValueError):
            pass
    return 50, False

def _ps_set_volume(level):
    """Set master volume to 0-100."""
    level = _coerce_int(level, 50, 0, 100)
    # Use nircmd if available, else waveOutSetVolume (legacy master volume)
    if _has_nircmd():
        _ps(f"nircmd setsysvolume {round(level * 655.35)}", timeout=5)
    else:
        script = r"""
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public class AudioVol {
    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(System.IntPtr h, uint v);
    public static void SetLevel(int pct) {
        uint lvl = (uint)(System.Math.Max(0, System.Math.Min(100, pct)) * 655.35);
        waveOutSetVolume(System.IntPtr.Zero, (lvl << 16) | lvl);
    }
}
'@
[AudioVol]::SetLevel(%d)
""" % level
        _ps(script, timeout=5)
    _log(f"Volume set to {level}%")
    return level

def _has_nircmd():
    """Check if nircmd.exe is in PATH."""
    return any(
        os.path.isfile(os.path.join(p, "nircmd.exe"))
        for p in os.environ.get("PATH", "").split(os.pathsep)
    ) or os.path.isfile(os.path.expandvars(r"%USERPROFILE%\nircmd\nircmd.exe"))

def _has_monitor_info():
    """Check if monitor brightness control is available."""
    script = """
Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction SilentlyContinue |
Select-Object -ExpandProperty CurrentBrightness -ErrorAction SilentlyContinue
"""
    out, _, rc = _ps(script)
    return rc == 0 and out.strip() != ""

# ── Brightness helpers ────────────────────────────────────────
def _ps_get_brightness():
    """Get current display brightness (0-100)."""
    script = """
try {
    $mon = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction Stop
    Write-Output $mon.CurrentBrightness
} catch {
    # Fallback: software brightness approximation
    Write-Output "-1"
}
"""
    out, _, rc = _ps(script)
    try:
        v = int(out.strip())
        return v if 0 <= v <= 100 else None
    except (ValueError, AttributeError):
        return None

def _ps_set_brightness(level):
    """Set display brightness percentage (0-100)."""
    level = _coerce_int(level, 50, 0, 100)
    if _has_nircmd():
        _ps(f"nircmd setbrightness {level}", timeout=5)
    else:
        _ps(f"""
$monitors = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue
foreach ($m in $monitors) {{
    $m.WmiSetBrightness(1, {level}) | Out-Null
}}
Write-Output "done"
""", timeout=10)
    _log(f"Brightness set to {level}%")
    return level


def register_routes(app, state, require_auth):

    # ── Volume ────────────────────────────────────────────────
    @app.route("/system/volume", methods=["POST"])
    @require_auth
    def route_system_volume():
        """Get or set master volume.
        GET-like (no body): returns current volume.
        POST body: {"level": 0-100} or {"delta": +10/-10}.
        """
        d = _json_body()
        if not d or not any(k in d for k in ("level", "delta")):
            # Report current
            vol, muted = _ps_get_volume()
            return jsonify({
                "volume": vol,
                "muted": muted,
                "min": _VOLUME_MIN,
                "max": _VOLUME_MAX,
            })

        if "delta" in d:
            current, _ = _ps_get_volume()
            delta = _coerce_int(d["delta"], 0, -100, 100)
            level = _coerce_int(current + delta, 50, 0, 100)
        else:
            level = _coerce_int(d.get("level", 50), 50, 0, 100)

        _ps_set_volume(level)
        return jsonify({"status": "ok", "volume": level})

    @app.route("/system/volume/up", methods=["POST"])
    @require_auth
    def route_system_volume_up():
        d = _json_body() or {}
        delta = _coerce_int(d.get("delta", 10), 10, 1, 100)
        current, _ = _ps_get_volume()
        level = _coerce_int(current + delta, 50, 0, 100)
        _ps_set_volume(level)
        return jsonify({"status": "ok", "volume": level, "delta": delta})

    @app.route("/system/volume/down", methods=["POST"])
    @require_auth
    def route_system_volume_down():
        d = _json_body() or {}
        delta = _coerce_int(d.get("delta", 10), 10, 1, 100)
        current, _ = _ps_get_volume()
        level = _coerce_int(current - delta, 50, 0, 100)
        _ps_set_volume(level)
        return jsonify({"status": "ok", "volume": level, "delta": delta})

    # ── Mute ──────────────────────────────────────────────────
    @app.route("/system/mute", methods=["POST"])
    @require_auth
    def route_system_mute():
        d = _json_body() or {}
        target = d.get("mute")  # True=on, False=off, None=toggle
        _, muted = _ps_get_volume()

        if target is None:
            # Toggle
            new_mute = not muted
        elif isinstance(target, bool):
            new_mute = target
        else:
            new_mute = not muted  # treat anything else as toggle

        if new_mute:
            _ps("nircmd mutesysvolume 1" if _has_nircmd()
                else "$obj = (New-Object -ComObject Sapi.SpSharedRecognizer).AudioObject; $obj.Mute = $true", timeout=5)
        else:
            _ps("nircmd mutesysvolume 0" if _has_nircmd()
                else "$obj = (New-Object -ComObject Sapi.SpSharedRecognizer).AudioObject; $obj.Mute = $false", timeout=5)

        _log(f"Mute set to {new_mute}")
        return jsonify({"status": "ok", "muted": new_mute})

    # ── Brightness ────────────────────────────────────────────
    @app.route("/system/brightness", methods=["POST"])
    @require_auth
    def route_system_brightness():
        d = _json_body()
        if not d or not any(k in d for k in ("level", "delta")):
            current = _ps_get_brightness()
            return jsonify({
                "brightness": current,
                "supported": current is not None,
            })

        if "delta" in d:
            current = _ps_get_brightness() or 50
            delta = _coerce_int(d["delta"], 0, -100, 100)
            level = _coerce_int(current + delta, 50, 0, 100)
        else:
            level = _coerce_int(d.get("level", 50), 50, 0, 100)

        _ps_set_brightness(level)
        return jsonify({"status": "ok", "brightness": level})

    @app.route("/system/brightness/up", methods=["POST"])
    @require_auth
    def route_system_brightness_up():
        delta = _coerce_int(_json_body().get("delta", 10) if _json_body() else 10, 10, 1, 100)
        current = _ps_get_brightness() or 50
        level = _coerce_int(current + delta, 50, 0, 100)
        _ps_set_brightness(level)
        return jsonify({"status": "ok", "brightness": level, "delta": delta})

    @app.route("/system/brightness/down", methods=["POST"])
    @require_auth
    def route_system_brightness_down():
        delta = _coerce_int(_json_body().get("delta", 10) if _json_body() else 10, 10, 1, 100)
        current = _ps_get_brightness() or 50
        level = _coerce_int(current - delta, 50, 0, 100)
        _ps_set_brightness(level)
        return jsonify({"status": "ok", "brightness": level, "delta": delta})

    # ── Monitor ──────────────────────────────────────────────
    @app.route("/system/monitor/off", methods=["POST"])
    @require_auth
    def route_system_monitor_off():
        """Turn off all monitors (immediately)."""
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        _log("Monitors turned off")
        return jsonify({"status": "ok", "monitors": "off"})

    @app.route("/system/monitor/on", methods=["POST"])
    @require_auth
    def route_system_monitor_on():
        """Wake all monitors."""
        # Simulate a small mouse move to wake the display
        import pyautogui as pg
        x, y = pg.position()
        pg.moveTo(x + 1, y) if x < 3000 else pg.moveTo(x - 1, y)
        time.sleep(0.1)
        pg.moveTo(x, y)
        _log("Monitors woken")
        return jsonify({"status": "ok", "monitors": "on"})

    @app.route("/system/monitor/info", methods=["GET"])
    @require_auth
    def route_system_monitor_info():
        """List available monitors with info."""
        try:
            from routes_ocr import get_monitor_list
            monitors = get_monitor_list()
        except Exception:
            monitors = []
        brightness = _ps_get_brightness()
        return jsonify({
            "monitors": monitors,
            "brightness_supported": brightness is not None,
            "current_brightness": brightness,
        })

    # ── Wi-Fi ─────────────────────────────────────────────────
    @app.route("/system/wifi", methods=["POST"])
    @require_auth
    def route_system_wifi():
        d = _json_body()
        action = d.get("action", "status") if d else "status"
        if action == "status":
            out, _, _ = _ps("netsh wlan show interfaces | findstr /R \"SSID.*:$\" | findstr /V \"BSSID\"")
            out2, _, _ = _ps("netsh wlan show interfaces | findstr /C:\"State\"")
            connected = "connected" in out2.lower()
            ssid = out.split(":")[-1].strip() if ":" in out else None
            return jsonify({"status": "ok", "connected": connected, "ssid": ssid})
        elif action == "off":
            _ps("netsh wlan disconnect", timeout=5)
            _log("Wi-Fi disconnected")
            return jsonify({"status": "ok", "wifi": "disconnected"})
        elif action == "on":
            ssid = d.get("ssid", "")
            # Use subprocess directly (no PowerShell) to avoid injection
            subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"],
                           capture_output=True, timeout=10)
            _log(f"Wi-Fi connecting to {ssid or 'last network'}")
            return jsonify({"status": "ok", "wifi": "connecting", "ssid": d.get("ssid")})
        elif action == "list":
            out, _, _ = _ps("netsh wlan show profiles | findstr /R \"^\\s*All User Profile\"")
            networks = [l.split(":")[-1].strip() for l in out.splitlines() if ":" in l]
            return jsonify({"status": "ok", "networks": networks})
        return jsonify({"error": "Unknown action"}), 400

    @app.route("/system/wifi/toggle", methods=["POST"])
    @require_auth
    def route_system_wifi_toggle():
        # Radio toggle via netsh
        cur, _, _ = _ps("netsh wlan show interfaces | findstr /C:\"State\"")
        state = cur.lower()
        if "connected" in state and "disconnected" not in state:
            _ps("netsh wlan disconnect", timeout=5)
            return jsonify({"status": "ok", "wifi": "disconnected"})
        _ps("netsh wlan connect", timeout=10)
        return jsonify({"status": "ok", "wifi": "connecting"})

    # ── Bluetooth ────────────────────────────────────────────
    @app.route("/system/bluetooth", methods=["POST"])
    @require_auth
    def route_system_bluetooth():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("Get-PnpDevice -Class Bluetooth | Select-Object Status,FriendlyName | ConvertTo-Json")
            try:
                devices = _json.loads(out) if out else []
                if isinstance(devices, dict):
                    devices = [devices]
            except Exception:
                devices = []
            return jsonify({"status": "ok", "devices": devices})
        elif action == "on":
            _ps("Enable-PnpDevice -InstanceId (Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -eq 'Error'}).InstanceId -Confirm:$false", timeout=10)
            return jsonify({"status": "ok", "bluetooth": "enabled"})
        elif action == "off":
            _ps("Disable-PnpDevice -InstanceId (Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -ne 'Error'}).InstanceId -Confirm:$false", timeout=10)
            return jsonify({"status": "ok", "bluetooth": "disabled"})
        return jsonify({"error": "Unknown action"}), 400

    # ── Night light (blue light filter) ──────────────────────
    @app.route("/system/nightlight", methods=["POST"])
    @require_auth
    def route_system_nightlight():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("(Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CloudStore\\Store\\Cache\\DefaultAccount\\$$windows.data.bluelightreduction.bluelightreductionstate\\Current' -Name 'Data' -ErrorAction SilentlyContinue).Data")
            on = "01" in out if out else False
            return jsonify({"status": "ok", "nightlight": on})
        elif action in ("on", "off"):
            _ps(f"""
$regPath = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CloudStore\\Store\\Cache\\DefaultAccount\\$$windows.data.bluelightreduction.bluelightreductionstate'
try {{
    $cur = Get-ItemProperty -Path \"$regPath\\Current\" -Name 'Data' -ErrorAction Stop
    $bytes = [byte[]]$cur.Data
    $bytes[8] = {'1' if action == 'on' else '0'}
    Set-ItemProperty -Path \"$regPath\\Current\" -Name 'Data' -Value $bytes -ErrorAction Stop
    Set-ItemProperty -Path \"$regPath\\Current\" -Name 'Data' -Value $bytes -ErrorAction Stop
    Start-Sleep -Milliseconds 500
    # Try toggle via action center
    [Windows.UI.ViewManagement.UISettings,Windows.UI.ViewManagement,ContentType=WindowsRuntime] | Out-Null
}} catch {{ }}
# Also try via settings shortcut
Start-Process ms-settings:nightlight -WindowStyle Hidden
Start-Sleep 1
[System.Windows.Forms.SendKeys]::SendWait('{{TAB}}')
Start-Sleep 0.3
[System.Windows.Forms.SendKeys]::SendWait(' ')
Start-Sleep 0.5
[System.Windows.Forms.SendKeys]::SendWait('%(F4)')
""", timeout=10)
            _log(f"Nightlight {'on' if action == 'on' else 'off'}")
            return jsonify({"status": "ok", "nightlight": action == "on"})
        return jsonify({"error": "Unknown action"}), 400

    # ── Audio output device ──────────────────────────────────
    @app.route("/system/audio/output", methods=["POST"])
    @require_auth
    def route_system_audio_output():
        d = _json_body() or {}
        action = d.get("action", "list")
        if action == "list":
            out, _, _ = _ps("Get-AudioDevice -Playback | Select-Object Index,Default,Type,Name | ConvertTo-Json 2>$null")
            try:
                devs = _json.loads(out) if out else []
                if isinstance(devs, dict):
                    devs = [devs]
            except Exception:
                devs = []
            return jsonify({"status": "ok", "devices": devs})
        elif action == "set":
            idx = d.get("index")
            if idx is None:
                return _missing_field("index")
            out, _, _ = _ps(f"Set-AudioDevice -Playback -Index {int(idx)} 2>&1 | Out-String", timeout=5)
            _log(f"Audio output set to index {idx}")
            return jsonify({"status": "ok", "index": idx})
        elif action == "switch":
            # Cycle to next audio device
            _ps("""
$devs = Get-AudioDevice -Playback
$current = $devs | Where-Object {$_.Default -eq $true}
if ($current) {
    $nextIdx = [Math]::Max(1, ($current.Index % $devs.Count) + 1)
    Set-AudioDevice -Playback -Index $nextIdx
    Write-Output $nextIdx
}
""", timeout=5)
            return jsonify({"status": "ok", "action": "switched"})
        return jsonify({"error": "Unknown action"}), 400

    # ── Do Not Disturb / Focus Assist ─────────────────────────
    @app.route("/system/dnd", methods=["POST"])
    @require_auth
    def route_system_dnd():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' -Name 'NUI_GUIDE_SETTING_DND_ENABLED' -ErrorAction SilentlyContinue).NUI_GUIDE_SETTING_DND_ENABLED")
            on = out.strip() == "1"
            return jsonify({"status": "ok", "dnd": on})
        elif action in ("on", "off"):
            _ps(f"New-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' -Name 'NUI_GUIDE_SETTING_DND_ENABLED' -Value {'1' if action == 'on' else '0'} -PropertyType DWord -Force", timeout=5)
            _log(f"DND {'on' if action == 'on' else 'off'}")
            return jsonify({"status": "ok", "dnd": action == "on"})
        return jsonify({"error": "Unknown action"}), 400

    # ── Camera ─────────────────────────────────────────────────
    @app.route("/system/camera", methods=["POST"])
    @require_auth
    def route_system_camera():
        d = _json_body() or {}
        action = d.get("action", "status")
        # Find camera devices
        cam_ps = "Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue | Where-Object {$_.FriendlyName -notmatch 'IR|Windows Hello'} | Select-Object InstanceId,FriendlyName,Status | ConvertTo-Json"
        if action == "status":
            out, _, _ = _ps(cam_ps)
            try:
                devs = _json.loads(out) if out else []
                if isinstance(devs, dict):
                    devs = [devs]
            except Exception:
                devs = []
            return jsonify({"status": "ok", "devices": devs})
        elif action == "off":
            ps_off = "$ids = Get-PnpDevice -Class Camera | Where-Object {$_.Status -ne 'Error'}; foreach ($d in $ids) { Disable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false }"
            _ps(ps_off, timeout=10)
            _log("Camera disabled")
            return jsonify({"status": "ok", "camera": "off"})
        elif action == "on":
            ps_on = "$ids = Get-PnpDevice -Class Camera | Where-Object {$_.Status -eq 'Error'}; foreach ($d in $ids) { Enable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false }"
            _ps(ps_on, timeout=10)
            _log("Camera enabled")
            return jsonify({"status": "ok", "camera": "on"})
        return jsonify({"error": "Unknown action"}), 400

    @app.route("/system/camera/snapshot", methods=["POST"])
    @require_auth
    def route_camera_snapshot():
        """Take a photo with the webcam and save it."""
        import subprocess
        import base64
        from pathlib import Path
        
        shots_dir = COAGENT_DIR / "camera_shots"
        shots_dir.mkdir(exist_ok=True)
        fname = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = shots_dir / fname
        
        # Use PowerShell MediaCapture via a minimal C#/PS script
        ps_script = '''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# Create a temporary Windows Forms form with a PictureBox
$form = New-Object System.Windows.Forms.Form
$form.WindowState = "Minimized"
$form.ShowInTaskbar = $false
$form.Opacity = 0

$picBox = New-Object System.Windows.Forms.PictureBox
$picBox.Dock = "Fill"
$form.Controls.Add($picBox)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
    $timer.Stop()
    $form.Close()
})

$capture = New-Object System.Windows.Forms.Timer
$capture.Interval = 100
$capture.Add_Tick({
    $capture.Stop()
    # Use native webcam capture via Windows.Media.Capture
})

$form.Add_Shown({
    $form.Activate()
    $timer.Start()
})

[System.Windows.Forms.Application]::Run($form)
'''
        # Simpler: use PowerShell's built-in camera access via Windows.Media.Capture
        # Fall back to a simple Windows.Media.Capture approach
        try:
            # Use ffmpeg if available (most reliable)
            ffmpeg_paths = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            ]
            ffmpeg = None
            for fp in ffmpeg_paths:
                if Path(fp).exists():
                    ffmpeg = fp
                    break
            if not ffmpeg:
                # Check PATH
                import shutil
                ffmpeg = shutil.which("ffmpeg")
            
            if ffmpeg:
                cmd = [ffmpeg, "-f", "dshow", "-i", "video=@device_cm_", 
                       "-frames:v", "1", "-q:v", "3", str(path), "-y"]
                # Try common camera names
                import subprocess
                for cam_name in ["USB Camera", "HD Camera", "Integrated Camera", "USB2.0 Camera"]:
                    cmd[4] = f"video={cam_name}"
                    r = subprocess.run(cmd, capture_output=True, timeout=10)
                    if path.exists() and path.stat().st_size > 1000:
                        break
                else:
                    # Try enumerating with ffmpeg -list_devices
                    enum = subprocess.run(
                        [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                        capture_output=True, text=True, timeout=10
                    )
                    _log(f"FFmpeg devices: {enum.stderr[:500]}")
                    return jsonify({"success": False, "error": "Could not find camera via ffmpeg"}), 500
            
            if path.exists() and path.stat().st_size > 1000:
                _log(f"Camera snapshot saved: {fname} ({path.stat().st_size} bytes)")
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                return jsonify({
                    "success": True,
                    "path": str(path),
                    "filename": fname,
                    "size_bytes": path.stat().st_size,
                    "image": b64,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                return jsonify({"success": False, "error": "FFmpeg not available or capture failed"}), 500
        except Exception as e:
            _log(f"Camera snapshot error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Microphone privacy ─────────────────────────────────────
    @app.route("/system/microphone", methods=["POST"])
    @require_auth
    def route_system_microphone():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone' -Name 'Value' -ErrorAction SilentlyContinue).Value")
            return jsonify({"status": "ok", "mic_access": out.strip() if out else "Allow"})
        elif action in ("deny", "allow"):
            _ps(f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone' -Name 'Value' -Value '{(action == 'allow') * 'Allow' or 'Deny'}' -Force", timeout=5)
            _log(f"Microphone access: {action}")
            return jsonify({"status": "ok", "mic_access": action.title()})
        return jsonify({"error": "Unknown action"}), 400

    # ── Proxy ──────────────────────────────────────────────────
    @app.route("/system/proxy", methods=["POST"])
    @require_auth
    def route_system_proxy():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -Name 'ProxyEnable' -ErrorAction SilentlyContinue).ProxyEnable")
            server, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -Name 'ProxyServer' -ErrorAction SilentlyContinue).ProxyServer")
            enabled = out.strip() == "1"
            return jsonify({"status": "ok", "proxy_enabled": enabled, "proxy_server": server if enabled else None})
        elif action == "on":
            server = d.get("server", "127.0.0.1:8080")
            server = str(server).strip().strip("'\"")
            if not re.fullmatch(r"[A-Za-z0-9.:\-_ ]{1,256}", server):
                return jsonify({"error": "invalid proxy server address"}), 400
            _ps(f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -Name 'ProxyEnable' -Value 1; Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -Name 'ProxyServer' -Value '{server}'", timeout=5)
            _log(f"Proxy enabled: {server}")
            return jsonify({"status": "ok", "proxy": "on", "server": server})
        elif action == "off":
            _ps("Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -Name 'ProxyEnable' -Value 0", timeout=5)
            _log("Proxy disabled")
            return jsonify({"status": "ok", "proxy": "off"})
        return jsonify({"error": "Unknown action"}), 400

    # ── VPN ────────────────────────────────────────────────────
    @app.route("/system/vpn", methods=["POST"])
    @require_auth
    def route_system_vpn():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("Get-VpnConnection | Select-Object Name,ServerAddress,ConnectionStatus | ConvertTo-Json")
            try:
                conns = _json.loads(out) if out else []
                if isinstance(conns, dict):
                    conns = [conns]
            except Exception:
                conns = []
            return jsonify({"status": "ok", "connections": conns})
        elif action == "connect":
            name = d.get("name", "")
            name = str(name).strip().strip("'\"")
            if not name or not re.fullmatch(r"[A-Za-z0-9 .\-_]{1,128}", name):
                return jsonify({"error": "invalid VPN connection name"}), 400
            _ps(f"rasdial \"{name}\"", timeout=30)
            _log(f"VPN connecting: {name}")
            return jsonify({"status": "ok", "vpn": "connecting", "name": name})
        elif action == "disconnect":
            name = d.get("name", "")
            name = str(name).strip().strip("'\"")
            if name:
                if not re.fullmatch(r"[A-Za-z0-9 .\-_]{1,128}", name):
                    return jsonify({"error": "invalid VPN connection name"}), 400
                _ps(f"rasdial \"{name}\" /d", timeout=15)
            else:
                _ps("rasdial /d", timeout=15)
            _log(f"VPN disconnect: {name or 'all'}")
            return jsonify({"status": "ok", "vpn": "disconnected"})
        return jsonify({"error": "Unknown action"}), 400

    # ── Dark mode ──────────────────────────────────────────────
    @app.route("/system/theme", methods=["POST"])
    @require_auth
    def route_system_theme():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            apps, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -ErrorAction SilentlyContinue).AppsUseLightTheme")
            sys, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'SystemUsesLightTheme' -ErrorAction SilentlyContinue).SystemUsesLightTheme")
            return jsonify({"status": "ok", "dark_mode_apps": apps.strip() == "0", "dark_mode_system": sys.strip() == "0"})
        elif action in ("dark", "light"):
            val = "0" if action == "dark" else "1"
            _ps(f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -Value {val}; Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'SystemUsesLightTheme' -Value {val}", timeout=5)
            _log(f"Theme: {action}")
            return jsonify({"status": "ok", "theme": action})
        return jsonify({"error": "Unknown action"}), 400

    # ── Power mode / plan ──────────────────────────────────────
    @app.route("/system/power/mode", methods=["POST"])
    @require_auth
    def route_system_power_mode():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("powercfg /getactivescheme")
            # parse GUID
            import re as _re
            m = _re.search(r'\{([^}]+)\}', out)
            guid = m.group(1) if m else None
            name = out.strip()
            # Determine mode from GUID
            mode_map = {
                "381b4222-f694-41f0-9685-ff5bb260df2f": "balanced",
                "a1841308-3541-4fab-bc81-f71556f20b4a": "power_saver",
                "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "high_performance",
                "e9a42b02-d5df-448d-aa00-03f14749eb61": "ultimate_performance",
            }
            mode = mode_map.get(guid, "unknown")
            return jsonify({"status": "ok", "mode": mode, "guid": guid, "name": name})
        elif action == "set":
            mode_map = {
                "balanced": "381b4222-f694-41f0-9685-ff5bb260df2f",
                "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
                "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
                "ultimate_performance": "e9a42b02-d5df-448d-aa00-03f14749eb61",
            }
            mode = d.get("mode", "balanced")
            guid = mode_map.get(mode)
            if not guid:
                return jsonify({"error": f"Unknown mode: {mode}. Use: balanced, power_saver, high_performance, ultimate_performance"}), 400
            _ps(f"powercfg /setactive {guid}", timeout=5)
            _log(f"Power mode: {mode}")
            return jsonify({"status": "ok", "mode": mode})
        return jsonify({"error": "Unknown action"}), 400

    # ── Battery info ───────────────────────────────────────────
    @app.route("/system/battery", methods=["GET"])
    @require_auth
    def route_system_battery():
        out, _, _ = _ps("(Get-WmiObject -Class BatteryStatus -Namespace root\\WMI -ErrorAction SilentlyContinue) | Select-Object PowerOnline,RemainingCapacity,MaxCapacity,ChargeRate | ConvertTo-Json")
        try:
            batt = _json.loads(out) if out else {}
            if isinstance(batt, list) and batt:
                batt = batt[0]
        except Exception:
            batt = {}
        # Fallback to system info
        if not batt:
            out2, _, _ = _ps("(Get-WmiObject Win32_Battery -ErrorAction SilentlyContinue) | Select-Object EstimatedChargeRemaining,BatteryStatus,EstimatedRunTime | ConvertTo-Json")
            try:
                batt = _json.loads(out2) if out2 else {}
                if isinstance(batt, list) and batt:
                    batt = batt[0]
            except Exception:
                batt = {}
        return jsonify({"status": "ok", "battery": batt if batt else {"error": "No battery found"}})

    # ── Keyboard backlight (OEM/laptop specific) ──────────────
    @app.route("/system/keyboard/backlight", methods=["POST"])
    @require_auth
    def route_system_keyboard_backlight():
        d = _json_body() or {}
        action = d.get("action", "status")
        if action == "status":
            out, _, _ = _ps("Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction SilentlyContinue | Select-Object *")
            has_kb = out.strip() != ""
            # Try OEM-specific
            out2, _, _ = _ps("(Get-WmiObject -Namespace root/WMI -Class MBI10_Device -ErrorAction SilentlyContinue) | Select-Object *")
            return jsonify({"status": "ok", "supported": bool(has_kb or out2.strip()), "keyboard_brightness": None})
        elif action in ("on", "off"):
            # `nircmd setbrightness` controls the *display* backlight, not the
            # keyboard. Keyboard backlight is OEM-specific with no universal CLI,
            # so report unsupported instead of silently dimming the screen.
            return jsonify({
                "status": "ok",
                "supported": False,
                "keyboard_backlight": None,
                "error": "Keyboard backlight control not available (OEM-specific)",
            }), 501
        return jsonify({"error": "Unknown action"}), 400

    # ── Media keys ───────────────────────────────────────────
    @app.route("/system/media/playpause", methods=["POST"])
    @require_auth
    def route_system_media_playpause():
        _send_media_key(0xB3)
        return jsonify({"status": "ok", "key": "playpause"})

    @app.route("/system/media/next", methods=["POST"])
    @require_auth
    def route_system_media_next():
        _send_media_key(0xB0)
        return jsonify({"status": "ok", "key": "next"})

    @app.route("/system/media/prev", methods=["POST"])
    @require_auth
    def route_system_media_prev():
        _send_media_key(0xB1)
        return jsonify({"status": "ok", "key": "prev"})

    @app.route("/system/media/stop", methods=["POST"])
    @require_auth
    def route_system_media_stop():
        _send_media_key(0xB2)
        return jsonify({"status": "ok", "key": "stop"})

    # ── System info ──────────────────────────────────────────
    @app.route("/system/info", methods=["GET"])
    @require_auth
    def route_system_info():
        bright = _ps_get_brightness()
        vol, muted = _ps_get_volume()
        # Grab a few more statuses
        wifi_out, _, _ = _ps("netsh wlan show interfaces | findstr /C:\"State\"")
        wifi_connected = "connected" in wifi_out.lower()
        dnd_out, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' -Name 'NUI_GUIDE_SETTING_DND_ENABLED' -ErrorAction SilentlyContinue).NUI_GUIDE_SETTING_DND_ENABLED")
        theme_apps, _, _ = _ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -ErrorAction SilentlyContinue).AppsUseLightTheme")
        return jsonify({
            "volume": vol,
            "muted": muted,
            "brightness": bright,
            "brightness_supported": bright is not None,
            "nircmd_available": _has_nircmd(),
            "monitor_brightness_available": _has_monitor_info(),
            "wifi_connected": wifi_connected,
            "dnd_enabled": dnd_out.strip() == "1",
            "dark_mode": theme_apps.strip() == "0" if theme_apps else None,
        })

    @app.route("/system/sync-github", methods=["GET"])
    @require_auth
    def route_sync_github():
        """Download latest hermes_coagent.py + routes_*.py from GitHub, then restart."""
        import platform as _platform
        if _platform.system() != "Windows":
            return jsonify({"ok": False, "error": "Windows only"})

        import sys
        import urllib.request
        import glob as _glob

        base_url = "https://raw.githubusercontent.com/Predator04/Hermes-Coagent/main/"
        coagent_path = str(COAGENT_DIR)

        # Use gh CLI token for private repo access
        gh_token = None
        try:
            r = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                gh_token = r.stdout.strip()
        except Exception:
            pass

        auth_headers = {"User-Agent": "CoAgent"}
        if gh_token:
            auth_headers["Authorization"] = f"token {gh_token}"

        # Fetch file list from GitHub repo
        repo_api = "https://api.github.com/repos/Predator04/Hermes-CoAgent/git/trees/main?recursive=1"
        repo_files = set()
        try:
            req = urllib.request.Request(repo_api, headers=auth_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
                for item in data.get("tree", []):
                    repo_files.add(item["path"])
        except Exception:
            repo_files = {
                "hermes_coagent.py", "shared.py", "VERSION",
                "requirements.txt",
            }

        # Build target list from files that exist on GitHub
        targets = []
        for fname in sorted(repo_files):
            if fname.endswith(".py") and "/" not in fname:
                targets.append(os.path.join(coagent_path, fname))
        for must_have in ["hermes_coagent.py", "shared.py"]:
            mp = os.path.join(coagent_path, must_have)
            if mp not in targets:
                targets.insert(0, mp)

        updated, errors = [], []
        for local_path in targets:
            fname = os.path.basename(local_path)
            if fname not in repo_files or not fname.endswith(".py"):
                continue
            try:
                req = urllib.request.Request(base_url + fname, headers=auth_headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read()
                with open(local_path, "wb") as fh:
                    fh.write(content)
                updated.append(fname)
            except Exception as exc:
                errors.append({"file": fname, "error": str(exc)})

        # Schedule restart and return
        try:
            script = os.path.abspath(sys.modules["__main__"].__file__)
            arg_string = subprocess.list2cmdline([script] + sys.argv[1:])
            ps_cmd = (
                "Start-Sleep -Seconds 2; "
                f"Start-Process -FilePath '{sys.executable}' "
                f"-ArgumentList '{arg_string}' "
                "-WindowStyle Hidden"
            )
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            import threading, time as _time
            threading.Thread(target=lambda: (_time.sleep(1.5), os._exit(0)), daemon=True).start()
        except Exception as exc:
            return jsonify({"ok": True, "updated": updated, "errors": errors, "restart_error": str(exc)})

        return jsonify({"ok": True, "updated": updated, "errors": errors, "restarting": True})

    @app.route("/system/restart", methods=["POST"])
    @require_auth
    def route_system_restart():
        """Restart via elevated scheduled task (admin-safe, Session 1)."""
        import sys as _sys

        try:
            main_script = os.path.abspath(_sys.modules["__main__"].__file__)
        except Exception:
            main_script = str(COAGENT_DIR / "hermes_coagent.py")

        pid = os.getpid()
        py = _sys.executable
        cwd = str(COAGENT_DIR)
        argv_str = " ".join([main_script] + _sys.argv[1:])
        import getpass as _getpass
        username = os.environ.get("USERNAME") or _getpass.getuser()

        # Write Python restart script to temp (no spaces in path for scheduled task)
        script_path = os.path.join(os.environ.get("TEMP", cwd), "_coagent_restart.py")
        # Use forward slashes in Python source to avoid escape issues,
        # convert back to native separators at runtime in _restart.py
        fwd_py = py.replace("\\", "/")
        fwd_argv = argv_str.replace("\\", "/")
        fwd_cwd = cwd.replace("\\", "/")
        with open(script_path, "w") as f:
            f.write(f'''import subprocess, time, os
time.sleep(2)
subprocess.run(["taskkill","/f","/pid","{pid}"], capture_output=True)
time.sleep(1)
# Convert forward slashes back for Windows scheduled task
_py = "{fwd_py}".replace("/", "\\\\")
_argv = "{fwd_argv}".replace("/", "\\\\")
_cwd = "{fwd_cwd}".replace("/", "\\\\")
subprocess.run([
    "powershell","-NoProfile","-Command",
    "$a=New-ScheduledTaskAction -Execute '" + _py + "' -Argument '" + _argv + "' -WorkingDirectory '" + _cwd + "';"
    "$t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(2);"
    "$p=New-ScheduledTaskPrincipal -UserId '{username}' -LogonType Interactive -RunLevel Highest;"
    "Register-ScheduledTask -TaskName CoAgentLaunch -Action $a -Trigger $t -Principal $p -Force|Out-Null;"
    "Start-ScheduledTask -TaskName CoAgentLaunch"
], capture_output=True, timeout=15)
''')

        # Create CoAgentReboot task (runs _restart.py directly, no cmd wrapper needed)
        ps = [
            "powershell", "-NoProfile", "-Command",
            f"$a=New-ScheduledTaskAction -Execute '{py}' -Argument '{script_path}' -WorkingDirectory '{cwd}';"
            '$t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(2);'
            f'$p=New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest;'
            "Register-ScheduledTask -TaskName CoAgentReboot -Action $a -Trigger $t -Principal $p -Force|Out-Null;"
            "Start-ScheduledTask -TaskName CoAgentReboot"
        ]

        try:
            subprocess.run(ps, timeout=8, capture_output=True)
        except Exception as e:
            _log(f"[RESTART] Failed: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

        _log("[RESTART] Scheduled task created; process will terminate in ~4s")
        return jsonify({"ok": True, "restarting": True})


def _send_media_key(vk_code):
    """Send a virtual key code via keyboard driver."""
    # Define the full Win32 INPUT union so sizeof(INPUT) is correct on x64.
    # SendInput requires cbSize == sizeof(INPUT) == 40 bytes on x64; a struct
    # with only KEYBDINPUT is 32 bytes and silently fails (returns 0).
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_ulong),
            ("u", _INPUTUNION),
        ]

    def _send(vk, flags=0):
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    _send(vk_code)
    time.sleep(0.05)
    _send(vk_code, 2)  # KEYEVENTF_KEYUP
