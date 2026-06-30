"""System control routes: volume, brightness, mute, monitor, media playback."""
import os, subprocess, ctypes, re, time
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

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
    script = """
$obj = (New-Object -ComObject Sapi.SpSharedRecognizer).AudioObject
$vol = $obj.Volume
$mute = $obj.Mute
Write-Output "$vol|$mute"
"""
    out, _, rc = _ps(script)
    if rc == 0 and "|" in out:
        parts = out.split("|")
        try:
            return int(parts[0]), parts[1].strip().lower() == "true"
        except ValueError:
            pass
    # Fallback: AudioEndpointVolume via WinRT (works on Win10+)
    fallback = """
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public class AudioVol {
    [DllImport(\"winmm.dll\")] public static extern int waveOutGetVolume(IntPtr h, out uint v);
}
'@
uint v;
AudioVol.waveOutGetVolume(nint.Zero, out v);
uint left = v & 0xFFFF;
uint right = (v >> 16) & 0xFFFF;
double pct = ((left + right) / 2.0) / 65535.0 * 100;
Write-Output ([Math]::Round(pct))
"""
    out2, _, rc2 = _ps(fallback)
    if rc2 == 0 and out2:
        try:
            return _coerce_int(out2, 50, 0, 100), False
        except ValueError:
            pass
    return 50, False

def _ps_set_volume(level):
    """Set master volume to 0-100."""
    level = _coerce_int(level, 50, 0, 100)
    # Use nircmd if available, else PowerShell volume slider
    if _has_nircmd():
        _ps(f"nircmd setsysvolume {int(level * 655.35)}", timeout=5)
    else:
        # Use SendKeys (volume up/down) — less precise but no deps
        _ps(f"""
$obj = (New-Object -ComObject Sapi.SpSharedRecognizer).AudioObject
$obj.Volume = {level}
""", timeout=5)
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
        delta = _coerce_int(_json_body().get("delta", 10) if _json_body() else 10, 10, 1, 100)
        current, _ = _ps_get_volume()
        level = _coerce_int(current + delta, 50, 0, 100)
        _ps_set_volume(level)
        return jsonify({"status": "ok", "volume": level, "delta": delta})

    @app.route("/system/volume/down", methods=["POST"])
    @require_auth
    def route_system_volume_down():
        delta = _coerce_int(_json_body().get("delta", 10) if _json_body() else 10, 10, 1, 100)
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
        return jsonify({
            "volume": vol,
            "muted": muted,
            "brightness": bright,
            "brightness_supported": bright is not None,
            "nircmd_available": _has_nircmd(),
            "monitor_brightness_available": _has_monitor_info(),
        })


def _send_media_key(vk_code):
    """Send a virtual key code via keyboard driver."""
    import pyautogui as pg
    # Use ctypes SendInput
    kbi = ctypes.create_unicode_buffer(40)  # KEYBDINPUT size
    ctypes.memset(kbi, 0, 40)
    ctypes.memmove(kbi, ctypes.c_ushort(vk_code), 2)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_ulong),
            ("ki", KEYBDINPUT),
        ]

    def _send(vk, flags=0):
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    _send(vk_code)
    time.sleep(0.05)
    _send(vk_code, 2)  # KEYEVENTF_KEYUP
