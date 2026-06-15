#!/usr/bin/env python
"""
Hermes CoAgent - Windows Computer Use MCP Server (Optimized v2.0)
================================================================
Fast-starting MCP server giving Hermes full desktop control:
screenshots, UIA tree, click/type/scroll/hotkey, find, drag,
and SOM overlays. All local — zero API costs.

Usage:
  python computer_use_mcp.py                   # stdio MCP (default)
  python computer_use_mcp.py --http            # HTTP SSE MCP server on :8000
  python computer_use_mcp.py --test            # Run self-test
  python computer_use_mcp.py --fast            # Lazy-load heavy deps

Config:
  COAGENT_URL=http://localhost:9123            # CoAgent server
  MCP_FAST=1                                   # Lazy-import mode via env
"""
import sys, os, json, base64, io, time, subprocess, threading, re, traceback
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from io import BytesIO

FAST_MODE = os.environ.get("MCP_FAST", "") or "--fast" in sys.argv

# ── MCP SDK ──────────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP, Context as MCPContext

# ── Lazy image imports ───────────────────────────────────────────────────
def _lazy_imports():
    """Import heavy deps on demand in fast mode."""
    global HAS_PIL, HAS_TESSERACT, HAS_UIA, pythoncom, PyWinDesktop, \
           Image, ImageDraw, ImageFont, pytesseract
    try:
        from PIL import Image, ImageDraw, ImageFont
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False
    HAS_TESSERACT = False
    try:
        import pytesseract
        try:
            pytesseract.get_tesseract_version()
            HAS_TESSERACT = True
        except:
            pass
    except ImportError:
        pass
    HAS_UIA = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        from pywinauto import Desktop as PyWinDesktop
        HAS_UIA = True
    except ImportError:
        pass

if FAST_MODE:
    # Stubs — real imports happen on first use
    HAS_PIL = HAS_TESSERACT = HAS_UIA = False
    Image = ImageDraw = ImageFont = pytesseract = pythoncom = PyWinDesktop = None
else:
    try:
        from PIL import Image, ImageDraw, ImageFont
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False
    HAS_TESSERACT = False
    try:
        import pytesseract
        try:
            pytesseract.get_tesseract_version()
            HAS_TESSERACT = True
        except:
            pass
    except ImportError:
        pass
    HAS_UIA = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        from pywinauto import Desktop as PyWinDesktop
        HAS_UIA = True
    except ImportError:
        pass

# ── CoAgent HTTP client ──────────────────────────────────────────────────
COAGENT_URL = os.environ.get("COAGENT_URL", "http://localhost:9123")
import urllib.request, urllib.error

_coagent_cache = {}
_coagent_cache_ttl = 2.0  # seconds
_last_coagent_cache = 0.0

