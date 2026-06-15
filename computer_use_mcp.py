#!/usr/bin/env python
"""
Hermes CoAgent - Windows Computer Use MCP Server
=================================================
Native Hermes MCP server that gives the agent full desktop control:
screenshot capture, SOM overlays, UIA tree, click/type/scroll/hotkey,
combined OCR+UIA element find, and drag support.

This is the Windows equivalent of macOS's cua-driver computer_use toolset.
No screenshots leave your machine - all vision analysis is local.

Usage:
  python computer_use_mcp.py          # stdio MCP (for Hermes mcp_servers)
  python computer_use_mcp.py --http   # HTTP SSE MCP server
  python computer_use_mcp.py --test   # Run self-test

Configuration (environment variables):
  COAGENT_URL=http://localhost:9123   # CoAgent HTTP server (default)
"""

import sys, os, json, base64, io, time, subprocess, threading, re, traceback
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from io import BytesIO

# ── MCP SDK ──────────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP, Context as MCPContext

# ── Image/OCR dependencies ───────────────────────────────────────────────
# These are optional - the server degrades gracefully without them
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

HAS_TESSERACT = False
try:
    import pytesseract
    # Check if tesseract is actually available
    try:
        pytesseract.get_tesseract_version()
        HAS_TESSERACT = True
    except:
        pass
except ImportError:
    pass

# ── UIA Engine (pywinauto) ───────────────────────────────────────────────
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

