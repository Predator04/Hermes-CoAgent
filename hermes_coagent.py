# ════════════════════════════════════════════════════════════════
# HERMES COAGENT v6.0 — SECURITY HARDENED
# ════════════════════════════════════════════════════════════════
import sys, os, json, base64, subprocess, threading, time, shutil
import re, queue, urllib.request
from io import BytesIO
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List
import ctypes

# Auth module (optional - provides --secure and --token support)
try:
    from auth import require_auth as _require_auth
    # Make them available at module level for route decorators
    require_auth = _require_auth
except ImportError:
    # Fallback no-op decorator
    def require_auth(f): return f

# UIA engine (Windows accessibility tree, SOM overlays, background input)
_uia_engine = None
HAS_SENDINPUT = False
def _get_uia_engine():
    global _uia_engine
    if _uia_engine is None:
        sys.path.insert(0, str(Path(__file__).parent))
        import uia_engine as ue
        _uia_engine = ue
    return _uia_engine

# Platform check — graceful fallback on non-Windows
import platform as _platform
if _platform.system() != "Windows":
    print(f"[WARN] Hermes CoAgent is designed for Windows (detected: {_platform.system()})")
    print("[WARN] Most features will not work. Running in stub mode.")
    HAS_SENDINPUT = False
    import types as _types
    _stub = _types.ModuleType('pyautogui')
    _stub.FAILSAFE = False
    _stub.MINIMUM_DURATION = 0
    _stub.MINIMUM_SLEEP = 0
    _stub.PAUSE = 0.01
    def _stub_pos(): return (0, 0)
    def _stub_noop(*a, **kw): pass
    _stub.position = _stub_pos
    _stub.moveTo = _stub_noop
    _stub.click = _stub_noop
    _stub.doubleClick = _stub_noop
    _stub.rightClick = _stub_noop
    _stub.typewrite = _stub_noop
    _stub.hotkey = _stub_noop
    _stub.scroll = _stub_noop
    _stub.drag = _stub_noop
    _stub.pixel = lambda x,y: (0,0,0)
    _stub.pixelMatchesColor = lambda *a,**kw: False
    sys.modules['pyautogui'] = _stub

os.environ["PYAUTOGUI_FAILSAFE"] = "false"

try:
    import pyautogui
    # On Windows, enable background SendInput co-pilot mode
    if _platform.system() == "Windows":
        HAS_SENDINPUT = True
except ImportError:
    print("[WARN] pyautogui not installed — input features disabled")
    pyautogui = _stub if '_stub' in dir() else None
    # Create stub if we haven't already
    if not pyautogui:
        import types as _types
        pyautogui = _types.ModuleType('pyautogui')
        pyautogui.FAILSAFE = False
        pyautogui.MINIMUM_DURATION = 0
        pyautogui.MINIMUM_SLEEP = 0
        pyautogui.PAUSE = 0.01
        def _s_noop(*a,**kw): pass
        pyautogui.position = lambda: (0,0)
        pyautogui.moveTo = _s_noop
        pyautogui.click = _s_noop
        pyautogui.doubleClick = _s_noop
        pyautogui.rightClick = _s_noop
        pyautogui.typewrite = _s_noop
        pyautogui.hotkey = _s_noop
        pyautogui.scroll = _s_noop
        pyautogui.drag = _s_noop
pyautogui.FAILSAFE = False
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0
pyautogui.PAUSE = 0.01

COAGENT_DIR = Path(__file__).parent.resolve()
MACROS_DIR = COAGENT_DIR / "macros"
SCREENSHOTS_DIR = COAGENT_DIR / "screenshots"
TUNNEL_LOG = COAGENT_DIR / "tunnel.log"
TRAY_LOG = COAGENT_DIR / "tray_icon.log"
SERVER_LOG = COAGENT_DIR / "coagent_server.log"
SERVER_PORT = 9123
TRAY_PORT = 9124
PULSE_DEFAULT_COLOR = 0x00FF00
PULSE_ACTION_COLORS = {
    "click": 0xFF4400,
    "doubleclick": 0xFF4400,
    "rightclick": 0xFF4400,
    "tripleclick": 0xFF4400,
    "type": 0x4488FF,
    "hotkey": 0xFF00FF,
    "scroll": 0xFFFF00,
    "drag": 0xFFAA00,
}

# Windows host IP reachable from WSL
try:
    _host_ip = subprocess.run(
        ["powershell.exe", "-Command",
         "(Get-NetIPAddress -InterfaceAlias 'vEthernet (WSL)' -AddressFamily IPv4).IPAddress"],
        capture_output=True, text=True, timeout=5
    ).stdout.strip()
    if not _host_ip:
        _host_ip = "172.21.192.1"
except:
    _host_ip = "172.21.192.1"
HOST_IP = _host_ip


# === SESSION CHECK — warn if no desktop access ===
def _ensure_interactive_session():
    """Check if we have desktop access. Warn if not, but don't try to fix it."""
    try:
        from ctypes import wintypes
        import ctypes
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return True
    except Exception:
        _console("WARNING: No desktop access (cursor=(0,0)). Launch from Windows desktop.")
        return False

_ensure_interactive_session()

from flask import Flask, request, jsonify, send_file, Response
app = Flask(__name__, static_folder=None)
MACROS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

def _attach_pythonw_stdio():
    try:
        if getattr(sys, "stdout", None) is None:
            sys.stdout = SERVER_LOG.open("a", encoding="utf-8", buffering=1)
        if getattr(sys, "stderr", None) is None:
            sys.stderr = SERVER_LOG.open("a", encoding="utf-8", buffering=1)
    except Exception:
        pass

_attach_pythonw_stdio()

PYTHON = sys.executable

def _console(msg=""):
    text = str(msg) + "\n"
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream.write(text)
            stream.flush()
            return
        except Exception:
            pass
    try:
        with SERVER_LOG.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

# === STATE ===
@dataclass
class CoPilotState:
    emergency_stop: bool = False
    input_lock: threading.Lock = field(default_factory=threading.Lock)
    last_action_time: float = 0.0
    min_action_gap: float = 0.05  # FASTER: 120ms → 50ms between actions
    last_screenshot_time: float = 0.0
    last_screenshot_data: dict = field(default_factory=dict)  # Cached multiple sizes
    last_screenshot_raw: bytes = b""
    screenshot_lock: threading.Lock = field(default_factory=threading.Lock)
    action_history: List[dict] = field(default_factory=list)
    max_history: int = 1000
    pending_queue: queue.Queue = field(default_factory=queue.Queue)
    queue_worker_running: bool = False
    recorder_active: bool = False
    recorder_actions: List[dict] = field(default_factory=list)
    tunnel_process: subprocess.Popen = None
    watchdog_running: bool = False

state = CoPilotState()

# === HELPER: PowerShell bridge ===
def ps(cmd, timeout=30):
    """Run PowerShell command, return (returncode, stdout, stderr)."""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

def _interactive_task_xml(command, arguments, author="CoAgent", execution_limit="PT10S", working_dir=None):
    """Build a Scheduled Task XML body for work that must run on the interactive desktop."""
    working_dir_xml = f"      <WorkingDirectory>{working_dir}</WorkingDirectory>\n" if working_dir else ""
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        f'  <RegistrationInfo><Author>{author}</Author></RegistrationInfo>\n'
        '  <Principals>\n'
        '    <Principal id="Author">\n'
        '      <UserId>Admin</UserId>\n'
        '      <LogonType>InteractiveToken</LogonType>\n'
        '      <RunLevel>HighestAvailable</RunLevel>\n'
        '    </Principal>\n'
        '  </Principals>\n'
        '  <Settings>\n'
        '    <Enabled>true</Enabled>\n'
        '    <AllowStartOnDemand>true</AllowStartOnDemand>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        f'    <ExecutionTimeLimit>{execution_limit}</ExecutionTimeLimit>\n'
        '    <Priority>7</Priority>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        '    <Exec>\n'
        f'      <Command>{command}</Command>\n'
        f'      <Arguments>{arguments}</Arguments>\n'
        f'{working_dir_xml}'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )

# === CURSOR PULSE - temporary topmost popup ===
# Each pulse owns a small topmost window, then fades and destroys it.

def _cursor_pulse(x, y, color=None):
    import win32gui, win32con, win32api, time
    from ctypes import windll
    try:
        if color is None:
            color = 0x00FF00
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
            "Static", "", win32con.WS_POPUP,
            x - 22, y - 22, 44, 44,
            0, 0, 0, None
        )
        windll.user32.SetLayeredWindowAttributes(hwnd, 0, 180, 2)
        dc = win32gui.GetDC(hwnd)
        brush = win32gui.CreateSolidBrush(win32api.RGB(r, g, b))
        win32gui.SelectObject(dc, brush)
        pen = win32gui.CreatePen(win32con.PS_SOLID, 2, win32api.RGB(255, 255, 255))
        win32gui.SelectObject(dc, pen)
        win32gui.Ellipse(dc, 2, 2, 42, 42)
        win32gui.SelectObject(dc, win32gui.GetStockObject(5))
        win32gui.DeleteObject(brush)
        win32gui.SelectObject(dc, win32gui.GetStockObject(5))
        win32gui.DeleteObject(pen)
        win32gui.ReleaseDC(hwnd, dc)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(hwnd)
        time.sleep(0.15)
        for i in range(6):
            alpha = max(0, 180 - i * 30)
            windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, 2)
            time.sleep(0.03)
        win32gui.DestroyWindow(hwnd)
    except Exception:
        pass

def _current_cursor_pos(default=(960, 540)):
    try:
        pos = pyautogui.position()
        return int(pos[0]), int(pos[1])
    except Exception as e:
        _console(f"[Pulse] Could not read cursor position: {e}")
        return default

def _pulse_before_action(action: dict):
    """Show a colored pulse based on action type before executing."""
    try:
        act_type = action.get("type", "")
        data = action.get("data", {})
        color = PULSE_ACTION_COLORS.get(act_type, PULSE_DEFAULT_COLOR)

        fallback_x, fallback_y = _current_cursor_pos()
        x = data.get("x", data.get("x2", data.get("x1", fallback_x)))
        y = data.get("y", data.get("y2", data.get("y1", fallback_y)))
        _cursor_pulse(x, y, color)
    except Exception:
        pass

# === INPUT ENGINE ===
def _execute_action(action: dict):
    act_type = action.get("type")
    data = action.get("data", {})
    bg_mode = data.get("background", True)  # default to background mode
    _pulse_before_action(action)
    with state.input_lock:
        if state.emergency_stop:
            raise Exception("Emergency stop active")
        elapsed = time.time() - state.last_action_time
        if elapsed < state.min_action_gap:
            time.sleep(state.min_action_gap - elapsed)
        try:
            if act_type == "move":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_mouse_move(data["x"], data["y"])
                else:
                    pyautogui.moveTo(data["x"], data["y"], duration=data.get("duration", 0.01))
            elif act_type == "click":
                if bg_mode and HAS_SENDINPUT:
                    btn = data.get("button", "left")
                    _get_uia_engine().send_mouse_click(data.get("x", None), data.get("y", None), button=btn, clicks=data.get("clicks", 1))
                else:
                    pyautogui.click(button=data.get("button", "left"), clicks=data.get("clicks", 1), interval=0.005)
            elif act_type == "type":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_keys(data["text"])
                else:
                    pyautogui.typewrite(data["text"], interval=data.get("interval", 0.005))
            elif act_type == "hotkey":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_input(data.get("keys", []))
                else:
                    pyautogui.hotkey(*data.get("keys", []))
            elif act_type == "scroll":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_scroll(data.get("clicks", -3))
                else:
                    pyautogui.scroll(data.get("clicks", -3))
            elif act_type == "drag":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_mouse_drag(
                        data["x1"], data["y1"], data["x2"], data["y2"],
                        button=data.get("button", "left")
                    )
                else:
                    pyautogui.moveTo(data["x1"], data["y1"], duration=0.01)
                    pyautogui.drag(data["x2"]-data["x1"], data["y2"]-data["y1"],
                                  button=data.get("button","left"), duration=data.get("duration",0.15))
            elif act_type == "doubleclick":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_mouse_click(data.get("x", None), data.get("y", None), button=data.get("button","left"), clicks=2)
                else:
                    pyautogui.doubleClick(button=data.get("button","left"))
            elif act_type == "rightclick":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_mouse_click(data.get("x", None), data.get("y", None), button="right")
                else:
                    pyautogui.rightClick(button=data.get("button","right"))
            elif act_type == "tripleclick":
                if bg_mode and HAS_SENDINPUT:
                    _get_uia_engine().send_mouse_click(data.get("x", None), data.get("y", None), button=data.get("button","left"), clicks=3)
                else:
                    pyautogui.tripleClick(button=data.get("button","left"))
        finally:
            state.last_action_time = time.time()
        state.action_history.append({"type":act_type,"data":data,"time":datetime.now().isoformat()})
        if len(state.action_history) > state.max_history:
            state.action_history = state.action_history[-state.max_history:]

def _queue_worker():
    state.queue_worker_running = True
    while True:
        try:
            action = state.pending_queue.get(timeout=1)
        except queue.Empty:
            if state.emergency_stop:
                break
            continue
        try:
            _execute_action(action)
        except Exception as e:
            _console(f"[Queue] Failed: {e}")
        time.sleep(max(0, state.min_action_gap - 0.05))
    state.queue_worker_running = False