def _coagent_get(path: str, no_cache=False) -> Optional[dict]:
    """GET request to CoAgent server with simple caching."""
    global _coagent_cache, _last_coagent_cache
    now = time.time()
    cache_key = f"GET:{path}"
    if not no_cache and path in _coagent_cache and (now - _last_coagent_cache) < _coagent_cache_ttl:
        return _coagent_cache[path]
    try:
        req = urllib.request.Request(f"{COAGENT_URL}{path}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode())
            if not no_cache:
                _coagent_cache[path] = result
                _last_coagent_cache = now
            return result
    except Exception as e:
        return {"error": str(e)}

def _coagent_post(path: str, data: dict) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            f"{COAGENT_URL}{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def _coagent_ensure_alive():
    """Quick ping with fallback retry."""
    result = _coagent_get("/", no_cache=True)
    if result and "error" not in result:
        return True
    # One retry: try to wake screenshot endpoint
    for _ in range(2):
        time.sleep(1)
        result = _coagent_get("/", no_cache=True)
        if result and "error" not in result:
            return True
    return False

# ── FastMCP Server ───────────────────────────────────────────────────────
mcp = FastMCP(
    "windows-computer-use",
    instructions="Windows desktop control via CoAgent (UIA + screenshots + OCR). "
                 "Use activate_window first to focus a window before clicking/typing."
)

# ── Tool Implementations ─────────────────────────────────────────────────

@mcp.tool()
async def ping() -> str:
    """Quick health check. Returns 'pong' plus CoAgent status."""
    alive = _coagent_ensure_alive()
    status = _coagent_get("/", no_cache=True)
    return json.dumps({
        "status": "ok",
        "coagent": alive,
        "coagent_version": (status or {}).get("version", "unknown"),
        "fast_mode": FAST_MODE
    })

# ── Screenshots ──────────────────────────────────────────────────────────

@mcp.tool()
async def screenshot() -> str:
    """Get a raw screenshot (base64 PNG). No overlays."""
    data = _coagent_get("/screenshot", no_cache=True)
    if not data or "error" in data:
        if not _coagent_ensure_alive():
            return json.dumps({"error": "CoAgent unreachable"})
        data = _coagent_get("/screenshot", no_cache=True)
    return json.dumps(data or {"error": "no screenshot data"})

@mcp.tool()
async def capture(mode: str = "som") -> str:
    """
    Capture screen with Set-of-Mark overlay or raw.
    Args:
        mode: 'som' for numbered overlay, 'raw' for plain screenshot, 'uia' for UIA tree only
    Returns JSON with labeled_screenshot (base64 PNG), elements list, or raw screenshot data.
    """
    if mode == "uia":
        data = _coagent_get("/uia/tree", no_cache=True)
        return json.dumps(data or {"error": "no UIA data"})
    data = _coagent_get("/screenshot", no_cache=True)
    if not data or "error" in data:
        if not _coagent_ensure_alive():
            return json.dumps({"error": "CoAgent unreachable"})
        data = _coagent_get("/screenshot", no_cache=True)
    if mode == "raw":
        return json.dumps(data or {"error": "no screenshot data"})
    # SOM mode — overlay elements on screenshot
    if not data or "image" not in data:
        return json.dumps(data or {"error": "no screenshot data"})
    try:
        img_b64 = data["image"]
        img_bytes = base64.b64decode(img_b64)
        img = Image.open(io.BytesIO(img_bytes))
        draw = ImageDraw.Draw(img)
        uia_data = _coagent_get("/uia/tree", no_cache=True)
        elements = []
        if uia_data and "windows" in uia_data:
            idx = 1
            for win in uia_data["windows"]:
                if all(k in win for k in ("left", "top", "width", "height")):
                    x, y, w, h = win["left"], win["top"], win["width"], win["height"]
                    if w < 20 or h < 20:
                        continue
                    elements.append({
                        "index": idx,
                        "name": win.get("name", ""),
                        "control_type": win.get("control_type", "Window"),
                        "x": x + w // 2,
                        "y": y + h // 2,
                        "width": w,
                        "height": h
                    })
                    # Draw number circle
                    cx, cy = x + w // 2, y + 8
                    draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill="red")
                    draw.text((cx - 4, cy - 6), str(idx), fill="white")
                    # Draw bounding box
                    draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
                    idx += 1
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return json.dumps({
            "labeled_screenshot": base64.b64encode(buf.getvalue()).decode(),
            "elements": elements
        })
    except Exception as e:
        return json.dumps({"error": f"SOM generation failed: {str(e)}"})

# ── Input actions ────────────────────────────────────────────────────────

@mcp.tool()
async def click(x: int, y: int, button: str = "left") -> str:
    """Click at specific screen coordinates."""
    result = _coagent_post("/click", {"x": x, "y": y, "button": button})
    return json.dumps(result or {"error": "click failed"})

@mcp.tool()
async def click_element(index: int) -> str:
    """Click a UI element by its SOM index (from capture output)."""
    # First get current UIA tree
    uia_data = _coagent_get("/uia/tree", no_cache=True)
    if not uia_data or "windows" not in uia_data:
        return json.dumps({"error": "no UIA data"})
    elements = []
    for win in uia_data["windows"]:
        if all(k in win for k in ("left", "top", "width", "height")):
            w = win.get("width", 0)
            h = win.get("height", 0)
            if w >= 20 and h >= 20:
                elements.append(win)
    idx = index - 1
    if idx < 0 or idx >= len(elements):
        return json.dumps({"error": f"element index {index} out of range (1-{len(elements)})"})
    el = elements[idx]
    x = el["left"] + el["width"] // 2
    y = el["top"] + el["height"] // 2
    result = _coagent_post("/click", {"x": x, "y": y, "button": "left"})
    return json.dumps(result or {"error": "click failed"})

@mcp.tool()
async def double_click(x: int, y: int, button: str = "left") -> str:
    """Double-click at specific coordinates."""
    click(x, y, button)
    time.sleep(0.05)
    result = _coagent_post("/click", {"x": x, "y": y, "button": button})
    return json.dumps(result or {"error": "double click failed"})

@mcp.tool()
async def right_click(x: int, y: int) -> str:
    """Right-click at coordinates."""
    result = _coagent_post("/click", {"x": x, "y": y, "button": "right"})
    return json.dumps(result or {"error": "right click failed"})

@mcp.tool()
async def move_mouse(x: int, y: int) -> str:
    """Move mouse to coordinates."""
    result = _coagent_post("/move", {"x": x, "y": y})
    return json.dumps(result or {"error": "move failed"})