def _coagent_get(path: str) -> Optional[dict]:
    """GET request to CoAgent server."""
    try:
        req = urllib.request.Request(f"{COAGENT_URL}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def _coagent_post(path: str, data: dict) -> Optional[dict]:
    """POST request to CoAgent server."""
    try:
        req = urllib.request.Request(
            f"{COAGENT_URL}{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def _coagent_ping() -> bool:
    """Check if CoAgent server is running."""
    result = _coagent_get("/ping")
    return result is not None and result.get("status") == "ok"

# ── Local screenshot (fallback if CoAgent unavailable) ───────────────────
def _local_screenshot() -> Optional[bytes]:
    """Take screenshot using PowerShell (works from any session)."""
    try:
        cmd = (
            'Add-Type -AssemblyName System.Drawing; '
            'Add-Type -AssemblyName System.Windows.Forms; '
            '$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; '
            '$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; '
            '$g = [System.Drawing.Graphics]::FromImage($bmp); '
            '$g.CopyFromScreen($b.X, $b.Y, 0, 0, $b.Size); '
            '$ms = New-Object System.IO.MemoryStream; '
            '$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); '
            '[System.Convert]::ToBase64String($ms.ToArray()); '
            '$g.Dispose(); $bmp.Dispose()'
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        if result.returncode == 0 and len(result.stdout.strip()) > 500:
            return base64.b64decode(result.stdout.strip())
    except:
        pass
    return None

def _get_screenshot(force: bool = True) -> Optional[bytes]:
    """Get screenshot via CoAgent or fallback to local."""
    try:
        result = _coagent_get("/screenshot/base64" if not force else "/screen/base64")
        if result and "data" in result and result.get("size", 0) > 500:
            return base64.b64decode(result["data"])
    except:
        pass
    return _local_screenshot()

# ── UIA helpers ──────────────────────────────────────────────────────────
def _uia_element_rect(elem):
    try:
        r = elem.rectangle()
        return {"left": r.left, "top": r.top, "width": r.width(), "height": r.height()}
    except:
        return None

def _uia_snapshot_local(timeout: int = 8) -> dict:
    """Get UIA tree locally (no CoAgent dependency)."""
    if not HAS_UIA:
        return {"success": False, "error": "UIA not available"}
    result = {"success": False, "error": "timeout"}
    
    def _run():
        nonlocal result
        try:
            desktop = PyWinDesktop(backend="uia")
            elements = []
            for win in desktop.windows():
                try:
                    name = win.element_info.name or ""
                    ctrl_type = win.element_info.control_type or ""
                    rect = _uia_element_rect(win)
                    if name or ctrl_type:
                        elements.append({
                            "name": name,
                            "control_type": ctrl_type,
                            "automation_id": win.element_info.automation_id or "",
                            "class_name": win.element_info.class_name or "",
                            "rect": rect,
                            "center": [rect["left"] + rect["width"]//2, rect["top"] + rect["height"]//2] if rect else None
                        })
                except:
                    pass
            result = {"success": True, "elements": elements, "total": len(elements)}
        except Exception as e:
            result = {"success": False, "error": str(e)}
    
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result

def _uia_find_local(text: str) -> list:
    """Find elements by name substring locally."""
    if not HAS_UIA:
        return []
    results = []
    try:
        desktop = PyWinDesktop(backend="uia")
        needle = text.lower()
        for win in desktop.windows():
            try:
                name = win.element_info.name or ""
                if needle in name.lower():
                    rect = _uia_element_rect(win)
                    results.append({
                        "name": name,
                        "control_type": win.element_info.control_type or "",
                        "automation_id": win.element_info.automation_id or "",
                        "rect": rect,
                        "center": [rect["left"] + rect["width"]//2, rect["top"] + rect["height"]//2] if rect else None,
                        "confidence": 1.0
                    })
            except:
                pass
            try:
                for child in win.descendants():
                    try:
                        cname = child.element_info.name or ""
                        if needle in cname.lower():
                            rect = _uia_element_rect(child)
                            results.append({
                                "name": cname,
                                "control_type": child.element_info.control_type or "",
                                "automation_id": child.element_info.automation_id or "",
                                "rect": rect,
                                "center": [rect["left"] + rect["width"]//2, rect["top"] + rect["height"]//2] if rect else None,
                                "confidence": 0.9
                            })
                    except:
                        pass
            except:
                pass
    except:
        pass
    return results[:25]

# ── OCR helpers (local, free) ────────────────────────────────────────────
def _ocr_find_local(screenshot_bytes: bytes, text: str) -> list:
    """Find text on screen using Tesseract OCR."""
    if not HAS_TESSERACT or not HAS_PIL:
        return []
    results = []
    try:
        img = Image.open(BytesIO(screenshot_bytes))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if word and text.lower() in word.lower():
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                results.append({
                    "word": word,
                    "confidence": data["conf"][i],
                    "bbox": [x, y, w, h],
                    "center": [x + w//2, y + h//2]
                })
    except:
        pass
    return results

# ── SOM overlay (local, no CoAgent needed) ───────────────────────────────
def _som_overlay_local(screenshot_bytes: bytes) -> dict:
    """Create numbered SOM overlay on screenshot using UIA elements."""
    if not HAS_PIL:
        return {"success": False, "error": "PIL not available"}
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(BytesIO(screenshot_bytes)).convert("RGBA")
        sw, sh = img.size
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        # Get elements from UIA
        elements = []
        snap = _uia_snapshot_local(timeout=6)
        if snap.get("success"):
            for e in snap.get("elements", []):
                rect = e.get("rect")
                if rect and rect.get("width", 0) > 20 and rect.get("height", 0) > 20:
                    if rect["width"] < sw // 2 and rect["height"] < sh // 2:
                        elements.append(e)
        
        elements = elements[:50]
        labeled = []
        
        for i, elem in enumerate(elements):
            rect = elem.get("rect")
            if not rect:
                continue
            bx, by, bw, bh = rect["left"], rect["top"], rect["width"], rect["height"]
            label = str(i + 1)
            center = [bx + bw // 2, by + bh // 2]
            
            # Draw box
            draw.rectangle([bx, by, bx + bw, by + bh], outline="#FF4444", width=2)
            
            # Draw label bg
            bbox = draw.textbbox((bx, by - 18), label, font=font)
            draw.rectangle(bbox, fill="#FF4444")
            draw.text((bx + 2, by - 18), label, fill="white", font=font)
            
            labeled.append({
                "index": i + 1,
                "name": elem.get("name", ""),
                "control_type": elem.get("control_type", ""),
                "bbox": [bx, by, bw, bh],
                "center": center
            })
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        
        return {
            "success": True,
            "labeled_screenshot": base64.b64encode(buf.getvalue()).decode(),
            "elements": labeled,
            "total": len(labeled)
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

# ── Combined find (OCR + UIA) ────────────────────────────────────────────
def _find_on_screen(text: str) -> dict:
    """Find element using both UIA and OCR, return best matches with coords."""
    results = {"text": text, "matches": [], "method": "combined"}
    
    # Method 1: UIA (free, fast, structured)
    uia_results = _uia_find_local(text)
    for r in uia_results:
        results["matches"].append({
            "method": "uia",
            "name": r.get("name", ""),
            "control_type": r.get("control_type", ""),
            "bbox": r.get("rect"),
            "center": r.get("center"),
            "confidence": r.get("confidence", 1.0)
        })
    
    # Method 2: OCR (free, finds visible text)
    screenshot = _get_screenshot()
    if screenshot:
        ocr_results = _ocr_find_local(screenshot, text)
        for r in ocr_results:
            results["matches"].append({
                "method": "ocr",
                "name": r.get("word", ""),
                "bbox": r.get("bbox"),
                "center": r.get("center"),
                "confidence": r.get("confidence", 0.5)
            })
    
    # Sort by confidence descending
    results["matches"].sort(key=lambda m: m.get("confidence", 0), reverse=True)
    results["total"] = len(results["matches"])
    results["found"] = results["total"] > 0
    return results

# ── Action helpers ───────────────────────────────────────────────────────
def _click_coords(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """Click at coordinates via CoAgent."""
    resp = _coagent_post("/mouse/move", {"x": x, "y": y})
    if resp and "error" not in resp:
        time.sleep(0.05)
        resp = _coagent_post("/mouse/click", {"button": button, "clicks": clicks})
    return resp or {"error": "CoAgent unreachable"}

def _type_text(text: str) -> dict:
    """Type text via CoAgent."""
    return _coagent_post("/key/type", {"text": text}) or {"error": "CoAgent unreachable"}

def _press_keys(keys: list) -> dict:
    """Press key combination via CoAgent."""
    return _coagent_post("/key/press", {"keys": keys}) or {"error": "CoAgent unreachable"}

def _scroll_screen(clicks: int = -3) -> dict:
    """Scroll via CoAgent."""
    return _coagent_post("/mouse/scroll", {"clicks": clicks}) or {"error": "CoAgent unreachable"}

def _drag_mouse(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> dict:
    """Drag from (x1,y1) to (x2,y2) via CoAgent."""
    return _coagent_post("/mouse/drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": button}) or {"error": "CoAgent unreachable"}

def _click_element(target) -> dict:
    """Click a UI element by index or name via CoAgent."""
    if isinstance(target, int):
        return _coagent_post("/uia/click", {"index": target}) or {"error": "CoAgent unreachable"}
    return _coagent_post("/uia/click", {"name": target}) or {"error": "CoAgent unreachable"}

def _chain_actions(actions: list) -> dict:
    """Execute multiple actions in sequence via CoAgent."""
    return _coagent_post("/chain", {"actions": actions}) or {"error": "CoAgent unreachable"}

def _activate_window(title: str) -> dict:
    """Bring window to front by title."""
    return _coagent_post("/windows/activate", {"title": title}) or {"error": "CoAgent unreachable"}

def _list_windows() -> list:
    """List all open windows."""
    result = _coagent_get("/windows")
    return result.get("windows", []) if result else []

def _launch_app(path: str) -> dict:
    """Launch an application."""
    return _coagent_post("/app/open", {"path": path}) or {"error": "CoAgent unreachable"}

# ═══════════════════════════════════════════════════════════════════════════
# MCP Server
# ═══════════════════════════════════════════════════════════════════════════

mcp = FastMCP("Hermes Windows Computer Use")

# ── Resources ────────────────────────────────────────────────────────────

@mcp.resource("status://computer-use")
def get_status() -> str:
    """Get CoAgent and MCP server status."""
    coagent_ok = _coagent_ping()
    return json.dumps({
        "coagent_running": coagent_ok,
        "uia_available": HAS_UIA,
        "ocr_available": HAS_TESSERACT,
        "pil_available": HAS_PIL,
        "coagent_url": COAGENT_URL,
        "version": "1.0.0"
    })

# ── Tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def ping() -> dict:
    """Check if the MCP server and CoAgent are alive."""
    coagent = _coagent_ping()
    return {
        "mcp": "ok",
        "coagent": coagent,
        "uia": HAS_UIA,
        "ocr": HAS_TESSERACT
    }

@mcp.tool()
def capture(mode: str = "som") -> dict:
    """
    Capture the current screen with a Set-of-Mark (SOM) overlay showing
    numbered interactable elements. Like macOS computer_use(action='capture', mode='som').
    
    Args:
        mode: 'som' for numbered overlay, 'raw' for plain screenshot, 'uia' for UIA tree only
    
    Returns:
        Dict with labeled_screenshot (base64 PNG), elements list with coords,
        or plain screenshot data.
    """
    if mode == "uia":
        # UIA tree only - no screenshot
        result = _uia_snapshot_local()
        if result.get("success"):
            return result
        # Try via CoAgent
        return _coagent_get("/uia/snapshot") or {"error": "UIA unavailable"}
    
    screenshot = _get_screenshot(force=True)
    if not screenshot:
        return {"error": "Could not capture screenshot. Is the CoAgent server running?"}
    
    if mode == "som":
        result = _som_overlay_local(screenshot)
        if result.get("success"):
            return result
        # Fallback: try CoAgent
        coagent_result = _coagent_get("/som/screenshot")
        if coagent_result and coagent_result.get("success"):
            return coagent_result
    
    # Raw screenshot
    return {
        "success": True,
        "screenshot": base64.b64encode(screenshot).decode(),
        "format": "png",
        "size": len(screenshot)
    }

@mcp.tool()
def som_screenshot() -> dict:
    """
    Get a screenshot with numbered SOM overlays on every interactable element.
    Alias for capture(mode='som'). Returns base64 PNG + element list.
    """
    return capture(mode="som")

@mcp.tool()
def screenshot() -> dict:
    """
    Get a plain screenshot (no overlays). Returns base64 PNG data.
    """
    return capture(mode="raw")

@mcp.tool()
def find_on_screen(text: str) -> dict:
    """
    Find an element on screen by name using both UIA (accessibility tree)
    and OCR. Returns all matches with coordinates. No screenshots needed.
    
    Args:
        text: Text to search for (button label, window title, etc.)
    
    Returns:
        Dict with matches list, each containing method, name, center coords, confidence.
    """
    return _find_on_screen(text)

@mcp.tool()
def click_element(index: int) -> dict:
    """
    Click a UI element by its SOM index (from capture/som_screenshot output).
    
    Args:
        index: Element index from SOM overlay (1-based numbering)
    
    Returns:
        Dict with success status
    """
    return _click_element(index)

@mcp.tool()
def click_by_name(name: str) -> dict:
    """
    Click a UI element by its name/label. Searches UIA tree for matching element.
    
    Args:
        name: Element name or label text to search for
    
    Returns:
        Dict with success/failure and what was clicked
    """
    # First, find the element
    results = _find_on_screen(name)
    
    # Try UIA click first
    uia_result = _click_element(name)
    if uia_result.get("success"):
        return uia_result
    
    # Fall back to center of first match
    for match in results.get("matches", []):
        center = match.get("center")
        if center:
            click_result = _click_coords(center[0], center[1])
            if click_result and "error" not in click_result:
                return {"success": True, "method": "coords", "name": name, "x": center[0], "y": center[1]}
    
    return {"success": False, "error": f"Could not find or click '{name}'"}

@mcp.tool()
def click(x: int, y: int, button: str = "left") -> dict:
    """
    Click at specific screen coordinates.
    
    Args:
        x: X coordinate
        y: Y coordinate
        button: Mouse button (left, right, middle)
    
    Returns:
        Dict with success status
    """
    return _click_coords(x, y, button)

@mcp.tool()
def double_click(x: int, y: int, button: str = "left") -> dict:
    """
    Double-click at specific screen coordinates.
    
    Args:
        x: X coordinate
        y: Y coordinate
        button: Mouse button (left, right, middle)
    """
    return _click_coords(x, y, button, clicks=2)

@mcp.tool()
def right_click(x: int, y: int) -> dict:
    """
    Right-click at specific screen coordinates.
    
    Args:
        x: X coordinate
        y: Y coordinate
    """
    return _click_coords(x, y, "right")

@mcp.tool()
def move_mouse(x: int, y: int) -> dict:
    """
    Move mouse to coordinates.
    
    Args:
        x: Target X coordinate
        y: Target Y coordinate
    """
    return _coagent_post("/mouse/move", {"x": x, "y": y}) or {"error": "CoAgent unreachable"}

@mcp.tool()
def type_text(text: str) -> dict:
    """
    Type text at the current cursor position.
    
    Args:
        text: Text to type
    """
    return _type_text(text)

@mcp.tool()
def press_key(keys: list) -> dict:
    """
    Press a key combination. Examples:
    - ['ctrl', 'c'] for copy
    - ['alt', 'tab'] for app switch
    - ['win', 'r'] for run dialog
    - ['enter'], ['escape'], ['tab']
    
    Args:
        keys: List of key names to press simultaneously
    """
    return _press_keys(keys)

@mcp.tool()
def scroll(clicks: int = -3) -> dict:
    """
    Scroll the mouse wheel.
    
    Args:
        clicks: Number of scroll clicks (negative = down, positive = up)
    """
    return _scroll_screen(clicks)

@mcp.tool()
def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> dict:
    """
    Drag from one point to another.
    
    Args:
        x1: Start X
        y1: Start Y
        x2: End X
        y2: End Y
        button: Mouse button (left, right)
    """
    return _drag_mouse(x1, y1, x2, y2, button)

@mcp.tool()
def activate_window(title: str) -> dict:
    """
    Bring a window to the foreground by its title.
    
    Args:
        title: Window title (substring match)
    """
    return _activate_window(title)

@mcp.tool()
def list_windows() -> list:
    """
    List all open windows with their titles and positions.
    """
    return _list_windows()

@mcp.tool()
def launch_app(path: str) -> dict:
    """
    Launch an application or open a file.
    
    Args:
        path: Path to executable or file (e.g. 'notepad.exe', 'C:\\path\\to\\app.exe')
    """
    return _launch_app(path)

@mcp.tool()
def get_cursor_position() -> dict:
    """Get the current mouse cursor position."""
    result = _coagent_get("/cursor/pos")
    return result or {"error": "CoAgent unreachable"}

@mcp.tool()
def run_command(cmd: str, timeout: int = 30) -> dict:
    """
    Run a shell command.
    
    Args:
        cmd: Command to execute
        timeout: Timeout in seconds (default 30)
    """
    return _coagent_post("/app/run", {"cmd": cmd, "timeout": timeout}) or {"error": "CoAgent unreachable"}

@mcp.tool()
def get_monitors() -> dict:
    """Get information about connected monitors."""
    return _coagent_get("/monitors") or {"error": "CoAgent unreachable"}

@mcp.tool()
def emergency_stop() -> dict:
    """
    EMERGENCY: Stop all mouse/keyboard input and clear the action queue.
    Use when the agent is doing something wrong/destructive.
    Resume with emergency_resume().
    """
    return _coagent_post("/emergency/stop", {}) or {"error": "CoAgent unreachable"}

@mcp.tool()
def emergency_resume() -> dict:
    """Resume input after emergency_stop()."""
    return _coagent_post("/emergency/resume", {}) or {"error": "CoAgent unreachable"}

@mcp.tool()
def get_uia_tree() -> dict:
    """
    Get the full UIA accessibility tree of all windows.
    Returns structured data of every control with name, type, position.
    """    
    result = _uia_snapshot_local(timeout=10)
    if result.get("success"):
        return result
    return _coagent_get("/uia/snapshot") or {"error": "UIA unavailable"}

@mcp.tool()
def chain(actions: list) -> dict:
    """
    Execute multiple actions atomically in sequence.
    Each action is {type, data} where type is one of:
    move, click, doubleclick, rightclick, type, hotkey, scroll, drag
    
    Example:
    [
        {"type": "move", "data": {"x": 100, "y": 200}},
        {"type": "click", "data": {"button": "left"}},
        {"type": "type", "data": {"text": "hello world"}}
    ]
    
    Args:
        actions: List of action dicts to execute in order
    """
    return _chain_actions(actions)

@mcp.tool()
def get_coagent_status() -> dict:
    """Get full status of the CoAgent server including queue, actions, and emergency state."""
    status = _coagent_get("/ping")
    stats = _coagent_get("/stats")
    result = {"ping": status or {"error": "unreachable"}}
    if stats:
        result["stats"] = stats
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Windows Computer Use MCP Server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP SSE server instead of stdio")
    parser.add_argument("--port", type=int, default=9124, help="HTTP port (default: 9124)")
    parser.add_argument("--test", action="store_true", help="Run self-test and exit")
    args = parser.parse_args()
    
    if args.test:
        print("=== Hermes Windows Computer Use MCP - Self Test ===\n")
        print(f"PIL: {HAS_PIL}")
        print(f"Tesseract: {HAS_TESSERACT}")
        print(f"UIA (pywinauto): {HAS_UIA}")
        print(f"CoAgent URL: {COAGENT_URL}")
        print(f"CoAgent ping: {_coagent_ping()}")
        
        print("\n--- Status Resource ---")
        print(get_status())
        
        print("\n--- Screenshot Test ---")
        img = _get_screenshot()
        print(f"Screenshot: {'OK' if img else 'FAIL'} ({len(img)} bytes)" if img else "FAIL")
        
        print("\n--- UIA Test ---")
        snap = _uia_snapshot_local(timeout=6)
        print(f"UIA: {'OK' if snap.get('success') else 'FAIL'} ({snap.get('total', 0)} elements)")
        
        print("\nDone.")
        sys.exit(0)
    
    print(f"Hermes Windows Computer Use MCP Server")
    print(f"  CoAgent: {COAGENT_URL}")
    print(f"  UIA: {'YES' if HAS_UIA else 'NO'}")
    print(f"  OCR: {'YES' if HAS_TESSERACT else 'NO'}")
    print(f"  PIL: {'YES' if HAS_PIL else 'NO'}")
    
    if args.http:
        print(f"  HTTP mode on port {args.port}")
        mcp.run(transport="sse", host="0.0.0.0", port=args.port)
    else:
        print(f"  Stdio mode (for Hermes mcp_servers)")
        mcp.run(transport="stdio")
