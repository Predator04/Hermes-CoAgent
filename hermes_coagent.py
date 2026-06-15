# Hermes CoAgent v3 - Ultimate Desktop Co-Pilot
# All features: Dashboard, MCP, OCR, Visual Search, TTS, Watchdog, Macros, Tunnel, Recorder, File API
import sys, os, json, base64, subprocess, threading, time, shutil
import re, queue
from io import BytesIO
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List
import ctypes

os.environ["PYAUTOGUI_FAILSAFE"] = "false"
import pyautogui
pyautogui.FAILSAFE = False
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0
pyautogui.PAUSE = 0.01

COAGENT_DIR = Path(__file__).parent.resolve()
MACROS_DIR = COAGENT_DIR / "macros"
SCREENSHOTS_DIR = COAGENT_DIR / "screenshots"
TUNNEL_LOG = COAGENT_DIR / "tunnel.log"
PULSE_SCRIPT = COAGENT_DIR / "pulse_overlay.py"
PULSE_LOG = COAGENT_DIR / "pulse_debug.log"
SERVER_PORT = 9123

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

PYTHON = sys.executable

def _console(msg=""):
    sys.stderr.write(str(msg) + "\n")
    sys.stderr.flush()

def _pulse_log(msg):
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with PULSE_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        _console(f"[Pulse] {msg}")

def _pythonw_for_pulse():
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)