# === SCREENSHOT ENGINE ===
def _grab_screen_bytes(force=False) -> bytes:
    now = time.time()
    if not force and state.last_screenshot_raw and (now - state.last_screenshot_time) < 0.5:
        return state.last_screenshot_raw
    with state.screenshot_lock:
        if not force and state.last_screenshot_raw and (time.time() - state.last_screenshot_time) < 0.5:
            return state.last_screenshot_raw
        img_bytes = _capture_raw()
        state.last_screenshot_raw = img_bytes
        state.last_screenshot_time = time.time()
        return img_bytes

def _capture_via_session1(fmt="png") -> bytes:
    """Capture screenshot from Session 1 via tray icon relay server.
    The tray icon (running on Session 1) serves screenshots on TRAY_PORT.
    This is instant with no PowerShell flash.
    Supports fmt='png' or fmt='jpeg' (quality 85)."""
    try:
        url = f"http://{HOST_IP}:{TRAY_PORT}/screen"
        if fmt == "jpeg":
            url += "?format=jpeg"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except Exception as e:
        _console(f"  [WARN] Tray relay failed ({e}), falling back to schtasks")

    # Fallback: original schtasks method
    out_path = Path("C:/Temp/_coagent_screen.png")
    ps1_script = COAGENT_DIR / "session1_capture.ps1"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except:
        pass

    # Build XML task targeting Session 1 with InteractiveToken
    task_name = "HermesCoAgent_Snap"
    subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                   capture_output=True, timeout=5)

    xml = _interactive_task_xml(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        '-ExecutionPolicy Bypass -WindowStyle Hidden -File "' + str(ps1_script) +
        '" -OutputPath "' + str(out_path) + '"',
        execution_limit="PT30S",
    )

    xml_path = COAGENT_DIR / "_snap_task.xml"
    try:
        xml_path.write_text(xml, encoding="utf-16")
    except:
        pass

    r1 = subprocess.run(
        ["schtasks", "/Create", "/XML", str(xml_path), "/TN", task_name, "/F"],
        capture_output=True, text=True, timeout=10
    )

    if r1.returncode == 0:
        subprocess.run(
            ["schtasks", "/Run", "/TN", task_name],
            capture_output=True, text=True, timeout=30
        )
        # Give it a moment to write the file
        import time as _time
        _time.sleep(1.0)
        if out_path.exists():
            data = out_path.read_bytes()
            if len(data) > 1000:
                return data

    # Fallback: try direct PowerShell
    try:
        rc, out, err = ps('''
Add-Type -AssemblyName System.Drawing; Add-Type -AssemblyName System.Windows.Forms
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $b.Size)
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
[System.Convert]::ToBase64String($ms.ToArray())
$g.Dispose(); $bmp.Dispose()
''', timeout=15)
        if rc == 0 and len(out) > 500:
            return base64.b64decode(out)
    except:
        pass

    raise Exception("No screenshot method works on Session 0. Tray icon must be running on desktop.")


def _send_keys_session1(keys: str) -> bool:
    """Execute key combo on Session 1 via schtasks with InteractiveToken.
    Works from Session 0 by running session1_keys.ps1 on the interactive desktop."""
    ps1_script = COAGENT_DIR / "session1_keys.ps1"
    task_name = "HermesCoAgent_Keys"
    subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                   capture_output=True, timeout=5)

    xml = _interactive_task_xml(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        '-ExecutionPolicy Bypass -WindowStyle Hidden -File "' + str(ps1_script) +
        '" -Keys "' + keys + '"',
    )

    xml_path = COAGENT_DIR / "_keys_task.xml"
    try:
        xml_path.write_text(xml, encoding="utf-16")
    except:
        pass

    r1 = subprocess.run(
        ["schtasks", "/Create", "/XML", str(xml_path), "/TN", task_name, "/F"],
        capture_output=True, text=True, timeout=10
    )

    if r1.returncode == 0:
        r2 = subprocess.run(
            ["schtasks", "/Run", "/TN", task_name],
            capture_output=True, text=True, timeout=15
        )
        try:
            xml_path.unlink()
        except:
            pass
        return r2.returncode == 0
    try:
        xml_path.unlink()
    except:
        pass
    return False


def _is_black_screenshot(img) -> bool:
    """Detect if PIL ImageGrab returned a blank/black screen (Session 0 ghost desktop)."""
    try:
        extrema = img.getextrema()
        # (0, 0) for all bands = pure black
        for band in extrema:
            if band != (0, 0):
                return False
        return True
    except:
        return False


def _capture_raw(fmt="png") -> bytes:
    # Method 1: PIL ImageGrab (fastest when available - <100ms)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if img and not _is_black_screenshot(img):
            buf = BytesIO()
            if fmt == "jpeg":
                img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=85, optimize=True)
            else:
                img.save(buf, format="PNG")
            return buf.getvalue()
        _console("  [INFO] PIL returned black screen (Session 0) - trying Session 1...")
    except:
        pass
    # Method 2: schtasks to Session 1 (works from Session 0)
    try:
        return _capture_via_session1(fmt=fmt)
    except Exception as e:
        _console(f"  [WARN] Session 1 capture failed: {e}")
    raise Exception("No screenshot method works. Double-click start.bat in your desktop session.")