@mcp.tool()
async def type_text(text: str) -> str:
    """Type text at current cursor position."""
    result = _coagent_post("/type", {"text": text})
    return json.dumps(result or {"error": "type failed"})

@mcp.tool()
async def press_key(keys: list) -> str:
    """Press key combination. Examples: ['ctrl','c'], ['alt','tab'], ['enter']"""
    result = _coagent_post("/hotkey", {"keys": keys})
    return json.dumps(result or {"error": "hotkey failed"})

@mcp.tool()
async def scroll(clicks: int = -3) -> str:
    """Scroll mouse wheel. Negative=down, positive=up."""
    result = _coagent_post("/scroll", {"clicks": clicks})
    return json.dumps(result or {"error": "scroll failed"})

@mcp.tool()
async def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> str:
    """Drag from (x1,y1) to (x2,y2)."""
    result = _coagent_post("/drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": button})
    return json.dumps(result or {"error": "drag failed"})

# ── Window management ────────────────────────────────────────────────────

@mcp.tool()
async def get_uia_tree() -> str:
    """Get full UIA accessibility tree of all windows."""
    data = _coagent_get("/uia/tree", no_cache=True)
    return json.dumps(data or {"error": "no UIA data"})

@mcp.tool()
async def list_windows() -> str:
    """List all open windows with titles and positions."""
    data = _coagent_get("/uia/tree", no_cache=True)
    if not data or "windows" not in data:
        return json.dumps({"error": "no UIA data"})
    windows = []
    for win in data.get("windows", []):
        windows.append({
            "title": win.get("name", ""),
            "x": win.get("left", 0),
            "y": win.get("top", 0),
            "width": win.get("width", 0),
            "height": win.get("height", 0),
            "control_type": win.get("control_type", "Window"),
        })
    return json.dumps({"windows": windows, "count": len(windows)})

@mcp.tool()
async def activate_window(title: str) -> str:
    """Bring a window to foreground by title (substring match)."""
    result = _coagent_post("/activate", {"title": title})
    return json.dumps(result or {"error": "activate failed"})

# ── Find on screen ───────────────────────────────────────────────────────