def _pulse_popen_kwargs():
    kwargs = {
        "cwd": str(COAGENT_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs

# === STATE ===
@dataclass
class CoPilotState:
    emergency_stop: bool = False
    input_lock: threading.Lock = field(default_factory=threading.Lock)
    last_action_time: float = 0.0
    min_action_gap: float = 0.12
    last_screenshot_time: float = 0.0
    last_screenshot_data: bytes = b""
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
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

# === CURSOR PULSE - visual ring before every AI action ===
def _cursor_pulse(x, y, color=None):
    """Flash a colored ring at (x, y) in a short-lived tkinter helper process."""
    if color is None:
        color = 0x00FF00  # green
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    try:
        if not PULSE_SCRIPT.exists():
            _pulse_log(f"Pulse helper missing: {PULSE_SCRIPT}")
            return
        subprocess.Popen(
            [
                _pythonw_for_pulse(),
                str(PULSE_SCRIPT),
                str(int(x)),
                str(int(y)),
                str(int(r)),
                str(int(g)),
                str(int(b)),
            ],
            **_pulse_popen_kwargs(),
        )
    except Exception as e:
        _pulse_log(f"Failed to launch pulse helper: {e}")

def _current_cursor_pos(default=(960, 540)):
    try:
        pos = pyautogui.position()
        return int(pos[0]), int(pos[1])
    except Exception as e:
        _pulse_log(f"Could not read cursor position: {e}")
        return default

def _pulse_before_action(action: dict):
    """Show a colored pulse based on action type before executing."""
    try:
        act_type = action.get("type", "")
        data = action.get("data", {})
        color = 0x00FF00  # green default
        if act_type in ("click", "doubleclick", "rightclick", "tripleclick"):
            color = 0xFF4400  # orange for clicks
        elif act_type == "type":
            color = 0x4488FF  # blue for typing
        elif act_type == "hotkey":
            color = 0xFF00FF  # magenta for hotkeys
        elif act_type == "scroll":
            color = 0xFFFF00  # yellow for scroll
        elif act_type == "drag":
            color = 0xFFAA00

        fallback_x, fallback_y = _current_cursor_pos()
        x = data.get("x", data.get("x2", data.get("x1", fallback_x)))
        y = data.get("y", data.get("y2", data.get("y1", fallback_y)))
        _cursor_pulse(x, y, color)
    except Exception as e:
        _pulse_log(f"Pulse setup failed: {e}")

# === INPUT ENGINE ===
def _execute_action(action: dict):
    act_type = action.get("type")
    data = action.get("data", {})
    _pulse_before_action(action)
    with state.input_lock:
        if state.emergency_stop:
            raise Exception("Emergency stop active")
        elapsed = time.time() - state.last_action_time
        if elapsed < state.min_action_gap:
            time.sleep(state.min_action_gap - elapsed)
        try:
            if act_type == "move":
                pyautogui.moveTo(data["x"], data["y"], duration=data.get("duration", 0.01))
            elif act_type == "click":
                pyautogui.click(button=data.get("button", "left"), clicks=data.get("clicks", 1), interval=0.005)
            elif act_type == "type":
                pyautogui.typewrite(data["text"], interval=data.get("interval", 0.005))
            elif act_type == "hotkey":
                pyautogui.hotkey(*data.get("keys", []))
            elif act_type == "scroll":
                pyautogui.scroll(data.get("clicks", -3))
            elif act_type == "drag":
                pyautogui.moveTo(data["x1"], data["y1"], duration=0.01)
                pyautogui.drag(data["x2"]-data["x1"], data["y2"]-data["y1"],
                              button=data.get("button","left"), duration=data.get("duration",0.15))
            elif act_type == "doubleclick":
                pyautogui.doubleClick(button=data.get("button","left"))
            elif act_type == "rightclick":
                pyautogui.rightClick(button=data.get("button","right"))
            elif act_type == "tripleclick":
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
    if not force and state.last_screenshot_data and (now - state.last_screenshot_time) < 1.0:
        return state.last_screenshot_data
    with state.screenshot_lock:
        if not force and state.last_screenshot_data and (time.time() - state.last_screenshot_time) < 1.0:
            return state.last_screenshot_data
        img_bytes = _capture_raw()
        state.last_screenshot_data = img_bytes
        state.last_screenshot_time = time.time()
        return img_bytes

def _capture_raw() -> bytes:
    # Method 1: PowerShell System.Drawing (most reliable from any session)
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
    except: pass
    # Method 2: PIL ImageGrab
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except: pass
    # Method 3: mss
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            sct_img = sct.grab(mon)
            from PIL import Image
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except: pass
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
        "app_open": lambda p: (subprocess.Popen(p["path"],shell=True),{"status":"launched"})[1],
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
            text=True
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
    data = {"name": name, "actions": actions, "created": str(datetime.now()),
            "modified": str(datetime.now())}
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
                items.append({
                    "name": item.name, "path": str(item),
                    "is_dir": is_dir, "size": 0 if is_dir else item.stat().st_size,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
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
        if p.stat().st_size > 50 * 1024 * 1024:
            return {"error": "File too large (>50MB)"}
        data = p.read_bytes()
        is_text = True
        try:
            data.decode("utf-8")
        except:
            is_text = False
        return {"path": str(p), "size": p.stat().st_size,
                "is_text": is_text,
                "content": data.decode("utf-8", errors="replace") if is_text else base64.b64encode(data).decode()}
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

def run_command_api(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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


DASHBOARD_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Hermes CoAgent v3</title>\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nbody{font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;background:#0a0a0f;color:#e0e0e0;overflow:hidden;height:100vh}\n.app{display:grid;grid-template-columns:320px 1fr 300px;height:100vh;gap:1px;background:#1a1a2e}\n.panel{background:#111122;padding:12px;overflow-y:auto}\n.panel h2{font-size:13px;text-transform:uppercase;color:#666;margin-bottom:10px;letter-spacing:1px}\n.btn{background:#1a1a3e;border:1px solid #333;color:#ccc;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s}\n.btn:hover{background:#2a2a5e;border-color:#555}\n.btn.danger{background:#3a1111;border-color:#633}\n.btn.danger:hover{background:#5a1515;border-color:#a33}\n.btn.success{background:#113a11;border-color:#363}\n.btn.success:hover{background:#155a15;border-color:#3a3}\n.btn-row{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}\n#screenshot-container{position:relative;display:flex;align-items:center;justify-content:center;height:100%;overflow:hidden;background:#0a0a0f}\n#screen-img{max-width:100%;max-height:100%;object-fit:contain;image-rendering:auto;cursor:crosshair;border-radius:4px}\n.coord-overlay{position:absolute;top:0;left:0;pointer-events:none;color:#fff;background:rgba(0,0,0,0.7);padding:2px 6px;border-radius:4px;font-size:11px;font-family:monospace;z-index:10}\n.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}\n.dot-green{background:#0f0}\n.dot-red{background:#f00}\n.dot-yellow{background:#ff0}\n#action-log{font-family:monospace;font-size:11px;line-height:1.6}\n.action-entry{padding:2px 0;border-bottom:1px solid #1a1a2e;display:flex;justify-content:space-between}\n.action-time{color:#555;font-size:10px}\n.logo{font-size:20px;font-weight:bold;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}\n.subtitle{font-size:11px;color:#666;margin-bottom:12px}\ninput[type=text],input[type=number]{background:#1a1a2e;border:1px solid #333;color:#ccc;padding:5px 8px;border-radius:4px;font-size:12px;width:100%;margin-bottom:6px}\nlabel{font-size:11px;color:#888;display:block;margin-bottom:2px}\n.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}\n.tool-group{margin-bottom:12px;padding:8px;background:#0e0e1a;border-radius:6px}\n.tool-group h3{font-size:12px;color:#888;margin-bottom:6px}\n#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1a1a3e;border:1px solid #444;padding:8px 16px;border-radius:8px;font-size:12px;z-index:999;display:none}\n</style>\n</head>\n<body>\n<div id="toast"></div>\n<div class="app">\n  <div class="panel" id="left-panel">\n    <div class="logo"> Hermes CoAgent</div>\n    <div class="subtitle">v3 - Desktop Co-Pilot</div>\n    <div id="status-bar" style="margin-bottom:10px"><span class="status-dot dot-green"></span><span id="status-text">Connected</span></div>\n\n    <div class="tool-group">\n      <h3> Mouse</h3>\n      <div class="grid">\n        <div><label>X</label><input type="number" id="mx" value="960"></div>\n        <div><label>Y</label><input type="number" id="my" value="540"></div>\n      </div>\n      <div class="btn-row">\n        <button class="btn" onclick="mouseMove()">Move</button>\n        <button class="btn" onclick="mouseClick(\'left\')">Left</button>\n        <button class="btn" onclick="mouseClick(\'right\')">Right</button>\n        <button class="btn" onclick="mouseClick(\'middle\')">Mid</button>\n        <button class="btn" onclick="mouseDClick()">Dbl</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Keyboard</h3>\n      <input type="text" id="type-text" placeholder="Type something..." onkeydown="if(event.key===\'Enter\')keyType()">\n      <div class="btn-row">\n        <button class="btn" onclick="keyType()">Type</button>\n        <button class="btn" onclick="keyPress([\'ctrl\',\'c\'])">Ctrl+C</button>\n        <button class="btn" onclick="keyPress([\'ctrl\',\'v\'])">Ctrl+V</button>\n        <button class="btn" onclick="keyPress([\'enter\'])">Enter</button>\n        <button class="btn" onclick="keyPress([\'tab\'])">Tab</button>\n        <button class="btn" onclick="keyPress([\'escape\'])">Esc</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Find</h3>\n      <input type="text" id="find-text" placeholder="Text on screen...">\n      <div class="btn-row">\n        <button class="btn" onclick="ocrFind()">Find Text</button>\n        <button class="btn" onclick="cursorPos()">Cursor</button>\n        <button class="btn" onclick="monitors()">Monitors</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Files</h3>\n      <input type="text" id="file-path" placeholder="C:\\Users\\Admin\\Desktop" value="C:\\Users\\Admin\\Desktop">\n      <div class="btn-row">\n        <button class="btn" onclick="fileList()">List</button>\n        <button class="btn" onclick="appOpen()">Open</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Macros</h3>\n      <input type="text" id="macro-name" placeholder="macro name">\n      <div class="btn-row">\n        <button class="btn" onclick="macroList()">List</button>\n        <button class="btn success" onclick="macroRecord()">Record</button>\n        <button class="btn" onclick="macroRun()">Run</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Emergency</h3>\n      <div class="btn-row">\n        <button class="btn danger" onclick="emergency(\'stop\')"> STOP</button>\n        <button class="btn success" onclick="emergency(\'resume\')"> Resume</button>\n      </div>\n    </div>\n\n    <div class="tool-group">\n      <h3> Tunnel</h3>\n      <div class="btn-row">\n        <button class="btn" onclick="tunnel(\'start\')">Start</button>\n        <button class="btn danger" onclick="tunnel(\'stop\')">Stop</button>\n        <button class="btn" onclick="tunnel(\'status\')">Status</button>\n      </div>\n      <div id="tunnel-info" style="font-size:11px;color:#666"></div>\n    </div>\n  </div>\n\n  <div id="screenshot-container">\n    <img id="screen-img" src="/screen" alt="Screen">\n    <div class="coord-overlay" id="coord-overlay">Click to get coords</div>\n  </div>\n\n  <div class="panel" id="right-panel">\n    <h2>Action Log</h2>\n    <div id="action-log">\n      <div class="action-entry"><span>Ready</span><span class="action-time">now</span></div>\n    </div>\n    <div style="margin-top:8px">\n      <button class="btn" onclick="clearLog()" style="width:100%">Clear</button>\n    </div>\n  </div>\n</div>\n\n<script>\nconst BASE = \'\';\nlet logCount = 0;\nfunction toast(msg){const t=document.getElementById(\'toast\');t.textContent=msg;t.style.display=\'block\';setTimeout(()=>t.style.display=\'none\',2000)}\nfunction api(method,path,body,cb){\n  const opts={method,headers:{\'Content-Type\':\'application/json\'}};\n  if(body)opts.body=JSON.stringify(body);\n  fetch(BASE+path,opts).then(r=>r.json()).then(d=>{if(cb)cb(d)}).catch(e=>toast(\'Error: \'+e.message));\n}\nfunction addLog(text){\n  logCount++;\n  const el=document.getElementById(\'action-log\');\n  const d=new Date();\n  el.innerHTML=`<div class="action-entry"><span>${text}</span><span class="action-time">${d.getHours().toString().padStart(2,\'0\')}:${d.getMinutes().toString().padStart(2,\'0\')}:${d.getSeconds().toString().padStart(2,\'0\')}</span></div>`+el.innerHTML;\n  if(logCount>100){el.lastChild.remove();logCount--}\n}\nfunction clearLog(){document.getElementById(\'action-log\').innerHTML=\'\';logCount=0;addLog(\'Cleared\')}\n\n// Mouse\nfunction mouseMove(){const x=document.getElementById(\'mx\').value,y=document.getElementById(\'my\').value;api(\'POST\',\'/mouse/move\',{x:parseInt(x),y:parseInt(y)},d=>addLog(\'Moved to \'+x+\',\'+y))}\nfunction mouseClick(b){api(\'POST\',\'/mouse/click\',{button:b},d=>addLog(\'Clicked \'+b))}\nfunction mouseDClick(){api(\'POST\',\'/mouse/doubleclick\',{},d=>addLog(\'Double clicked\'))}\n\n// Keyboard\nfunction keyType(){const t=document.getElementById(\'type-text\').value;api(\'POST\',\'/key/type\',{text:t},d=>addLog(\'Typed: \'+t.substring(0,30)+(t.length>30?\'...\':\'\')))}\nfunction keyPress(keys){api(\'POST\',\'/key/press\',{keys},d=>addLog(\'Pressed: \'+keys.join(\'+\'))})}\n\n// Emergency\nfunction emergency(a){api(\'POST\',\'/emergency/\'+a,{},d=>{addLog(\'Emergency: \'+a);document.getElementById(\'status-text\').textContent=a===\'stop\'?\'STOPPED\':\'Connected\';document.getElementById(\'status-bar\').innerHTML=(a===\'stop\'?\'<span class="status-dot dot-red"></span>\':\'<span class="status-dot dot-green"></span>\')+document.getElementById(\'status-text\').textContent})}\n\n// Find\nfunction ocrFind(){const t=document.getElementById(\'find-text\').value;if(!t)return;api(\'POST\',\'/ocr/find\',{text:t},d=>{if(d.found){addLog(\'Found: \'+t+\' at \'+JSON.stringify(d.matches[0].center));toast(\'Found at \'+d.matches[0].center)}else{addLog(\'Not found: \'+t);toast(\'Not found\')}})}\nfunction cursorPos(){api(\'GET\',\'/cursor/pos\',null,d=>{document.getElementById(\'mx\').value=d.x;document.getElementById(\'my\').value=d.y;addLog(\'Cursor: \'+d.x+\',\'+d.y)})}\nfunction monitors(){api(\'GET\',\'/monitors\',null,d=>addLog(\'Monitors: \'+JSON.stringify(d.monitors)))}\n\n// Files\nfunction fileList(){const p=document.getElementById(\'file-path\').value;api(\'POST\',\'/file/list\',{path:p},d=>{if(d.items){addLog(\'Files in \'+d.path+\': \'+d.count+\' items\');toast(d.count+\' items\')}})}\nfunction appOpen(){const p=document.getElementById(\'file-path\').value;api(\'POST\',\'/app/open\',{path:p},d=>addLog(\'Opened: \'+p))}\n\n// Macros\nfunction macroList(){api(\'GET\',\'/macro/list\',null,d=>{if(d.macros){addLog(\'Macros: \'+d.macros.map(m=>m.name).join(\', \')||\'none\');toast(d.macros.length+\' macros\')}})}\nfunction macroRecord(){const n=document.getElementById(\'macro-name\').value;if(!n)return;api(\'POST\',\'/macro/record\',{name:n},d=>{addLog(\'Recording: \'+n+\'. Press F9 to stop.\');toast(\'Recording \'+n)})}\nfunction macroRun(){const n=document.getElementById(\'macro-name\').value;if(!n)return;api(\'POST\',\'/macro/run\',{name:n},d=>addLog(\'Ran macro: \'+n+\' (\'+d.executed+\'/\'+d.total+\')\'))}\n\n// Tunnel\nfunction tunnel(a){api(\'POST\',\'/tunnel/\'+a,{},d=>{addLog(\'Tunnel: \'+a+\' - \'+(d.url||d.status||d.message||\'ok\'));document.getElementById(\'tunnel-info\').textContent=d.url?\'URL: \'+d.url:\'\'})}\n\n// Screenshot click -> get coords\ndocument.getElementById(\'screen-img\').addEventListener(\'click\', function(e){\n  const rect = this.getBoundingClientRect();\n  const x = Math.round(e.clientX - rect.left);\n  const y = Math.round(e.clientY - rect.top);\n  const nw = this.naturalWidth||1920, nh = this.naturalHeight||1080;\n  const sx = this.width, sy = this.height;\n  const realX = Math.round(x * nw / sx);\n  const realY = Math.round(y * nh / sy);\n  document.getElementById(\'mx\').value = realX;\n  document.getElementById(\'my\').value = realY;\n  document.getElementById(\'coord-overlay\').textContent = realX+\',\'+realY;\n  toast(\'Screen coords: \'+realX+\',\'+realY);\n});\n\n// Auto-refresh screenshot every 2s\nsetInterval(()=>{\n  const img = document.getElementById(\'screen-img\');\n  img.src = \'/screenshot/fresh?\'+Date.now();\n}, 2000);\n\n// Auto-refresh action history every 3s\nsetInterval(()=>{\n  fetch(BASE+\'/history?limit=20\').then(r=>r.json()).then(d=>{\n    if(!d.actions||!d.actions.length)return;\n    const el=document.getElementById(\'action-log\');\n    let html=\'\';\n    for(let i=d.actions.length-1;i>=Math.max(0,d.actions.length-20);i--){\n      const a=d.actions[i];\n      const t=a.time?new Date(a.time).getHours().toString().padStart(2,\'0\')+\':\'+new Date(a.time).getMinutes().toString().padStart(2,\'0\')+\':\'+new Date(a.time).getSeconds().toString().padStart(2,\'0\'):\'\';\n      html+=`<div class="action-entry"><span>${a.type} ${JSON.stringify(a.data).substring(0,40)}</span><span class="action-time">${t}</span></div>`;\n    }\n    el.innerHTML=html;\n  }).catch(()=>{});\n}, 3000);\n</script>\n</body>\n</html>'

# =========== WEB DASHBOARD ===========
@app.route("/")
def dashboard():
    return DASHBOARD_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

# =========== REST API ROUTES ===========
@app.route("/ping")
def route_ping():
    return jsonify({
        "status": "ok", "agent": "Hermes CoAgent v3",
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
def route_app_open():
    d = request.json
    subprocess.Popen(d["path"], shell=True)
    return jsonify({"status": "launched", "path": d["path"]})

@app.route("/app/run", methods=["POST"])
def route_app_run():
    d = request.json
    return jsonify(run_command_api(d["cmd"], d.get("timeout", 30)))

# === MONITORS ===
@app.route("/monitors")
def route_monitors():
    return jsonify(monitors_api())

# === OCR ===
@app.route("/ocr/find", methods=["POST"])
def route_ocr():
    d = request.json
    return jsonify(ocr_find_text(d["text"], d.get("region")))

# === VISUAL SEARCH ===
@app.route("/visual/find", methods=["POST"])
def route_visual():
    d = request.json
    return jsonify(visual_find_image(d["template_path"], d.get("confidence", 0.8)))

# === FILES ===
@app.route("/file/list", methods=["POST"])
def route_file_list():
    d = request.json
    return jsonify(file_list_api(d.get("path", ".")))

@app.route("/file/read", methods=["POST"])
def route_file_read():
    d = request.json
    return jsonify(file_read_api(d["path"]))

@app.route("/file/write", methods=["POST"])
def route_file_write():
    d = request.json
    return jsonify(file_write_api(d["path"], d["content"], d.get("is_base64", False)))

@app.route("/file/delete", methods=["POST"])
def route_file_delete():
    d = request.json
    return jsonify(file_delete_api(d["path"]))

# === TTS ===
@app.route("/tts/speak", methods=["POST"])
def route_tts():
    d = request.json
    return jsonify(tts_speak_api(d["text"]))

# === TUNNEL ===
@app.route("/tunnel/start", methods=["POST"])
def route_tunnel_start():
    return jsonify(tunnel_start_action())

@app.route("/tunnel/stop", methods=["POST"])
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
def route_macro_delete():
    d = request.json
    p = MACROS_DIR / f"{d['name']}.json"
    if p.exists():
        p.unlink()
        return jsonify({"status": "deleted", "name": d["name"]})
    return jsonify({"error": "Not found"}), 404

# === MCP PROXY ===
mcp_queue = queue.Queue()
mcp_result_queue = queue.Queue()
mcp_ready = threading.Event()

def _mcp_listener_thread():
    """Read MCP responses from the MCP subprocess."""
    import sys as _sys
    while True:
        try:
            line = _sys.stdin.readline()
        except:
            break

def _handle_mcp():
    """Handle MCP connections by spawning a subprocess."""
    pass

# =========== MAIN ===========
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9123
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

    _console()
    _console("  +" + "="*44 + "+")
    _console("  |         Hermes CoAgent v3                |")
    _console("  |      Ultimate Desktop Co-Pilot            |")
    _console("  +" + "="*44 + "+")
    _console()
    _console(f"  Mode:   {'MCP' if mcp_mode else 'HTTP REST + Web Dashboard'}")
    _console(f"  Port:   {port}")
    _console()
    _console("  10 NEW FEATURES:")
    _console("  [OK] Web Dashboard - Live screen + clickable map + controls")
    if watchdog_ok:
        _console("  [OK] Keyboard Watchdog - Ctrl+Alt+Shift = emergency stop")
    _console("  [OK] OCR Find - Locate buttons/text by label")
    _console("  [OK] Visual Search - Find images on screen")
    _console("  [OK] TTS - Speak through speakers")
    _console("  [OK] Macros - Record/replay sequences (F9 to stop recording)")
    _console("  [OK] File Explorer - List/read/write/delete files via API")
    _console("  [OK] Tunnel - Cloudflare tunnel for remote access")
    _console("  [OK] MCP Mode - JSON-RPC stdin/stdout (run with --mcp)")
    _console("  [OK] Screenshot Cache - <1s instant response")
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
        _console("  WARNING: No auth. Local/trusted network only.")
        _console()

        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