# === MCP SERVER (stdin/stdout JSON-RPC for Hermes) ===
def run_mcp():
    """MCP protocol: read JSON-RPC 2.0 from stdin, write to stdout."""
    mcp_tools = [
        {"name":"ping","description":"Health check","inputSchema":{"type":"object","properties":{}}},
        {"name":"cursor_pos","description":"Get cursor position","inputSchema":{"type":"object","properties":{}}},
        {"name":"mouse_move","description":"Move mouse to XY","inputSchema":{"type":"object","properties":{"x":{"type":"number"},"y":{"type":"number"}},"required":["x","y"]}},
        {"name":"mouse_click","description":"Click mouse button","inputSchema":{"type":"object","properties":{"button":{"type":"string","enum":["left","right","middle"],"default":"left"}}}},
        {"name":"mouse_doubleclick","description":"Double click","inputSchema":{"type":"object","properties":{"button":{"type":"string","default":"left"}}}},
        {"name":"mouse_drag","description":"Drag from x1,y1 to x2,y2","inputSchema":{"type":"object","properties":{"x1":{"type":"number"},"y1":{"type":"number"},"x2":{"type":"number"},"y2":{"type":"number"},"button":{"type":"string","default":"left"}},"required":["x1","y1","x2","y2"]}},
        {"name":"mouse_scroll","description":"Scroll","inputSchema":{"type":"object","properties":{"clicks":{"type":"integer","default":-3}}}},
        {"name":"key_type","description":"Type text","inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}},
        {"name":"key_press","description":"Press hotkey combo","inputSchema":{"type":"object","properties":{"keys":{"type":"array","items":{"type":"string"}}},"required":["keys"]}},
        {"name":"screenshot","description":"Get screenshot as base64 PNG","inputSchema":{"type":"object","properties":{}}},
        {"name":"ocr_find","description":"Find text on screen and return coords","inputSchema":{"type":"object","properties":{"text":{"type":"string"},"region":{"type":"array","items":{"type":"integer"},"description":"[x,y,w,h]"}},"required":["text"]}},
        {"name":"visual_find","description":"Find image on screen","inputSchema":{"type":"object","properties":{"template_path":{"type":"string"},"confidence":{"type":"number","default":0.8}},"required":["template_path"]}},
        {"name":"list_windows","description":"List open windows","inputSchema":{"type":"object","properties":{}}},
        {"name":"activate_window","description":"Activate window by title","inputSchema":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}},
        {"name":"run_command","description":"Run shell command","inputSchema":{"type":"object","properties":{"cmd":{"type":"string"},"timeout":{"type":"integer","default":30}},"required":["cmd"]}},
        {"name":"file_list","description":"List files in directory","inputSchema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
        {"name":"file_read","description":"Read file contents","inputSchema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
        {"name":"macro_list","description":"List saved macros","inputSchema":{"type":"object","properties":{}}},
        {"name":"macro_run","description":"Run a saved macro","inputSchema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}},
        {"name":"macro_record","description":"Start recording macro","inputSchema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}},
        {"name":"clipboard_get","description":"Get clipboard text","inputSchema":{"type":"object","properties":{}}},
        {"name":"clipboard_set","description":"Set clipboard text","inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}},
        {"name":"emergency_stop","description":"Emergency stop all input","inputSchema":{"type":"object","properties":{}}},
        {"name":"emergency_resume","description":"Resume input","inputSchema":{"type":"object","properties":{}}},
        {"name":"app_open","description":"Open application/file","inputSchema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
        {"name":"monitors","description":"Get monitor layout","inputSchema":{"type":"object","properties":{}}},
        {"name":"tts_speak","description":"Speak text through speakers","inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}},
    ]
    mcp_handlers = {
        "ping": lambda p: {"status":"ok","agent":"Hermes CoAgent v3","mode":"mcp"},
        "cursor_pos": lambda p: {"x":pyautogui.position()[0],"y":pyautogui.position()[1]},
        "mouse_move": lambda p: (_execute_action({"type":"move","data":p}),{"status":"moved"})[1],
        "mouse_click": lambda p: (_execute_action({"type":"click","data":p}),{"status":"clicked"})[1],
        "mouse_doubleclick": lambda p: (_execute_action({"type":"doubleclick","data":p}),{"status":"double_clicked"})[1],
        "mouse_drag": lambda p: (_execute_action({"type":"drag","data":p}),{"status":"dragged"})[1],
        "mouse_scroll": lambda p: (_execute_action({"type":"scroll","data":p}),{"status":"scrolled"})[1],
        "key_type": lambda p: (_execute_action({"type":"type","data":p}),{"status":"typed","chars":len(p.get("text",""))})[1],
        "key_press": lambda p: (_execute_action({"type":"hotkey","data":p}),{"status":"pressed"})[1],
        "screenshot": lambda p: {"data":base64.b64encode(_grab_screen_bytes(force=True)).decode()},
        "ocr_find": lambda p: ocr_find_text(p["text"], p.get("region")),
        "visual_find": lambda p: visual_find_image(p["template_path"], p.get("confidence",0.8)),
        "list_windows": lambda p: list_windows_api(),
        "activate_window": lambda p: activate_window_api(p["title"]),
        "run_command": lambda p: run_command_api(p["cmd"], p.get("timeout",30)),
        "file_list": lambda p: file_list_api(p["path"]),
        "file_read": lambda p: file_read_api(p["path"]),
        "macro_list": lambda p: macro_list_api(),
        "macro_run": lambda p: macro_run_api(p["name"]),
        "macro_record": lambda p: macro_record_api(p["name"]),
        "clipboard_get": lambda p: clipboard_get_api(),
        "clipboard_set": lambda p: clipboard_set_api(p["text"]),
        "emergency_stop": lambda p: (setattr(state,"emergency_stop",True),{"status":"stopped"})[1],
        "emergency_resume": lambda p: (setattr(state,"emergency_stop",False),{"status":"resumed"})[1],
        "app_open": lambda p: _launch_app_safe(p["path"]),
        "monitors": lambda p: monitors_api(),
        "tts_speak": lambda p: tts_speak_api(p["text"]),
    }
    import sys as _sys
    _sys.stdin.reconfigure(encoding='utf-8')
    _sys.stdout.reconfigure(encoding='utf-8')
    _console("CoAgent MCP Server")
    for line in _sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
            method = req.get("method","")
            params = req.get("params",{})
            if method == "list_tools":
                resp = {"jsonrpc":"2.0","id":req.get("id"),"result":{"tools":mcp_tools}}
            elif method in mcp_handlers:
                result = mcp_handlers[method](params)
                resp = {"jsonrpc":"2.0","id":req.get("id"),"result":result}
            else:
                resp = {"jsonrpc":"2.0","id":req.get("id"),"error":{"code":-32601,"message":f"Unknown tool: {method}"}}
        except Exception as e:
            resp = {"jsonrpc":"2.0","id":req.get("id") if 'req' in dir() else None,"error":{"code":-32603,"message":str(e)}}
        _sys.stdout.write(json.dumps(resp)+"\n")
        _sys.stdout.flush()

# === OCR ENGINE ===
def ocr_find_text(text_query, region=None):
    try:
        import pytesseract
        from PIL import Image
        from io import BytesIO
        img_bytes = _grab_screen_bytes(force=True)
        img = Image.open(BytesIO(img_bytes))
        if region:
            img = img.crop((region[0], region[1], region[0]+region[2], region[1]+region[3]))
        # Get data with bounding boxes
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        results = []
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if word and text_query.lower() in word.lower():
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                cx = x + w//2
                cy = y + h//2
                if region:
                    cx += region[0]
                    cy += region[1]
                results.append({"word":word,"confidence":data["conf"][i],"bbox":[x,y,w,h],"center":[cx,cy]})
        return {"found": len(results)>0, "matches": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)}

# === VISUAL SEARCH ENGINE ===
def visual_find_image(template_path, confidence=0.8):
    try:
        import cv2
        import numpy as np
        from PIL import Image
        from io import BytesIO
        if not os.path.isfile(template_path):
            return {"error": f"Template not found: {template_path}"}
        screen_bytes = _grab_screen_bytes(force=True)
        screen = cv2.cvtColor(np.array(Image.open(BytesIO(screen_bytes))), cv2.COLOR_RGB2BGR)
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return {"error": "Could not read template image"}
        h, w = template.shape[:2]
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val >= confidence:
            return {"found": True, "confidence": float(max_val),
                    "bbox": [int(max_loc[0]), int(max_loc[1]), w, h],
                    "center": [int(max_loc[0]+w//2), int(max_loc[1]+h//2)]}
        return {"found": False, "confidence": float(max_val), "best_match": [int(max_loc[0]), int(max_loc[1])]}
    except Exception as e:
        return {"error": str(e)}

# === TTS ENGINE ===
def tts_speak_api(text):
    try:
        script = "$speaker = New-Object -ComObject SAPI.SpVoice; $speaker.Speak([Console]::In.ReadToEnd()) | Out-Null"
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        try:
            proc.communicate(input=str(text), timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"error": "TTS timed out"}
        return {"status": "speaking", "text": str(text)[:100]}
    except Exception as e:
        return {"error": str(e)}

# === KEYBOARD WATCHDOG ===
def _keyboard_watchdog():
    """Monitor global keyboard for Ctrl+Alt+Shift -> emergency stop"""
    state.watchdog_running = True
    try:
        from pynput import keyboard
        ctrl, alt, shift = False, False, False
        def on_press(key):
            nonlocal ctrl, alt, shift
            if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r: ctrl = True
            if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r: alt = True
            if key == keyboard.Key.shift or key == keyboard.Key.shift_r: shift = True
            if ctrl and alt and shift:
                state.emergency_stop = True
                _console("[Watchdog] EMERGENCY STOP triggered via Ctrl+Alt+Shift")
                ctrl, alt, shift = False, False, False
        def on_release(key):
            nonlocal ctrl, alt, shift
            if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r: ctrl = False
            if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r: alt = False
            if key == keyboard.Key.shift or key == keyboard.Key.shift_r: shift = False
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    except Exception as e:
        _console(f"[Watchdog] Failed: {e}")
    state.watchdog_running = False

# === MACROS ENGINE ===
def macro_list_api():
    macros = []
    for f in MACROS_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        macros.append({"name": f.stem, "actions": len(data.get("actions", [])),
                       "created": data.get("created",""), "modified": data.get("modified","")})
    return {"macros": macros}

def macro_save_api(name, actions):
    path = MACROS_DIR / f"{name}.json"
    now = str(datetime.now())
    data = {"name": name, "actions": actions, "created": now, "modified": now}
    path.write_text(json.dumps(data, indent=2))
    return {"status": "saved", "name": name, "actions": len(actions)}

def macro_load(name):
    path = MACROS_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None

def macro_run_api(name):
    data = macro_load(name)
    if not data:
        return {"error": f"Macro '{name}' not found"}
    actions = data.get("actions", [])
    results = []
    for i, action in enumerate(actions):
        try:
            _execute_action(action)
            results.append({"index": i, "status": "ok", "type": action.get("type")})
        except Exception as e:
            results.append({"index": i, "status": "error", "error": str(e)})
            break
    return {"name": name, "executed": len(results), "total": len(actions), "results": results}

def macro_record_api(name):
    state.recorder_active = True
    state.recorder_actions = []
    # Start listener thread that captures keyboard/mouse events
    def _recorder_thread():
        from pynput import mouse, keyboard
        recording_name = name
        def on_click(x, y, button, pressed):
            if not state.recorder_active:
                return False
            if pressed:
                btn = "left"
                if button == mouse.Button.right: btn = "right"
                elif button == mouse.Button.middle: btn = "middle"
                state.recorder_actions.append({"type": "click", "data": {"button": btn}})
        def on_move(x, y):
            if not state.recorder_active:
                return False
            # Throttle - only record every 10th move
            if len(state.recorder_actions) == 0 or state.recorder_actions[-1].get("type") != "move":
                state.recorder_actions.append({"type": "move", "data": {"x": x, "y": y, "duration": 0.02}})
        def on_scroll(x, y, dx, dy):
            if not state.recorder_active:
                return False
            state.recorder_actions.append({"type": "scroll", "data": {"clicks": dy}})
        def on_press(key):
            if not state.recorder_active:
                return False
            try:
                if hasattr(key, 'char') and key.char:
                    state.recorder_actions.append({"type": "type", "data": {"text": key.char}})
            except: pass
            # Stop recording on F9
            try:
                if key.name == "f9":
                    state.recorder_active = False
                    macro_save_api(recording_name, state.recorder_actions)
                    return False
            except: pass
        with mouse.Listener(on_click=on_click, on_move=on_move, on_scroll=on_scroll) as ml, \
             keyboard.Listener(on_press=on_press) as kl:
            ml.join()
            kl.join()
    t = threading.Thread(target=_recorder_thread, daemon=True)
    t.start()
    return {"status": "recording", "name": name, "message": "Press F9 to stop recording"}
# === FILE EXPLORER API ===
def file_list_api(folder="."):
    try:
        p = Path(folder).resolve()
        items = []
        for item in sorted(p.iterdir()):
            try:
                is_dir = item.is_dir()
                stat = item.stat()
                items.append({
                    "name": item.name, "path": str(item),
                    "is_dir": is_dir, "size": 0 if is_dir else stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except: pass
        return {"path": str(p), "items": items, "count": len(items)}
    except Exception as e:
        return {"error": str(e)}

def file_read_api(path):
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        stat = p.stat()
        if stat.st_size > 50 * 1024 * 1024:
            return {"error": "File too large (>50MB)"}
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
            is_text = True
        except UnicodeDecodeError:
            text = base64.b64encode(data).decode()
            is_text = False
        return {"path": str(p), "size": stat.st_size,
                "is_text": is_text,
                "content": text}
    except Exception as e:
        return {"error": str(e)}

def file_write_api(path, content, is_base64=False):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if is_base64:
            p.write_bytes(base64.b64decode(content))
        else:
            p.write_text(content)
        return {"status": "written", "path": str(p), "size": p.stat().st_size}
    except Exception as e:
        return {"error": str(e)}

def file_delete_api(path):
    try:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"status": "deleted", "path": str(p)}
    except Exception as e:
        return {"error": str(e)}

# === WINDOW & MONITOR HELPERS ===
def list_windows_api():
    try:
        import pygetwindow as gw
        wins = [{"title": w.title, "left": w.left, "top": w.top,
                 "width": w.width, "height": w.height, "active": w.isActive}
                for w in gw.getAllWindows() if w.title.strip()]
        return {"windows": wins}
    except Exception as e:
        return {"error": str(e)}

def activate_window_api(title):
    try:
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle(title)
        if not wins:
            return {"error": f"No window matching '{title}'"}
        wins[0].activate()
        wins[0].restore()
        return {"status": "activated", "title": wins[0].title}
    except Exception as e:
        return {"error": str(e)}

def monitors_api():
    try:
        import mss
        with mss.mss() as sct:
            mons = []
            for i, m in enumerate(sct.monitors):
                if i == 0: continue
                mons.append({"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]})
            return {"monitors": mons}
    except:
        return {"monitors": [{"width": 1920, "height": 1080, "left": 0, "top": 0}]}

SAFE_ALLOWED_ROOTS = [
    Path(os.environ.get('USERPROFILE', 'C:/Users/Default')).resolve(),
    Path(os.environ.get('TEMP', 'C:/Temp')).resolve(),
    COAGENT_DIR,
]
DANGEROUS_CMD_CHARS = frozenset('|;&`$(){}<>')

def _sanitize_path(p):
    """Block path traversal. Only allow paths under allowed roots."""
    resolved = Path(p).resolve()
    if not any(str(resolved).startswith(str(r)) for r in SAFE_ALLOWED_ROOTS):
        raise ValueError(f"Path traversal blocked: {p} -> {resolved}")
    return str(resolved)

def _sanitize_cmd(cmd_str):
    """Block dangerous shell metacharacters in string commands."""
    for d in DANGEROUS_CMD_CHARS:
        if d in cmd_str:
            raise ValueError(f"Command blocked: contains character {repr(d)}")
    return cmd_str.split()

def run_command_api(cmd, timeout=30):
    try:
        if isinstance(cmd, str):
            args = _sanitize_cmd(cmd)
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"stdout": r.stdout[:100000], "stderr": r.stderr[:50000], "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except Exception as e:
        return {"error": str(e)}

def clipboard_get_api():
    try:
        import pyperclip
        return {"text": pyperclip.paste()}
    except Exception as e:
        return {"error": str(e)}

def clipboard_set_api(text):
    try:
        import pyperclip
        pyperclip.copy(text)
        return {"status": "copied", "chars": len(text)}
    except Exception as e:
        return {"error": str(e)}

def _launch_app_safe(path):
    """Launch an application without shell=True. Only allows .exe, .lnk, URLs."""
    path = str(path)
    # Only allow safe file types
    safe_extensions = ('.exe', '.lnk', '.bat', '.cmd', '.msi', '.url')
    if path.startswith(('http://', 'https://', 'ms-')):
        # System protocol handlers (ms-settings: etc) are safe
        subprocess.Popen(['start', path], shell=True)
        return {"status": "launched", "path": path}
    if not path.lower().endswith(safe_extensions):
        return {"error": f"Unsafe file type: {path}"}, 400
    subprocess.Popen([path], shell=False)
    return {"status": "launched", "path": path}

# === CLOUDFLARE TUNNEL ===
def tunnel_start_action():
    if state.tunnel_process and state.tunnel_process.poll() is None:
        return {"status": "already_running"}
    ps("Get-Command cloudflared -ErrorAction SilentlyContinue")
    try:
        _log = open(str(TUNNEL_LOG), "w")
        _p = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{SERVER_PORT}"],
            stdout=_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        state.tunnel_process = _p
        for i in range(30):
            if TUNNEL_LOG.exists():
                _logtxt = TUNNEL_LOG.read_text()
                _m = re.search(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com', _logtxt)
                if _m:
                    return {"status": "running", "url": _m.group(0), "pid": _p.pid}
            time.sleep(1)
        return {"status": "started", "message": "Tunnel starting...", "pid": _p.pid}
    except Exception as e:
        return {"error": str(e)}

def tunnel_stop_action():
    if state.tunnel_process and state.tunnel_process.poll() is None:
        state.tunnel_process.terminate()
        state.tunnel_process = None
        return {"status": "stopped"}
    return {"status": "not_running"}

def tunnel_status_action():
    if state.tunnel_process and state.tunnel_process.poll() is None:
        _logtxt = TUNNEL_LOG.read_text()[:2000] if TUNNEL_LOG.exists() else ""
        _m = re.search(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com', _logtxt)
        _url = _m.group(0) if _m else "connecting..."
        return {"running": True, "url": _url, "pid": state.tunnel_process.pid}
    return {"running": False}


# === SSE EVENTS (real-time action broadcasting) ===
import threading as _sse_threading
_sse_clients = []
_sse_lock = _sse_threading.Lock()

def _sse_broadcast(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

@app.route("/events")
def sse_events():
    def gen():
        q = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)
        try:
            yield f"event: status\ndata: {json.dumps({'running': True, 'emergency': state.emergency_stop})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
    return Response(gen(), mimetype="text/event-stream")

# === LOGS ===
_log_buffer = []
_log_lock = _sse_threading.Lock()
_MAX_LOG = 5000

def _log(msg):
    entry = {"time": datetime.now().isoformat(), "msg": str(msg)}
    with _log_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > _MAX_LOG:
            _log_buffer[:1000] = []

def _limit_arg(name, default, maximum):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, maximum))

@app.route("/logs")
def route_logs():
    limit = _limit_arg("limit", 200, 1000)
    with _log_lock:
        logs = [] if limit == 0 else _log_buffer[-limit:]
        return jsonify({"logs": logs})

# === STATS ===
_start_time = time.time()
_psutil_avail = False
try:
    import psutil
    _psutil_avail = True
except:
    pass

@app.route("/stats")
def route_stats():
    with state.input_lock:
        actions_today = len(state.action_history)
    info = {
        "actions_today": actions_today,
        "queue_size": state.pending_queue.qsize(),
        "emergency_stop": state.emergency_stop,
        "watchdog": state.watchdog_running,
        "uptime_seconds": round(time.time() - _start_time),
        "screenshot_cache_age": round(time.time() - state.last_screenshot_time, 1) if state.last_screenshot_time else None
    }
    if _psutil_avail:
        try:
            proc = psutil.Process(os.getpid())
            info["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
            info["cpu_percent"] = proc.cpu_percent(interval=0.1)
        except:
            pass
    return jsonify(info)

# Patch _execute_action to broadcast and log
_execute_action_orig = _execute_action
def _execute_action_wrapper(action):
    _execute_action_orig(action)
    _log(f"{action.get('type')}: {json.dumps(action.get('data', {}))[:100]}")
    _sse_broadcast("action", {"type": action.get("type"), "data": action.get("data", {}),
                               "time": datetime.now().isoformat()})
_execute_action = _execute_action_wrapper


DASHBOARD_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Hermes CoAgent v5.1</title>\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;background:#0a0a0f;color:#e0e0e0;overflow:hidden;height:100vh}\n.app{display:grid;grid-template-columns:320px 1fr 300px;height:100vh;gap:1px;background:#1a1a2e}\n.panel{background:#111122;padding:12px;overflow-y:auto}\n.panel h2{font-size:13px;text-transform:uppercase;color:#666;margin-bottom:10px;letter-spacing:1px}\n.btn{background:#1a1a3e;border:1px solid #333;color:#ccc;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s}\n.btn:hover{background:#2a2a5e;border-color:#555}\n.btn.danger{background:#3a1111;border-color:#633}\n.btn.danger:hover{background:#5a1515;border-color:#a33}\n.btn.success{background:#113a11;border-color:#363}\n.btn.success:hover{background:#155a15;border-color:#3a3}\n.btn-row{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}\n#screenshot-container{position:relative;display:flex;align-items:center;justify-content:center;height:100%;overflow:hidden;background:#0a0a0f}\n#screen-img{max-width:100%;max-height:100%;object-fit:contain;image-rendering:auto;cursor:crosshair;border-radius:4px}\n.coord-overlay{position:absolute;top:0;left:0;pointer-events:none;color:#fff;background:rgba(0,0,0,0.7);padding:2px 6px;border-radius:4px;font-size:11px;font-family:monospace;z-index:10}\n.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}\n.dot-green{background:#0f0}\n.dot-red{background:#f00}\n.dot-yellow{background:#ff0}\n#action-log{font-family:monospace;font-size:11px;line-height:1.6}\n.action-entry{padding:2px 0;border-bottom:1px solid #1a1a2e;display:flex;justify-content:space-between}\n.action-time{color:#555;font-size:10px}\n.logo{font-size:20px;font-weight:bold;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}\n.subtitle{font-size:11px;color:#666;margin-bottom:12px}\ninput[type=text],input[type=number]{background:#1a1a2e;border:1px solid #333;color:#ccc;padding:5px 8px;border-radius:4px;font-size:12px;width:100%;margin-bottom:6px}\nlabel{font-size:11px;color:#888;display:block;margin-bottom:2px}\n.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}\n.tool-group{margin-bottom:12px;padding:8px;background:#0e0e1a;border-radius:6px}\n.tool-group h3{font-size:12px;color:#888;margin-bottom:6px}\n#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1a1a3e;border:1px solid #444;padding:8px 16px;border-radius:8px;font-size:12px;z-index:999;display:none}\n</style>\n</head>\n<body>\n<div id="toast"></div>\n<div class="app">\n  <div class="panel" id="left-panel">\n    <div class="logo"> Hermes CoAgent</div>\n    <div class="subtitle">v5.0 - Desktop Co-Pilot</div>\n    <div id="status-bar" style="margin-bottom:10px"><span class="status-dot dot-green"></span><span id="status-text">Connected</span></div>\n\n    <div class="tool-group">\n      <h3> Mouse</h3>\n      <div class="grid">\n        <div><label>X</label><input type="number" id="mx" value="960"></div>\n        <div><label>Y</label><input type="number" id="my" value="540"></div>\n      </div>\n      <div class="btn-row">\n        <button class="btn" onclick="mouseMove()">Move</button>\n        <button class="btn" onclick="mouseClick(\'left\')">Left</button>\n        <button class="btn" onclick="mouseClick(\'right\')">Right</button>\n        <button class="btn" onclick="mouseClick(\'middle\')">Mid</button>\n        <button class="btn" onclick="mouseDClick()">Dbl</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Keyboard</h3>\n      <input type="text" id="type-text" placeholder="Type something..." onkeydown="if(event.key===\'Enter\')keyType()">\n      <div class="btn-row">\n        <button class="btn" onclick="keyType()">Type</button>\n        <button class="btn" onclick="keyPress([\'ctrl\',\'c\'])">Ctrl+C</button>\n        <button class="btn" onclick="keyPress([\'ctrl\',\'v\'])">Ctrl+V</button>\n        <button class="btn" onclick="keyPress([\'enter\'])">Enter</button>\n        <button class="btn" onclick="keyPress([\'tab\'])">Tab</button>\n        <button class="btn" onclick="keyPress([\'escape\'])">Esc</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Find</h3>\n      <input type="text" id="find-text" placeholder="Text on screen...">\n      <div class="btn-row">\n        <button class="btn" onclick="ocrFind()">Find Text</button>\n        <button class="btn" onclick="cursorPos()">Cursor</button>\n        <button class="btn" onclick="monitors()">Monitors</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Files</h3>\n      <input type="text" id="file-path" placeholder="C:\\Users\\Admin\\Desktop" value="C:\\Users\\Admin\\Desktop">\n      <div class="btn-row">\n        <button class="btn" onclick="fileList()">List</button>\n        <button class="btn" onclick="appOpen()">Open</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Macros</h3>\n      <input type="text" id="macro-name" placeholder="macro name">\n      <div class="btn-row">\n        <button class="btn" onclick="macroList()">List</button>\n        <button class="btn success" onclick="macroRecord()">Record</button>\n        <button class="btn" onclick="macroRun()">Run</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Emergency</h3>\n      <div class="btn-row">\n        <button class="btn danger" onclick="emergency(\'stop\')"> STOP</button>\n        <button class="btn success" onclick="emergency(\'resume\')"> Resume</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Tunnel</h3>\n      <div class="btn-row">\n        <button class="btn" onclick="tunnel(\'start\')">Start</button>\n        <button class="btn danger" onclick="tunnel(\'stop\')">Stop</button>\n        <button class="btn" onclick="tunnel(\'status\')">Status</button>\n      </div>\n      <div id="tunnel-info" style="font-size:11px;color:#666"></div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Power</h3>\n      <div class="btn-row">\n        <button class="btn" onclick="power(\'sleep\')">Sleep</button>\n        <button class="btn" onclick="power(\'shutdown\')">Shut</button>\n        <button class="btn" onclick="power(\'restart\')">Restart</button>\n        <button class="btn" onclick="power(\'lock\')">Lock</button>\n        <button class="btn" onclick="power(\'cancel\')">Cancel</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Wallpaper</h3>\n      <input type="text" id="wp-folder" placeholder="C:\\wallpapers" value="C:\\Users\\Admin\\Desktop">\n      <div class="btn-row">\n        <button class="btn" onclick="wpSet()">Set</button>\n        <button class="btn" onclick="wpCycle()">Cycle</button>\n        <button class="btn" onclick="wpRandom()">Random</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Search</h3>\n      <input type="text" id="search-pat" placeholder="*.pdf" value="*.pdf">\n      <input type="text" id="search-path" placeholder="C:\\" value="C:\\Users\\Admin">\n      <div class="btn-row">\n        <button class="btn" onclick="searchFiles()">Search</button>\n      </div>\n      <div id="search-results" style="font-size:11px;color:#666;max-height:100px;overflow-y:auto"></div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Screen</h3>\n      <div class="btn-row">\n        <button class="btn" onclick="cropScreen()">Crop/OCR</button>\n        <button class="btn" onclick="describeScreen()">Describe</button>\n        <button class="btn" onclick="layoutMonitors()">Tile Wndws</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Voice</h3>\n      <div class="btn-row">\n        <button class="btn success" onclick="voiceToggle(true)">Start</button>\n        <button class="btn danger" onclick="voiceToggle(false)">Stop</button>\n      </div>\n      <div id="voice-status" style="font-size:11px;color:#666">Inactive</div>\n    </div>\n\n    <div class="tool-group">\n      <h3> AI Launch</h3>\n      <input type="text" id="launch-query" placeholder="open chrome to reddit">\n      <div class="btn-row">\n        <button class="btn" onclick="aiLaunch()">Launch</button>\n      </div>\n    </div>\n  </div>\n\n  <div id="screenshot-container">\n    <img id="screen-img" src="/screen" alt="Screen">\n    <div class="coord-overlay" id="coord-overlay">Click to get coords</div>\n  </div>\n\n  <div class="panel" id="right-panel">\n    <h2>Action Log</h2>\n    <div id="action-log">\n      <div class="action-entry"><span>Ready</span><span class="action-time">now</span></div>\n    </div>\n    <div style="margin-top:8px">\n      <button class="btn" onclick="clearLog()" style="width:100%">Clear</button>\n    </div>\n  </div>\n</div>\n\n<script>\nconst BASE = \'\';\nlet logCount = 0;\nfunction toast(msg){const t=document.getElementById(\'toast\');t.textContent=msg;t.style.display=\'block\';setTimeout(()=>t.style.display=\'none\',2000)}\nfunction api(method,path,body,cb){\n  const opts={method,headers:{\'Content-Type\':\'application/json\'}};\n  if(body)opts.body=JSON.stringify(body);\n  fetch(BASE+path,opts).then(r=>r.json()).then(d=>{if(cb)cb(d)}).catch(e=>toast(\'Error: \'+e.message));\n}\nfunction addLog(text){\n  logCount++;\n  const el=document.getElementById(\'action-log\');\n  const d=new Date();\n  el.innerHTML=`<div class="action-entry"><span>${text}</span><span class="action-time">${d.getHours().toString().padStart(2,\'0\')}:${d.getMinutes().toString().padStart(2,\'0\')}:${d.getSeconds().toString().padStart(2,\'0\')}</span></div>`+el.innerHTML;\n  if(logCount>100){el.lastChild.remove();logCount--}\n}\nfunction clearLog(){document.getElementById(\'action-log\').innerHTML=\'\';logCount=0;addLog(\'Cleared\')}\n\n// Mouse\nfunction mouseMove(){const x=document.getElementById(\'mx\').value,y=document.getElementById(\'my\').value;api(\'POST\',\'/mouse/move\',{x:parseInt(x),y:parseInt(y)},d=>addLog(\'Moved to \'+x+\',\'+y))}\nfunction mouseClick(b){api(\'POST\',\'/mouse/click\',{button:b},d=>addLog(\'Clicked \'+b))}\nfunction mouseDClick(){api(\'POST\',\'/mouse/doubleclick\',{},d=>addLog(\'Double clicked\'))}\n\n// Keyboard\nfunction keyType(){const t=document.getElementById(\'type-text\').value;api(\'POST\',\'/key/type\',{text:t},d=>addLog(\'Typed: \'+t.substring(0,30)+(t.length>30?\'...\':\'\')))}\nfunction keyPress(keys){api(\'POST\',\'/key/press\',{keys},d=>addLog(\'Pressed: \'+keys.join(\'+\'))})}\n\n// Emergency\nfunction emergency(a){api(\'POST\',\'/emergency/\'+a,{},d=>{addLog(\'Emergency: \'+a);document.getElementById(\'status-text\').textContent=a===\'stop\'?\'STOPPED\':\'Connected\';document.getElementById(\'status-bar\').innerHTML=(a===\'stop\'?\'<span class="status-dot dot-red"></span>\':\'<span class="status-dot dot-green"></span>\')+document.getElementById(\'status-text\').textContent})}\n\n// Find\nfunction ocrFind(){const t=document.getElementById(\'find-text\').value;if(!t)return;api(\'POST\',\'/ocr/find\',{text:t},d=>{if(d.found){addLog(\'Found: \'+t+\' at \'+JSON.stringify(d.matches[0].center));toast(\'Found at \'+d.matches[0].center)}else{addLog(\'Not found: \'+t);toast(\'Not found\')}})}\nfunction cursorPos(){api(\'GET\',\'/cursor/pos\',null,d=>{document.getElementById(\'mx\').value=d.x;document.getElementById(\'my\').value=d.y;addLog(\'Cursor: \'+d.x+\',\'+d.y)})}\nfunction monitors(){api(\'GET\',\'/monitors\',null,d=>addLog(\'Monitors: \'+JSON.stringify(d.monitors)))}\n\n// Files\nfunction fileList(){const p=document.getElementById(\'file-path\').value;api(\'POST\',\'/file/list\',{path:p},d=>{if(d.items){addLog(\'Files in \'+d.path+\': \'+d.count+\' items\');toast(d.count+\' items\')}})}\nfunction appOpen(){const p=document.getElementById(\'file-path\').value;api(\'POST\',\'/app/open\',{path:p},d=>addLog(\'Opened: \'+p))}\n\n// Macros\nfunction macroList(){api(\'GET\',\'/macro/list\',null,d=>{if(d.macros){addLog(\'Macros: \'+d.macros.map(m=>m.name).join(\', \')||\'none\');toast(d.macros.length+\' macros\')}})}\nfunction macroRecord(){const n=document.getElementById(\'macro-name\').value;if(!n)return;api(\'POST\',\'/macro/record\',{name:n},d=>{addLog(\'Recording: \'+n+\'. Press F9 to stop.\');toast(\'Recording \'+n)})}\nfunction macroRun(){const n=document.getElementById(\'macro-name\').value;if(!n)return;api(\'POST\',\'/macro/run\',{name:n},d=>addLog(\'Ran macro: \'+n+\' (\'+d.executed+\'/\'+d.total+\')\'))}\n\n// V5.0 Power\nfunction power(a){api(\'POST\',\'/power/\'+a,{},d=>{addLog(\'Power: \'+a+\' - \'+(d.status||d.error||\'ok\'))})}\n\n// V5.0 Wallpaper\nfunction wpSet(){const f=document.getElementById(\'wp-folder\').value;api(\'POST\',\'/wallpaper/set\',{path:f},d=>addLog(\'WP: \'+(d.wallpaper||d.error)))}\nfunction wpCycle(){const f=document.getElementById(\'wp-folder\').value;api(\'POST\',\'/wallpaper/cycle\',{folder:f},d=>addLog(\'WP cycled: \'+(d.wallpaper||d.error)))}\nfunction wpRandom(){const f=document.getElementById(\'wp-folder\').value;api(\'POST\',\'/wallpaper/random\',{folder:f},d=>addLog(\'WP random: \'+(d.wallpaper||d.error)))}\n\n// V5.0 Search\nfunction searchFiles(){const pat=document.getElementById(\'search-pat\').value, p=document.getElementById(\'search-path\').value;api(\'POST\',\'/search/files\',{pattern:pat,path:p,limit:20},d=>{const el=document.getElementById(\'search-results\');if(d.matches){el.innerHTML=d.matches.map(m=>m.name+\' (\'+(m.size/1024).toFixed(0)+\'KB)\').join(\'<br>\');addLog(\'Search: \'+d.count+\' matches\')}else{el.innerHTML=d.error;addLog(\'Search error\')}})}\n\n// V5.0 Screen\nfunction cropScreen(){api(\'POST\',\'/crop\',{},d=>addLog(\'Crop: \'+(d.chars||\'0\')+\' chars copied\'))}\nfunction describeScreen(){api(\'GET\',\'/describe\',null,d=>addLog(\'Describe: \'+d.lines+\' lines found\'))}\nfunction layoutMonitors(){api(\'POST\',\'/monitors/layout\',{layout:\'grid\'},d=>addLog(\'Layout: \'+(d.windows_arranged||\'0\')+\' tiled\'))}\n\n// V5.0 Voice\nfunction voiceToggle(s){api(\'POST\',\'/voice/toggle\',{enable:s},d=>{document.getElementById(\'voice-status\').textContent=s?\'Active\':\'Inactive\';addLog(\'Voice: \'+(d.status||d.error||\'toggled\'))})}\n\n// V5.0 AI Launch\nfunction aiLaunch(){const q=document.getElementById(\'launch-query\').value;if(!q)return;api(\'POST\',\'/launch/ai\',{query:q},d=>addLog(\'Launch: \'+(d.app||d.error||\'ok\')))}\n\n// Tunnel\n\n// Screenshot click -> get coords\ndocument.getElementById(\'screen-img\').addEventListener(\'click\', function(e){\n  const rect = this.getBoundingClientRect();\n  const x = Math.round(e.clientX - rect.left);\n  const y = Math.round(e.clientY - rect.top);\n  const nw = this.naturalWidth||1920, nh = this.naturalHeight||1080;\n  const sx = this.width, sy = this.height;\n  const realX = Math.round(x * nw / sx);\n  const realY = Math.round(y * nh / sy);\n  document.getElementById(\'mx\').value = realX;\n  document.getElementById(\'my\').value = realY;\n  document.getElementById(\'coord-overlay\').textContent = realX+\',\'+realY;\n  toast(\'Screen coords: \'+realX+\',\'+realY);\n});\n\n// Auto-refresh screenshot every 2s\nsetInterval(()=>{\n  const img = document.getElementById(\'screen-img\');\n  img.src = \'/screenshot/fresh?\'+Date.now();\n}, 2000);\n\n// Auto-refresh action history every 3s\nsetInterval(()=>{\n  fetch(BASE+\'/history?limit=20\').then(r=>r.json()).then(d=>{\n    if(!d.actions||!d.actions.length)return;\n    const el=document.getElementById(\'action-log\');\n    let html=\'\';\n    for(let i=d.actions.length-1;i>=Math.max(0,d.actions.length-20);i--){\n      const a=d.actions[i];\n      const t=a.time?new Date(a.time).getHours().toString().padStart(2,\'0\')+\':\'+new Date(a.time).getMinutes().toString().padStart(2,\'0\')+\':\'+new Date(a.time).getSeconds().toString().padStart(2,\'0\'):\'\';\n      html+=`<div class="action-entry"><span>${a.type} ${JSON.stringify(a.data).substring(0,40)}</span><span class="action-time">${t}</span></div>`;\n    }\n    el.innerHTML=html;\n  }).catch(()=>{});\n}, 3000);\n</script>\n</body>\n</html>'

DASHBOARD2_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes CoAgent Dashboard 2</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0a0a0f;color:#ccc;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:18px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
h1{font-size:22px;margin:0;color:#eee;font-weight:600}
.tabs{display:flex;gap:8px;border-bottom:1px solid #333;margin-bottom:16px}
.tab{background:#1a1a3e;border:1px solid #333;border-bottom:0;color:#ccc;padding:10px 14px;cursor:pointer}
.tab:hover,.btn:hover{background:#2a2a5e}
.tab.active{border-bottom:3px solid #444;color:#fff}
.tab-panel{display:none;background:#111122;border:1px solid #333;padding:14px}
.tab-panel.active{display:block}
.row{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.btn,button{background:#1a1a3e;border:1px solid #333;color:#ccc;padding:8px 12px;cursor:pointer;border-radius:4px}
input[type=text]{background:#1a1a2e;border:1px solid #333;color:#ccc;padding:9px 10px;min-width:320px}
textarea{border-radius:4px;padding:10px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border:1px solid #333;padding:8px;text-align:left;vertical-align:top}
th{background:#0e0e1a;color:#eee}
tr{background:#111122}
.status{color:#888;margin-top:8px;min-height:22px}
.image-panel{background:#0a0a0f;border:1px solid #333;padding:10px;text-align:center;margin-bottom:12px}
#som-img{display:block;margin:0 auto;max-height:680px;object-fit:contain}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>Hermes CoAgent</h1>
    <div class="status" id="global-status">Ready</div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="som">SOM View</button>
    <button class="tab" data-tab="uia">UIA Tree</button>
    <button class="tab" data-tab="find">Find and Click</button>
  </div>
  <section id="tab-som" class="tab-panel active">
    <div class="row"><button class="btn" onclick="refreshSom()">Refresh</button><span id="som-status" class="status"></span></div>
    <div class="image-panel"><img id="som-img" src="/som/screenshot" style="max-width:100%" alt="SOM screenshot"></div>
    <div id="som-elements" class="status">Loading SOM elements...</div>
  </section>
  <section id="tab-uia" class="tab-panel">
    <div class="row"><button class="btn" onclick="refreshUia()">Refresh</button><span id="uia-status" class="status"></span></div>
    <textarea id="uia-tree" style="width:100%;height:600px;font-family:monospace;background:#1a1a2e;color:#ccc;border:1px solid #333"></textarea>
  </section>
  <section id="tab-find" class="tab-panel">
    <div class="row">
      <input id="find-name" type="text" placeholder="Element name">
      <button class="btn" onclick="findElements()">Find</button>
      <span id="find-status" class="status"></span>
    </div>
    <div id="find-results"></div>
  </section>
</div>
<script>
function hideAllTabs(){document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'))}
function showTab(name){hideAllTabs();document.getElementById('tab-'+name).classList.add('active');document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name))}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>showTab(t.dataset.tab)))
function status(id,msg){document.getElementById(id).textContent=msg;document.getElementById('global-status').textContent=msg}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function centerOf(e){if(Array.isArray(e.center))return e.center.join(', ');const r=e.rect;if(r)return (r.left+Math.round(r.width/2))+', '+(r.top+Math.round(r.height/2));return ''}
async function fetchJson(url,opts){
  const res=await fetch(url,opts)
  const text=await res.text()
  let data={}
  try{data=text?JSON.parse(text):{}}catch(e){throw new Error('Invalid JSON from '+url)}
  if(!res.ok)throw new Error(data.error||res.statusText)
  return data
}
async function postJson(url,body){return fetchJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}
function renderSomElements(elements){
  const host=document.getElementById('som-elements')
  if(!elements.length){host.innerHTML='<div class="status">No elements found</div>';return}
  host.innerHTML='<table><thead><tr><th>Index</th><th>Name</th><th>Control Type</th><th>Center coords</th><th>Action</th></tr></thead><tbody>'+
    elements.map(e=>`<tr><td>${esc(e.index)}</td><td>${esc(e.name)}</td><td>${esc(e.control_type)}</td><td>${esc(centerOf(e))}</td><td><button class="som-click" data-index="${esc(e.index)}">Click #${esc(e.index)}</button></td></tr>`).join('')+
    '</tbody></table>'
  host.querySelectorAll('.som-click').forEach(b=>b.addEventListener('click',()=>clickSom(Number(b.dataset.index))))
}
async function refreshSom(){
  try{
    status('som-status','Loading SOM...')
    const data=await fetchJson('/som/screenshot?cache='+Math.random())
    if(!data.success)throw new Error(data.error||'SOM failed')
    if(data.labeled_screenshot)document.getElementById('som-img').src='data:image/png;base64,'+data.labeled_screenshot
    renderSomElements(data.elements||[])
    status('som-status','Loaded '+(data.elements||[]).length+' elements')
  }catch(e){status('som-status','Error: '+e.message);document.getElementById('som-elements').innerHTML='<div class="status">'+esc(e.message)+'</div>'}
}
async function refreshUia(){
  try{
    status('uia-status','Loading UIA snapshot...')
    const data=await fetchJson('/uia/snapshot?cache='+Date.now())
    document.getElementById('uia-tree').value=JSON.stringify(data,null,2)
    status('uia-status','UIA snapshot loaded')
  }catch(e){status('uia-status','Error: '+e.message);document.getElementById('uia-tree').value=e.stack||e.message}
}
function renderFindResults(results){
  const host=document.getElementById('find-results')
  if(!results.length){host.innerHTML='';return}
  host.innerHTML='<table><thead><tr><th>Index</th><th>Name</th><th>Control Type</th><th>Center</th><th>Action</th></tr></thead><tbody>'+
    results.map((r,i)=>`<tr><td>${i+1}</td><td>${esc(r.name)}</td><td>${esc(r.control_type)}</td><td>${esc(centerOf(r))}</td><td><button class="name-click" data-name="${esc(r.name)}">Click</button></td></tr>`).join('')+
    '</tbody></table>'
  host.querySelectorAll('.name-click').forEach(b=>b.addEventListener('click',()=>clickName(b.dataset.name)))
}
async function findElements(){
  const term=document.getElementById('find-name').value.trim()
  if(!term){status('find-status','Enter an element name');return}
  try{
    status('find-status','Searching...')
    const data=await fetchJson('/uia/find/'+encodeURIComponent(term))
    const results=data.results||[]
    renderFindResults(results)
    status('find-status',results.length?'Found '+results.length+' elements':'Not found')
  }catch(e){status('find-status','Error: '+e.message);document.getElementById('find-results').innerHTML=''}
}
async function clickSom(index){
  try{status('som-status','Clicking #'+index+'...');await postJson('/uia/click',{index:index});status('som-status','Clicked #'+index)}
  catch(e){status('som-status','Click failed: '+e.message)}
}
async function clickName(name){
  try{status('find-status','Clicking '+name+'...');await postJson('/uia/click',{name:name});status('find-status','Clicked '+name)}
  catch(e){status('find-status','Click failed: '+e.message)}
}
document.getElementById('find-name').addEventListener('keydown',e=>{if(e.key==='Enter')findElements()})
refreshSom()
refreshUia()
// Auth status check
fetch('/ping').then(r=>r.json()).then(d=>{
  const badge=document.getElementById('auth-badge');
  if(badge)badge.textContent='';
}).catch(()=>{})
// Version info
fetch('/').then(()=>{
  const el=document.createElement('div');
  el.style.cssText='position:fixed;bottom:4px;right:8px;font-size:10px;color:#444;z-index:999';
  el.textContent='Hermes CoAgent v3.0 — MIT License';
  document.body.appendChild(el);
}).catch(()=>{})
</script>
</body>
</html>"""

# =========== WEB DASHBOARD ===========
@app.route("/")
def dashboard():
    return DASHBOARD_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/dashboard2")
def dashboard2():
    return DASHBOARD2_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

# =========== REST API ROUTES ===========
@app.route("/ping")
def route_ping():
    return jsonify({
        "status": "ok", "agent": "Hermes CoAgent v6.1",
        "mode": "copilot", "emergency_stop": state.emergency_stop,
        "queue_size": state.pending_queue.qsize(),
        "actions_today": len(state.action_history),
        "watchdog": state.watchdog_running,
        "recorder": state.recorder_active
    })

@app.route("/cursor/pos")
def route_cursor():
    x, y = pyautogui.position()
    return jsonify({"x": x, "y": y})

@app.route("/mouse/move", methods=["POST"])
def route_mouse_move():
    d = request.json
    _execute_action({"type": "move", "data": d})
    return jsonify({"status": "moved", "x": d["x"], "y": d["y"]})

@app.route("/mouse/click", methods=["POST"])
def route_mouse_click():
    d = request.json or {}
    _execute_action({"type": "click", "data": d})
    return jsonify({"status": "clicked", "button": d.get("button", "left")})

@app.route("/copilot/mode")
def route_copilot_mode():
    """Get current co-pilot mode (background vs foreground input)."""
    return jsonify({
        "background_input": HAS_SENDINPUT,
        "available": True,
        "description": "background" if HAS_SENDINPUT else "foreground (pyautogui)",
        "info": "Co-pilot mode uses SendInput/mouse_event — no focus steal, you keep control"
    })

@app.route("/mouse/doubleclick", methods=["POST"])
def route_mouse_dclick():
    d = request.json or {}
    _execute_action({"type": "doubleclick", "data": d})
    return jsonify({"status": "double_clicked"})

@app.route("/mouse/rightclick", methods=["POST"])
def route_mouse_rclick():
    d = request.json or {}
    _execute_action({"type": "rightclick", "data": d})
    return jsonify({"status": "right_clicked"})

@app.route("/mouse/drag", methods=["POST"])
def route_mouse_drag():
    d = request.json
    _execute_action({"type": "drag", "data": d})
    return jsonify({"status": "dragged"})

@app.route("/mouse/scroll", methods=["POST"])
def route_mouse_scroll():
    d = request.json or {}
    _execute_action({"type": "scroll", "data": d})
    return jsonify({"status": "scrolled"})

@app.route("/key/type", methods=["POST"])
def route_key_type():
    d = request.json
    _execute_action({"type": "type", "data": d})
    return jsonify({"status": "typed", "chars": len(d.get("text",""))})

@app.route("/key/press", methods=["POST"])
def route_key_press():
    d = request.json
    _execute_action({"type": "hotkey", "data": d})
    return jsonify({"status": "pressed", "keys": d.get("keys",[])})

@app.route("/minimize", methods=["POST"])
def route_minimize():
    """Minimize all windows on Session 1 (interactive desktop).
    Works from Session 0 by using schtasks with InteractiveToken."""
    ok1 = _send_keys_session1("win,d")
    time.sleep(0.3)
    ok2 = _send_keys_session1("win,m")
    return jsonify({
        "win_d": ok1,
        "win_m": ok2,
        "status": "minimized" if ok1 or ok2 else "failed"
    })

@app.route("/click/session1", methods=["POST"])
def route_click_session1():
    """Click at coordinates on Session 1 via schtasks.
    Required: {"x": int, "y": int}"""
    d = request.json
    x = int(d.get("x", 960))
    y = int(d.get("y", 540))
    
    # Coerce to safe integers — prevent script injection
    if not (-99999 <= x <= 99999 and -99999 <= y <= 99999):
        return jsonify({"error": "Coordinates out of range"}), 400
    
    click_ps1 = COAGENT_DIR / "_click_s1.ps1"
    click_ps1.write_text(f'''Add-Type @"
using System;
using System.Runtime.InteropServices;
public class M {{
    [DllImport("user32.dll")]
    public static extern void SetCursorPos(int x, int y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}}
"@
[M]::SetCursorPos({x}, {y})
Start-Sleep -Milliseconds 50
[M]::mouse_event(0x02, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 30
[M]::mouse_event(0x04, 0, 0, 0, [UIntPtr]::Zero)
Write-Output "Clicked {x},{y}"
''')
    
    task_name = "HermesCoAgent_Clk"
    subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                   capture_output=True, timeout=5)
    
    xml_path = COAGENT_DIR / "_clk_task.xml"
    xml = _interactive_task_xml(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        '-ExecutionPolicy Bypass -WindowStyle Hidden -File "' + str(click_ps1) + '"',
    )
    xml_path.write_text(xml, encoding="utf-16")
    
    r1 = subprocess.run(
        ["schtasks", "/Create", "/XML", str(xml_path), "/TN", task_name, "/F"],
        capture_output=True, text=True, timeout=10
    )
    if r1.returncode == 0:
        subprocess.run(
            ["schtasks", "/Run", "/TN", task_name],
            capture_output=True, text=True, timeout=15
        )
    try:
        xml_path.unlink()
        click_ps1.unlink()
    except:
        pass
    return jsonify({"x": x, "y": y, "status": "clicked" if r1.returncode == 0 else "failed"})


# === CHAIN ===
@app.route("/chain", methods=["POST"])
def route_chain():
    data = request.json
    actions = data.get("actions", [])
    results = []
    for i, action in enumerate(actions):
        try:
            _execute_action(action)
            results.append({"index": i, "status": "ok", "type": action.get("type")})
        except Exception as e:
            results.append({"index": i, "status": "error", "error": str(e)})
            break
    return jsonify({"executed": len(results), "total": len(actions), "results": results})

# === ACT + SNAP ===
@app.route("/act", methods=["POST"])
def route_act_snap():
    data = request.json
    action = data.get("action", {})
    before = _grab_screen_bytes(force=True)
    try:
        _execute_action(action)
        result = {"status": "ok", "type": action.get("type")}
    except Exception as e:
        result = {"status": "error", "error": str(e)}
    after = _grab_screen_bytes(force=True)
    return jsonify({
        "result": result,
        "before": base64.b64encode(before).decode(),
        "after": base64.b64encode(after).decode(),
        "before_size": len(before), "after_size": len(after)
    })

# === SCREENSHOTS ===
@app.route("/screen")
@app.route("/screenshot/cached")
def route_screen_cached():
    try:
        return send_file(BytesIO(_grab_screen_bytes(force=False)), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/screen/jpeg")
@app.route("/screenshot/jpeg")
def route_screen_jpeg():
    """Return screenshot as JPEG (smaller, faster transfer)."""
    try:
        img_bytes = _capture_via_session1(fmt="jpeg")
        return send_file(BytesIO(img_bytes), mimetype="image/jpeg")
    except Exception as e:
        try:
            # Fallback: convert cached PNG to JPEG
            buf = BytesIO()
            from PIL import Image
            img = Image.open(BytesIO(_grab_screen_bytes(force=False)))
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85, optimize=True)
            buf.seek(0)
            return send_file(buf, mimetype="image/jpeg")
        except Exception as e2:
            return jsonify({"error": str(e2)}), 500

@app.route("/screenshot/fresh")
@app.route("/screenshot/force")
def route_screen_fresh():
    try:
        return send_file(BytesIO(_grab_screen_bytes(force=True)), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/screen/base64")
@app.route("/screenshot/base64")
def route_screen_b64():
    try:
        b = _grab_screen_bytes(force=False)
        return jsonify({"data": base64.b64encode(b).decode(), "size": len(b)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/screen/diagnose")
def route_screen_diag():
    return jsonify({
        "session_id": os.environ.get("SESSIONNAME", "none"),
        "username": os.environ.get("USERNAME", "unknown"),
        "pid": os.getpid(),
        "python": sys.version
    })

# === EMERGENCY ===
@app.route("/emergency/stop", methods=["POST"])
def route_emergency_stop():
    state.emergency_stop = True
    with state.pending_queue.mutex:
        state.pending_queue.queue.clear()
    return jsonify({"status": "stopped", "message": "All input blocked"})

@app.route("/emergency/resume", methods=["POST"])
def route_emergency_resume():
    state.emergency_stop = False
    return jsonify({"status": "resumed", "message": "Input re-enabled"})

@app.route("/emergency/restart", methods=["POST"])
def route_emergency_restart():
    launcher = COAGENT_DIR / "start_coagent.bat"
    if not launcher.exists():
        return jsonify({"error": f"Launcher not found: {launcher}"}), 500

    def _restart_from_launcher():
        time.sleep(0.5)
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", "/min", str(launcher)],
            cwd=str(COAGENT_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    threading.Thread(target=_restart_from_launcher, daemon=True).start()
    return jsonify({"status": "restarting", "launcher": str(launcher)})

@app.route("/emergency/status")
def route_emergency_status():
    return jsonify({
        "emergency_stop": state.emergency_stop,
        "input_locked": state.input_lock.locked(),
        "queue_size": state.pending_queue.qsize(),
        "actions_today": len(state.action_history),
        "watchdog": state.watchdog_running
    })

# === HISTORY ===
@app.route("/history")
def route_history():
    limit = _limit_arg("limit", 50, 500)
    with state.input_lock:
        total = len(state.action_history)
        actions = [] if limit == 0 else list(state.action_history[-limit:])
    return jsonify({"actions": actions, "total": total})

@app.route("/replay", methods=["POST"])
def route_replay():
    d = request.json or {}
    count = min(d.get("count", 5), 50)
    results = []
    for action in state.action_history[-count:]:
        try:
            _execute_action(action)
            results.append({"status": "ok", "type": action["type"]})
        except Exception as e:
            results.append({"status": "error", "error": str(e)})
    return jsonify({"replayed": len(results), "results": results})

# === WINDOWS ===
@app.route("/windows")
def route_windows():
    return jsonify(list_windows_api())

@app.route("/windows/activate", methods=["POST"])
def route_win_activate():
    d = request.json
    return jsonify(activate_window_api(d["title"]))

# === CLIPBOARD ===
@app.route("/clipboard/get")
def route_clip_get():
    return jsonify(clipboard_get_api())

@app.route("/clipboard/set", methods=["POST"])
def route_clip_set():
    d = request.json
    return jsonify(clipboard_set_api(d["text"]))

# === APP ===
@app.route("/app/open", methods=["POST"])
@require_auth
def route_app_open():
    d = request.json
    result = _launch_app_safe(d["path"])
    return jsonify(result)

@app.route("/app/run", methods=["POST"])
@require_auth
def route_app_run():
    d = request.json
    return jsonify(run_command_api(d["cmd"], d.get("timeout", 30)))

# === MONITORS ===
@app.route("/monitors")
@require_auth
def route_monitors():
    return jsonify(monitors_api())

# === OCR ===
@app.route("/ocr/find", methods=["POST"])
@require_auth
def route_ocr():
    d = request.json
    return jsonify(ocr_find_text(d["text"], d.get("region")))

# === VISUAL SEARCH ===
@app.route("/visual/find", methods=["POST"])
@require_auth
def route_visual():
    d = request.json
    return jsonify(visual_find_image(d["template_path"], d.get("confidence", 0.8)))

# === FILES ===
@app.route("/file/list", methods=["POST"])
@require_auth
def route_file_list():
    d = request.json
    p = d.get("path", ".")
    try:
        p = _sanitize_path(p)
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(file_list_api(p))

@app.route("/file/read", methods=["POST"])
@require_auth
def route_file_read():
    d = request.json
    try:
        p = _sanitize_path(d["path"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(file_read_api(p))

@app.route("/file/write", methods=["POST"])
@require_auth
def route_file_write():
    d = request.json
    try:
        p = _sanitize_path(d["path"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(file_write_api(p, d["content"], d.get("is_base64", False)))

@app.route("/file/delete", methods=["POST"])
@require_auth
def route_file_delete():
    d = request.json
    try:
        p = _sanitize_path(d["path"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(file_delete_api(p))

# === TTS ===
@app.route("/tts/speak", methods=["POST"])
@require_auth
def route_tts():
    d = request.json
    return jsonify(tts_speak_api(d["text"]))

# === TUNNEL ===
@app.route("/tunnel/start", methods=["POST"])
@require_auth
def route_tunnel_start():
    return jsonify(tunnel_start_action())

@app.route("/tunnel/stop", methods=["POST"])
@require_auth
def route_tunnel_stop():
    return jsonify(tunnel_stop_action())

@app.route("/tunnel/status")
def route_tunnel_status():
    return jsonify(tunnel_status_action())

# === MACROS ===
@app.route("/macro/list")
@app.route("/macros")
def route_macro_list():
    return jsonify(macro_list_api())

@app.route("/macro/save", methods=["POST"])
def route_macro_save():
    d = request.json
    return jsonify(macro_save_api(d["name"], d.get("actions", [])))

@app.route("/macro/run", methods=["POST"])
def route_macro_run():
    d = request.json
    return jsonify(macro_run_api(d["name"]))

@app.route("/macro/record", methods=["POST"])
def route_macro_record():
    d = request.json
    return jsonify(macro_record_api(d["name"]))

@app.route("/macro/delete", methods=["POST"])
@require_auth
def route_macro_delete():
    d = request.json
    p = MACROS_DIR / f"{d['name']}.json"
    if p.exists():
        p.unlink()
        return jsonify({"status": "deleted", "name": d["name"]})
    return jsonify({"error": "Not found"}), 404

# === UIA ENGINE ROUTES ===
@app.route("/uia/snapshot")
@app.route("/uia/tree")
def route_uia_snapshot():
    """Get full accessibility tree of all windows and elements.
    Tries Session 1 relay first, falls back to Session 0 UIA."""
    try:
        # Try Session 1 relay first (has real desktop)
        req = urllib.request.Request(f"http://{HOST_IP}:{TRAY_PORT}/uia/tree")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            if data and "windows" in data and data.get("count", 0) > 0:
                data["source"] = "session1_relay"
                return jsonify(data)
    except:
        pass
    # Fallback to Session 0 UIA
    ue = _get_uia_engine()
    result = ue.uia_snapshot()
    if isinstance(result, dict):
        result["source"] = "session0"
    return jsonify(result)

@app.route("/uia/find/<path:name>")
def route_uia_find(name):
    """Find UI elements by name substring (deep search)."""
    ue = _get_uia_engine()
    return jsonify({"results": ue.uia_find_deep(name)})

@app.route("/uia/click", methods=["POST"])
def route_uia_click():
    """Click a UI element by index (int) or name (str)."""
    d = request.json
    target = d.get("target", d.get("index", d.get("name", 0)))
    ue = _get_uia_engine()
    result = ue.uia_click_element(target)
    if result.get("success"):
        return jsonify(result)
    return jsonify(result), 404

@app.route("/som/screenshot")
def route_som_screenshot():
    """Screenshot with numbered SOM overlays on every interactable element.
    Supports ?force=1 to bypass diffing cache.
    Uses pixel hash to skip full reconstruction on unchanged screens (v5.1)."""
    ue = _get_uia_engine()
    
    # v5.1: SOM diffing cache — check if screen has changed
    force = request.args.get("force", "") == "1" if hasattr(request, 'args') else False
    if not force:
        try:
            from PIL import Image as _PILImg
            raw = _grab_screen_bytes(force=True)
            img = _PILImg.open(BytesIO(raw))
            small = img.resize((10, 10)).tobytes()
            h = hash(small)
            now = time.time()
            if _SOM_CACHE and _SOM_CACHE.get("hash") == h and (now - _SOM_CACHE.get("ts", 0)) < 2.0:
                return jsonify(_SOM_CACHE["result"])
        except:
            pass
    
    try:
        screen_bytes = _grab_screen_bytes(force=True)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as ex:
            fut = ex.submit(ue.som_overlay, screen_bytes)
            result = fut.result(timeout=10)
        if result.get("success"):
            # Update cache
            try:
                img = _PILImg.open(BytesIO(screen_bytes))
                _SOM_CACHE["hash"] = hash(img.resize((10, 10)).tobytes())
            except:
                pass
            _SOM_CACHE["ts"] = time.time()
            _SOM_CACHE["result"] = result
            return jsonify(result)
        return jsonify({"success": False, "error": result.get("error", "SOM failed")})
    except concurrent.futures.TimeoutError:
        return jsonify({"success": False, "error": "SOM timed out (UIA unavailable for this session)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/som/image")
def route_som_image():
    """SOM labeled screenshot as a raw PNG image."""
    ue = _get_uia_engine()
    try:
        from io import BytesIO
        import base64, concurrent.futures
        screen_bytes = _grab_screen_bytes(force=True)
        with concurrent.futures.ThreadPoolExecutor() as ex:
            fut = ex.submit(ue.som_overlay, screen_bytes)
            result = fut.result(timeout=10)
        if result.get("success"):
            from PIL import Image
            img_data = base64.b64decode(result["labeled_screenshot"])
            return send_file(BytesIO(img_data), mimetype="image/png")
        # Fallback: return raw screenshot if SOM failed
        return send_file(BytesIO(screen_bytes), mimetype="image/png")
    except concurrent.futures.TimeoutError:
        # Return raw screenshot
        return send_file(BytesIO(_grab_screen_bytes(force=True)), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/uia/find-combined", methods=["POST"])
def route_find_combined():
    """Find element by text using both UIA and OCR, return coordinates."""
    d = request.json
    text = d.get("text", "")
    ue = _get_uia_engine()
    return jsonify(ue.find_on_screen(text))

@app.route("/input/send", methods=["POST"])
def route_input_send():
    """Send keystrokes in background (doesn't steal focus)."""
    d = request.json
    keys = d.get("keys", d.get("text", "").split())
    ue = _get_uia_engine()
    return jsonify(ue.send_input_background(keys))

@app.route("/uia/diag")
def route_uia_diag():
    """Check UIA availability and basic functionality."""
    ue = _get_uia_engine()
    return jsonify(ue.diag())

# ════════════════════════════════════════════════════════════════
# v5.1 SOM/UIA IMPROVEMENTS: Diff cache, Bridging, Per-window,
# Accelerated Regions, Element Tracking, Clear Cache
# ════════════════════════════════════════════════════════════════

_SOM_CACHE = {}  # {"hash": <pixel_hash>, "result": <json>, "ts": <time>}

@app.route("/som/cache/clear")
def route_som_cache_clear():
    """Clear SOM diffing cache."""
    _SOM_CACHE.clear()
    return jsonify({"status": "cache_cleared"})

@app.route("/som/bridge")
def route_som_bridge():
    """SOM overlay with UIA cross-referencing (v5.1)."""
    ue = _get_uia_engine()
    try:
        screen_bytes = _grab_screen_bytes(force=True)
        result = ue.uia_som_bridge(screen_bytes)
        if result.get("success"):
            return jsonify(result)
        return jsonify({"success": False, "error": result.get("error", "SOM bridge failed")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/som/per-window")
def route_som_per_window():
    """Per-window SOM snapshots (v5.1). Body: {window_title: 'Telegram'} or empty for all windows."""
    ue = _get_uia_engine()
    d = request.json or {}
    window_title = d.get("window_title", None) if hasattr(request, 'json') and request.json else None
    result = ue.per_window_som(window_title)
    return jsonify(result)

@app.route("/som/point", methods=["POST"])
def route_som_point():
    """Find the UIA element at pixel coordinates (v5.1). Body: {x: 100, y: 200}"""
    ue = _get_uia_engine()
    d = request.json or {}
    x = d.get("x", 0)
    y = d.get("y", 0)
    result = ue.find_element_by_center(x, y)
    if result:
        return jsonify({"success": True, "element": result})
    return jsonify({"success": False, "error": "No element found at that point"}), 404

@app.route("/uia/accelerated-regions")
def route_uia_accelerated():
    """Get information about accelerated regions (v5.1)."""
    ue = _get_uia_engine()
    regions = ue._get_cold_regions() if hasattr(ue, '_get_cold_regions') else []
    return jsonify({
        "cold_regions": regions,
        "region_count": len(regions),
        "total_tracked": len(ue._ACCEL_REGIONS) if hasattr(ue, '_ACCEL_REGIONS') else 0
    })


# ════════════════════════════════════════════════════════════════
# V5.0 NEW FEATURES: Power, Scheduler, Search, Wallpaper, Crop,
# Describe, Monitor Layout, File Search, Voice, AI Launch
# ════════════════════════════════════════════════════════════════

# ── POWER MANAGEMENT ──────────────────────────────────────────

@app.route("/power/sleep", methods=["POST"])
def route_power_sleep():
    """Put PC to sleep."""
    try:
        import ctypes
        ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
        return jsonify({"status": "sleeping"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/power/shutdown", methods=["POST"])
def route_power_shutdown():
    """Shutdown PC. Body: {timeout: 30} (seconds)."""
    d = request.json or {}
    t = d.get("timeout", 30)
    subprocess.run(["shutdown", "/s", "/t", str(t)], capture_output=True)
    return jsonify({"status": "shutdown_scheduled", "timeout": t})

@app.route("/power/restart", methods=["POST"])
def route_power_restart():
    """Restart PC."""
    t = (request.json or {}).get("timeout", 30)
    subprocess.run(["shutdown", "/r", "/t", str(t)], capture_output=True)
    return jsonify({"status": "restart_scheduled", "timeout": t})

@app.route("/power/lock", methods=["POST"])
def route_power_lock():
    """Lock the workstation."""
    ctypes.windll.user32.LockWorkStation()
    return jsonify({"status": "locked"})

@app.route("/power/cancel", methods=["POST"])
def route_power_cancel():
    """Cancel pending shutdown/restart."""
    subprocess.run(["shutdown", "/a"], capture_output=True)
    return jsonify({"status": "cancelled"})

# ── WALLPAPER CONTROL ─────────────────────────────────────────

@app.route("/wallpaper/set", methods=["POST"])
def route_wallpaper_set():
    """Set desktop wallpaper. Body: {path: "C:/img.jpg"}"""
    d = request.json or {}
    img_path = d.get("path", "")
    if not os.path.isfile(img_path):
        return jsonify({"error": "File not found"}), 404
    abs_path = os.path.abspath(img_path)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, abs_path, 2)
    _log(f"Wallpaper set to {abs_path}")
    return jsonify({"status": "ok", "wallpaper": abs_path})

@app.route("/wallpaper/cycle", methods=["POST"])
def route_wallpaper_cycle():
    """Cycle through wallpapers in a folder."""
    d = request.json or {}
    folder = d.get("folder", "")
    if not os.path.isdir(folder):
        return jsonify({"error": "Folder not found"}), 404
    exts = ('.jpg','.jpeg','.png','.bmp','.gif')
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    if not files:
        return jsonify({"error": "No image files found"}), 404
    files.sort()
    state_file = COAGENT_DIR / "wallpaper_state.json"
    idx = 0
    if state_file.exists():
        try:
            import json as _jj
            state = _jj.loads(state_file.read_text())
            idx = state.get("index", 0)
        except:
            pass
    idx = (idx + 1) % len(files)
    img = files[idx]
    ctypes.windll.user32.SystemParametersInfoW(20, 0, img, 2)
    state_file.write_text(json.dumps({"index": idx, "folder": folder}))
    _log(f"Wallpaper cycled to {os.path.basename(img)} ({idx+1}/{len(files)})")
    return jsonify({"status": "ok", "wallpaper": os.path.basename(img), "index": idx, "total": len(files)})

@app.route("/wallpaper/random", methods=["POST"])
def route_wallpaper_random():
    """Set random wallpaper from a folder."""
    d = request.json or {}
    folder = d.get("folder", "")
    if not os.path.isdir(folder):
        return jsonify({"error": "Folder not found"}), 404
    import random as _rnd
    exts = ('.jpg','.jpeg','.png','.bmp','.gif')
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    if not files:
        return jsonify({"error": "No image files found"}), 404
    img = _rnd.choice(files)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, img, 2)
    _log(f"Wallpaper random set to {os.path.basename(img)}")
    return jsonify({"status": "ok", "wallpaper": os.path.basename(img)})

# ── FILE SEARCH ───────────────────────────────────────────────

@app.route("/search/files", methods=["POST"])
def route_search_files():
    """Search files by name/glob. Body: {pattern: "*.pdf", path: "C:/Users", limit: 50}"""
    import fnmatch
    d = request.json or {}
    pattern = d.get("pattern", "*")
    search_path = d.get("path", "C:\\")
    limit = min(d.get("limit", 50), 200)
    try:
        results = []
        for root, dirs, files in os.walk(search_path):
            try:
                for f in files:
                    if len(results) >= limit:
                        break
                    if fnmatch.fnmatch(f, pattern):
                        full = os.path.join(root, f)
                        try:
                            sz = os.path.getsize(full)
                        except:
                            sz = 0
                        results.append({"path": full, "name": f, "size": sz})
            except (PermissionError, OSError):
                continue
            if len(results) >= limit:
                break
        return jsonify({"matches": results, "count": len(results), "pattern": pattern, "path": search_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── SMART CROP / OCR ──────────────────────────────────────────

@app.route("/crop", methods=["POST"])
def route_crop():
    """Smart crop: OCR the whole screen, copy text to clipboard."""
    d = request.json or {}
    region = d.get("region")
    try:
        img = _capture_raw()
        if region:
            from PIL import Image
            pil = Image.open(BytesIO(img))
            pil = pil.crop((region[0], region[1], region[0]+region[2], region[1]+region[3]))
            buf = BytesIO()
            pil.save(buf, format="PNG")
            img = buf.getvalue()
        import pytesseract
        import pyperclip
        text = pytesseract.image_to_string(BytesIO(img))
        pyperclip.copy(text.strip())
        _log(f"Cropped text ({len(text)} chars) copied to clipboard")
        return jsonify({"status": "ok", "text": text.strip(), "chars": len(text.strip())})
    except ImportError:
        return jsonify({"error": "pytesseract not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── DESCRIBE SCREEN ───────────────────────────────────────────

@app.route("/describe", methods=["GET"])
def route_describe():
    """Describe current screen via OCR."""
    try:
        img = _capture_raw()
        import pytesseract
        text = pytesseract.image_to_string(BytesIO(img))
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return jsonify({
            "status": "ok",
            "description": "\n".join(lines[:100]),
            "lines": len(lines),
            "full_text": text
        })
    except ImportError:
        return jsonify({"error": "pytesseract not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── SCHEDULED ACTIONS ─────────────────────────────────────────

SCHEDULER_FILE = COAGENT_DIR / "scheduler.json"

def _load_scheduler():
    if SCHEDULER_FILE.exists():
        try:
            return json.loads(SCHEDULER_FILE.read_text())
        except:
            return {"actions": []}
    return {"actions": []}

def _save_scheduler(data):
    SCHEDULER_FILE.write_text(json.dumps(data, indent=2))

@app.route("/scheduler/list", methods=["GET"])
def route_scheduler_list():
    """List scheduled actions."""
    return jsonify(_load_scheduler())

@app.route("/scheduler/add", methods=["POST"])
def route_scheduler_add():
    """Add a scheduled action."""
    d = request.json or {}
    name = d.get("name", f"action_{int(time.time())}")
    cron = d.get("cron", "* * * * *")
    action = d.get("action", {})
    data = _load_scheduler()
    for a in data["actions"]:
        if a["name"] == name:
            a["cron"] = cron
            a["action"] = action
            a["updated"] = time.time()
            _save_scheduler(data)
            return jsonify({"status": "updated", "name": name})
    data["actions"].append({
        "name": name, "cron": cron, "action": action, "created": time.time()
    })
    _save_scheduler(data)
    _log(f"Scheduler: added '{name}' at {cron}")
    return jsonify({"status": "added", "name": name})

@app.route("/scheduler/remove", methods=["POST"])
def route_scheduler_remove():
    """Remove a scheduled action."""
    d = request.json or {}
    name = d.get("name", "")
    data = _load_scheduler()
    data["actions"] = [a for a in data["actions"] if a["name"] != name]
    _save_scheduler(data)
    _log(f"Scheduler: removed '{name}'")
    return jsonify({"status": "removed", "name": name})

@app.route("/scheduler/run", methods=["POST"])
def route_scheduler_run():
    """Run a scheduled action immediately."""
    d = request.json or {}
    name = d.get("name", "")
    data = _load_scheduler()
    for a in data["actions"]:
        if a["name"] == name:
            _execute_action_wrapper(a["action"])
            _log(f"Scheduler: ran '{name}'")
            return jsonify({"status": "executed", "name": name})
    return jsonify({"error": f"Action '{name}' not found"}), 404

# ── MONITOR LAYOUT ────────────────────────────────────────────

@app.route("/monitors/layout", methods=["POST"])
def route_monitor_layout():
    """Arrange windows across monitors in a grid."""
    d = request.json or {}
    layout = d.get("layout", "grid")
    try:
        import pygetwindow as gw
        wins = gw.getAllWindows()
        visible = [w for w in wins if w.visible and w.title and w.width > 100]
        if not visible:
            return jsonify({"error": "No visible windows found"}), 404
        num = len(visible)
        cols = int(num ** 0.5) + (1 if num ** 0.5 % 1 > 0 else 0)
        rows = (num + cols - 1) // cols
        try:
            screen_w, screen_h = pyautogui.size()
        except:
            screen_w, screen_h = 1920, 1080
        tile_w = screen_w // cols
        tile_h = screen_h // rows
        for i, w in enumerate(visible[:20]):
            col = i % cols
            row = i // cols
            try:
                w.moveTo(col * tile_w, row * tile_h)
                w.resizeTo(tile_w, tile_h)
            except:
                pass
        return jsonify({"status": "ok", "windows_arranged": len(visible[:20]), "grid": f"{cols}x{rows}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── VOICE CONTROL ─────────────────────────────────────────────

_voice_active = False
_voice_thread = None

@app.route("/voice/toggle", methods=["POST"])
def route_voice_toggle():
    """Toggle voice control on/off. Requires SpeechRecognition package."""
    global _voice_active, _voice_thread
    d = request.json or {}
    state = d.get("enable")
    if state is True:
        if _voice_active:
            return jsonify({"status": "already_active"})
        try:
            import speech_recognition as sr
        except ImportError:
            return jsonify({"error": "speech_recognition not installed"}), 500
        _voice_active = True
        _voice_thread = threading.Thread(target=_voice_loop, daemon=True)
        _voice_thread.start()
        _log("Voice control activated")
        return jsonify({"status": "activated"})
    elif state is False:
        _voice_active = False
        if _voice_thread:
            _voice_thread.join(timeout=2)
        _log("Voice control deactivated")
        return jsonify({"status": "deactivated"})
    return jsonify({"active": _voice_active})

def _voice_loop():
    """Background voice recognition loop."""
    import speech_recognition as sr
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source)
        while _voice_active:
            try:
                audio = r.listen(source, timeout=2, phrase_time_limit=5)
                text = r.recognize_google(audio).lower()
                _log(f"[Voice] Heard: {text}")
                if "click" in text:
                    nums = re.findall(r'\d+', text)
                    if len(nums) >= 2:
                        x, y = int(nums[0]), int(nums[1])
                        pyautogui.moveTo(x, y)
                        pyautogui.click()
                    elif "enter" in text:
                        pyautogui.press('enter')
                elif "type" in text:
                    words = text.replace("type", "").strip()
                    if words:
                        pyautogui.write(words)
                elif "scroll" in text:
                    pyautogui.scroll(-3)
                elif "stop" in text or "emergency" in text:
                    _emergency_stop()
            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                continue
            except Exception as e:
                _log(f"[Voice] Error: {e}")

# ── AI APP LAUNCHER ───────────────────────────────────────────

@app.route("/launch/ai", methods=["POST"])
def route_launch_ai():
    """Smart app launcher. Body: {query: 'open chrome'} or {app: 'chrome'}"""
    d = request.json or {}
    query = d.get("query", d.get("app", "")).lower()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    app_map = {
        "chrome": "chrome.exe", "google": "chrome.exe", "browser": "chrome.exe",
        "firefox": "firefox.exe", "edge": "msedge.exe",
        "notepad": "notepad.exe", "calculator": "calc.exe",
        "cmd": "cmd.exe", "terminal": "cmd.exe", "powershell": "powershell.exe",
        "word": "winword.exe", "excel": "excel.exe", "outlook": "outlook.exe",
        "vscode": "code.exe", "code": "code.exe",
        "telegram": "Telegram.exe", "discord": "Discord.exe",
        "explorer": "explorer.exe", "settings": "ms-settings:",
        "task manager": "taskmgr.exe", "paint": "mspaint.exe",
        "spotify": "Spotify.exe", "vlc": "vlc.exe", "steam": "steam.exe",
    }
    for key, exe in app_map.items():
        if key in query:
            try:
                if exe.startswith("ms-"):
                    subprocess.run(["start", exe], shell=True, capture_output=True)
                else:
                    # Safe: exe is from hardcoded map, not user input
                    subprocess.Popen([exe])
                _log(f"AI Launcher: '{query}' -> {exe}")
                return jsonify({"status": "launched", "app": exe, "query": query})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
    import webbrowser
    if re.match(r'^https?://', query):
        webbrowser.open_new_tab(query)
        return jsonify({"status": "launched", "app": "browser", "url": query})
    return jsonify({"error": f"Could not find app matching '{query}'"}), 404

# ════════════════════════════════════════════════════════════════
# END V5.0 NEW FEATURES
# ════════════════════════════════════════════════════════════════


# ── System Tray Icon ────────────────────────────────────────
def _start_tray():
    """Start system tray icon on the interactive desktop (Session 1).
    Uses schtasks with InteractiveToken logon type so the tray icon
    appears in the notification area even when the server runs in Session 0.
    Falls back silently."""

    try:
        tray_script = Path(__file__).parent / "tray_icon.py"
        if not tray_script.exists():
            _console("  [INFO] tray_icon.py not found, skip tray icon")
            return

        pyw = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"
        if not Path(pyw).exists():
            _console("  [INFO] Tray icon skipped: pythonw.exe not found")
            return

        task_name = "HermesCoAgent_Tray"

        with TRAY_LOG.open("a", encoding="utf-8") as tray_log:
            tray_log.write(f"{datetime.now().isoformat(timespec='seconds')} launching tray via schtasks...\n")
            tray_log.flush()

        subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                       capture_output=True, timeout=5)

        xml = _interactive_task_xml(
            pyw,
            '"' + str(tray_script) + '" ' + str(SERVER_PORT) + ' ' + str(TRAY_PORT),
            author="Admin",
            execution_limit="PT0S",
            working_dir=str(COAGENT_DIR),
        )

        xml_path = COAGENT_DIR / "_tray_task.xml"
        xml_path.write_text(xml, encoding="utf-16")

        result = subprocess.run(
            ["schtasks", "/Create", "/XML", str(xml_path), "/TN", task_name, "/F"],
            capture_output=True, text=True, timeout=10
        )

        with TRAY_LOG.open("a", encoding="utf-8") as tray_log:
            tray_log.write(f"schtasks create: {result.stdout.strip()} {result.stderr.strip()}\n")

        if result.returncode == 0:
            run_result = subprocess.run(
                ["schtasks", "/Run", "/TN", task_name],
                capture_output=True, text=True, timeout=10
            )
            with TRAY_LOG.open("a", encoding="utf-8") as tray_log:
                tray_log.write(f"schtasks run: {run_result.stdout.strip()} {run_result.stderr.strip()}\n")
            _console("  [OK] System Tray Icon launched on Session 1 via schtasks")
        else:
            _console("  [INFO] schtasks failed, fallback to direct subprocess")
            proc = subprocess.Popen(
                [pyw, str(tray_script), str(SERVER_PORT), str(TRAY_PORT)],
                cwd=str(COAGENT_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.75)
            if proc.poll() is None:
                _console(f"  [OK] System Tray Icon - PID {proc.pid}")
            else:
                _console(f"  [INFO] Tray icon exited early with code {proc.returncode}")

        try:
            xml_path.unlink()
        except:
            pass

    except Exception as e:
        _console(f"  [INFO] Tray icon skipped: {e}")

# =========== MAIN ===========
if __name__ == "__main__":
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), 9123))
    SERVER_PORT = port

    # Start queue worker
    t = threading.Thread(target=_queue_worker, daemon=True)
    t.start()

    # Start keyboard watchdog
    try:
        wt = threading.Thread(target=_keyboard_watchdog, daemon=True)
        wt.start()
        watchdog_ok = True
    except Exception as e:
        watchdog_ok = False
        _console(f"[v3] Watchdog not started: {e}")

    # Check MCP mode
    mcp_mode = "--mcp" in sys.argv

    # Auth setup
    _secure_mode = "--secure" in sys.argv
    _allow_external = "--allow-external" in sys.argv
    
    # Require auth for external access
    if _allow_external and not _secure_mode:
        _console("  [ERROR]      --allow-external requires --secure")
        _console("  [ERROR]      Refusing to start: would expose desktop to network without auth")
        _console("  [ERROR]      Add --secure or bind to 127.0.0.1 (omit --allow-external)")
        sys.exit(1)
    
    _token_arg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--token=")), None)
    if _secure_mode or _token_arg:
        try:
            from auth import init_auth, require_auth
            init_auth(port)
            import auth
            if auth.AUTH_ENABLED:
                _console(f"  [SECURITY]   Auth enabled — token: {auth.AUTH_TOKEN[:16]}...{auth.AUTH_TOKEN[-8:]}")
                _console("  [SECURITY]   Auth enabled — Bearer token required")
                # Global before_request for auth
                @app.before_request
                def _check_auth():
                    if request.path.startswith("/static") or request.path == "/health" or request.path.startswith("/emergency"):
                        return None
                    auth_header = request.headers.get("Authorization", "")
                    if not auth_header.startswith("Bearer "):
                        return jsonify({"error": "Unauthorized"}), 401
                    token = auth_header[7:]
                    if token != auth.AUTH_TOKEN:
                        return jsonify({"error": "Invalid token"}), 403
                    return None
            else:
                _console("  [WARNING]    No auth — desktop controllable by anyone on network")
        except Exception as e:
            _console(f"  [AUTH]       Auth module error: {e}")
            _console("  [WARNING]    No auth — desktop controllable by anyone on network")
    else:
        _console("  [WARNING]    No auth — desktop controllable by anyone on network")
    _console()

    _console()
    _console("  +" + "="*44 + "+")
    _console("  |         Hermes CoAgent v6.1              |")
    _console("  |      Ultimate Desktop Co-Pilot            |")
    _console("  +" + "="*44 + "+")
    _console()
    _console(f"  Mode:   {'MCP' if mcp_mode else 'HTTP REST + Web Dashboard'}")
    _console(f"  Port:   {port}")
    _console()
    _console("  V5.1 FEATURES:")
    _console("  [OK] UIA Element Tracking - Stable IDs across frames")
    _console("  [OK] SOM Diff Cache - Instant repeat SOMs (pixel hash)")
    _console("  [OK] UIA→SOM Bridge - Cross-reference elements by point")
    _console("  [OK] Per-Window SOM - Snapshot individual windows")
    _console("  [OK] Accelerated Regions - Track static areas")
    _console("  [OK] Element Finder - Find UIA element at pixel coords")
    _console()
    _console("  V5.0 FEATURES:")
    _console("  [OK] Web Dashboard - Live screen + clickable map + controls")
    if watchdog_ok:
        _console("  [OK] Keyboard Watchdog - Ctrl+Alt+Shift = emergency stop")
    _console("  [OK] OCR Find - Locate buttons/text by label")
    _console("  [OK] Visual Search - Find images on screen")
    _console("  [OK] UIA Tree - Accessibility element tree (click by index/name)")
    _console("  [OK] SOM Overlay - Numbered element boxes on screenshots")
    _console("  [OK] Background Input - SendInput (no focus steal)")
    _console("  [OK] TTS - Speak through speakers")
    _console("  [OK] Macros - Record/replay sequences (F9 to stop recording)")
    _console("  [OK] File Explorer - List/read/write/delete files via API")
    _console("  [OK] Tunnel - Cloudflare tunnel for remote access")
    _console("  [OK] MCP Mode - JSON-RPC stdin/stdout (run with --mcp)")
    _console("  [OK] Screenshot Cache - <1s instant response")
    _console("  [OK] Power Management - Sleep/Shutdown/Restart/Lock")
    _console("  [OK] Wallpaper Control - Set/Cycle/Random")
    _console("  [OK] File Search - Find files by name/glob across drives")
    _console("  [OK] Smart Crop - OCR region to clipboard")
    _console("  [OK] Screen Description - OCR the whole screen")
    _console("  [OK] Scheduled Actions - Cron-like timed desktop operations")
    _console("  [OK] Monitor Layout - Tile windows in grid")
    _console("  [OK] Voice Control - Wake word + voice commands")
    _console("  [OK] AI App Launcher - Smart app launch by description")
    _console()

    if mcp_mode:
        _console("  Starting in MCP mode...")
        run_mcp()
    else:
        session = os.environ.get("SESSIONNAME")
        if not session:
            _console("  [WARN] Running in non-interactive session")
            _console("  -> Screenshots may not work without GPU access")
            _console("  -> Double-click start.bat for full functionality")
            _console("  -> All mouse/keyboard/app/window features still work")
            _console()
        else:
            _console(f"  [OK] Interactive session: {session}")
            _console()

        _console(f"  [Dashboard]   http://localhost:{port}/")
        _console(f"  [Screen]      http://localhost:{port}/screen")
        _console(f"  [OCR]         POST /ocr/find")
        _console(f"  [CoPilot]     150ms cooldown, fire-and-forget")
        _console(f"  [Emergency]   POST /emergency/stop  |  Ctrl+Alt+Shift")
        _console(f"  [Macros]      POST /macro/record + /macro/run")
        _console(f"  [Tunnel]      POST /tunnel/start")
        _console()
        # Auth already initialized above
        if _secure_mode or _token_arg:
            _console(f"  [SECURE]     Auth active — Bearer token required")
        else:
            _console("  [WARNING]    No auth — desktop controllable by anyone on network (add --secure)")
        _console()

        bind_host = "127.0.0.1" if "--allow-external" not in sys.argv else "0.0.0.0"
        _console(f"  [LISTEN]     http://{bind_host}:{port}/")
        _console()

        # === SHORT ALIAS ROUTES for MCP server compatibility ===
        # These let the MCP server call /screenshot, /click, /move, /type, /hotkey, /scroll, /drag, /activate, /cursor
        @app.route("/screenshot")
        def route_short_screenshot():
            return route_screen_b64()

        @app.route("/click", methods=["POST"])
        def route_short_click():
            return route_mouse_click()

        @app.route("/move", methods=["POST"])
        def route_short_move():
            return route_mouse_move()

        @app.route("/type", methods=["POST"])
        def route_short_type():
            return route_key_type()

        @app.route("/hotkey", methods=["POST"])
        def route_short_hotkey():
            return route_key_press()

        @app.route("/scroll", methods=["POST"])
        def route_short_scroll():
            return route_mouse_scroll()

        @app.route("/drag", methods=["POST"])
        def route_short_drag():
            return route_mouse_drag()

        @app.route("/activate", methods=["POST"])
        def route_short_activate():
            from flask import request as _r
            d = _r.json
            return jsonify(activate_window_api(d["title"]))

        @app.route("/cursor")
        def route_short_cursor():
            return route_cursor()

        @app.route("/screensize")
        def route_short_screensize():
            return monitors_api()

        @app.route("/uia/tree")
        def route_short_uia_tree():
            return route_uia_snapshot()

        # Start system tray icon (falls back silently if pystray not installed)
        _start_tray()
        app.run(host=bind_host, port=port, debug=False, threaded=True)