@mcp.tool()
async def find_on_screen(text: str) -> str:
    """Find UI element by name using both UIA and OCR. Returns matches with coordinates."""
    matches = []
    # Try UIA first
    uia_data = _coagent_get("/uia/tree", no_cache=True)
    if uia_data and "windows" in uia_data:
        for win in uia_data.get("windows", []):
            name = win.get("name", "")
            if text.lower() in name.lower():
                matches.append({
                    "method": "uia",
                    "name": name,
                    "center": {
                        "x": win.get("left", 0) + win.get("width", 0) // 2,
                        "y": win.get("top", 0) + win.get("height", 0) // 2
                    },
                    "bounds": {
                        "x": win.get("left", 0),
                        "y": win.get("top", 0),
                        "width": win.get("width", 0),
                        "height": win.get("height", 0)
                    },
                    "control_type": win.get("control_type", "Window")
                })
            # Also check child controls
            for child in win.get("children", []):
                cname = child.get("name", "")
                if text.lower() in cname.lower():
                    matches.append({
                        "method": "uia",
                        "name": cname,
                        "center": {
                            "x": child.get("left", 0) + child.get("width", 0) // 2,
                            "y": child.get("top", 0) + child.get("height", 0) // 2
                        },
                        "bounds": {
                            "x": child.get("left", 0),
                            "y": child.get("top", 0),
                            "width": child.get("width", 0),
                            "height": child.get("height", 0)
                        },
                        "control_type": child.get("control_type", "Control")
                    })
    # Try OCR for text find if no matches
    if not matches and HAS_TESSERACT and not FAST_MODE:
        _lazy_imports()
        try:
            import pytesseract
            from PIL import Image
            data = _coagent_get("/screenshot", no_cache=True)
            if data and "image" in data:
                img = Image.open(io.BytesIO(base64.b64decode(data["image"])))
                ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                for i in range(len(ocr_data["text"])):
                    if text.lower() in ocr_data["text"][i].lower():
                        x, y, w, h = (ocr_data["left"][i], ocr_data["top"][i],
                                       ocr_data["width"][i], ocr_data["height"][i])
                        matches.append({
                            "method": "ocr",
                            "text": ocr_data["text"][i],
                            "center": {"x": x + w // 2, "y": y + h // 2},
                            "bounds": {"x": x, "y": y, "width": w, "height": h},
                            "confidence": ocr_data["conf"][i] if i < len(ocr_data["conf"]) else 0
                        })
        except:
            pass
    return json.dumps({
        "query": text,
        "count": len(matches),
        "matches": matches
    })

# ── Chain actions ────────────────────────────────────────────────────────

@mcp.tool()
async def chain(actions: list) -> str:
    """
    Execute multiple actions atomically in sequence.
    Each action is {type, data} where type is one of:
    move, click, doubleclick, rightclick, type, hotkey, scroll, drag
    """
    results = []
    for i, action in enumerate(actions):
        t = action.get("type", "")
        d = action.get("data", {})
        try:
            if t == "move":
                r = _coagent_post("/move", {"x": d["x"], "y": d["y"]})
            elif t == "click":
                r = _coagent_post("/click", {"x": d.get("x", 0), "y": d.get("y", 0),
                                             "button": d.get("button", "left")})
            elif t == "doubleclick":
                r1 = _coagent_post("/click", {"x": d.get("x", 0), "y": d.get("y", 0),
                                              "button": d.get("button", "left")})
                time.sleep(0.05)
                r = _coagent_post("/click", {"x": d.get("x", 0), "y": d.get("y", 0),
                                              "button": d.get("button", "left")})
            elif t == "rightclick":
                r = _coagent_post("/click", {"x": d.get("x", 0), "y": d.get("y", 0), "button": "right"})
            elif t == "type":
                r = _coagent_post("/type", {"text": d.get("text", "")})
            elif t == "hotkey":
                r = _coagent_post("/hotkey", {"keys": d.get("keys", [])})
            elif t == "scroll":
                r = _coagent_post("/scroll", {"clicks": d.get("clicks", -3)})
            elif t == "drag":
                r = _coagent_post("/drag", {"x1": d["x1"], "y1": d["y1"],
                                            "x2": d["x2"], "y2": d["y2"],
                                            "button": d.get("button", "left")})
            else:
                r = {"error": f"unknown action type: {t}"}
            results.append({"step": i, "action": t, "result": r or {}})
        except Exception as e:
            results.append({"step": i, "action": t, "error": str(e)})
    return json.dumps({"actions_completed": i + 1, "results": results})

# ── System ────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_monitors() -> str:
    """Get monitor info."""
    data = _coagent_get("/screensize", no_cache=True)
    return json.dumps(data or {"error": "no monitor data"})

@mcp.tool()
async def get_cursor_position() -> str:
    """Get current cursor position."""
    data = _coagent_get("/cursor", no_cache=True)
    return json.dumps(data or {"error": "no cursor data"})

@mcp.tool()
async def get_coagent_status() -> str:
    """Get full CoAgent server status."""
    data = _coagent_get("/", no_cache=True)
    return json.dumps(data or {"error": "CoAgent unreachable"})

@mcp.tool()
async def emergency_stop() -> str:
    """EMERGENCY: Stop all mouse/keyboard input."""
    result = _coagent_post("/emergency/stop", {})
    return json.dumps(result or {"error": "stop failed"})

@mcp.tool()
async def emergency_resume() -> str:
    """Resume input after emergency_stop()."""
    result = _coagent_post("/emergency/resume", {})
    return json.dumps(result or {"error": "resume failed"})

# ── Screen wake ──────────────────────────────────────────────────────────

@mcp.tool()
async def wake_screen() -> str:
    """Wake the display from sleep/lock using Ctrl+Alt+Del, then Esc."""
    _coagent_post("/hotkey", {"keys": ["ctrl", "alt", "del"]})
    time.sleep(2)
    _coagent_post("/hotkey", {"keys": ["escape"]})
    time.sleep(1)
    return json.dumps({"status": "wake_signal_sent"})

# ── Launch app ───────────────────────────────────────────────────────────

@mcp.tool()
async def launch_app(path: str) -> str:
    """Launch application or open file."""
    if FAST_MODE:
        _lazy_imports()
    import subprocess
    try:
        subprocess.Popen(path, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return json.dumps({"status": "launched", "path": path})
    except Exception as e:
        return json.dumps({"error": str(e)})

# ── Run via command click_element ────────────────────────────────────────

@mcp.tool()
async def click_by_name(name: str) -> str:
    """Click a UI element by its name/label using UIA."""
    result = _coagent_post("/uia/click", {"name": name})
    return json.dumps(result or {"error": f"could not find/click '{name}'"})

# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--test" in sys.argv:
        print("Running self-test...")
        result = _coagent_get("/", no_cache=True)
        print(f"CoAgent ping: {'OK' if result and 'error' not in result else 'FAIL'}")
        print(f"PIL: {'OK' if HAS_PIL else 'MISSING'}")
        print(f"Tesseract: {'OK' if HAS_TESSERACT else 'MISSING'}")
        print(f"UIA: {'OK' if HAS_UIA else 'MISSING'}")
        print(f"Fast mode: {FAST_MODE}")
        sys.exit(0)
    if "--http" in sys.argv:
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
