"""CoAgent v7.0 — Feature Module

Adds:
1. Agent Cursor Overlay — shows animated arrow on screen before each click
2. Element-Indexed UIA Actions — click/find by stable UIA element index
3. Stabilization / Wait-for-Element — waits until UI element appears or times out
4. Session Recording — records action trajectories to disk for debugging

Integrates with cua-driver MCP bridge for cursor overlay when available,
or falls back to a simple cursor overlay drawn via pywinauto.
"""

import json
import os
import threading
import time
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Optional

import ctypes
from ctypes import wintypes

# ── Agent Cursor Overlay ──────────────────────────────────────────────
# Animated arrow that moves to click position before an action fires.
# Uses a transparent overlay window (WS_EX_LAYERED + WS_EX_TRANSPARENT).

_CURSOR_ENABLED = True
_CURSOR_COLOR = 0xFF4400  # Default orange-red
_CURSOR_SIZE = 48
_CURSOR_WINDOW = None
_CURSOR_LOCK = threading.Lock()
_CURSOR_HWND = None
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WS_POPUP = 0x80000000
_LWA_ALPHA = 0x00000002

# Cursor animation constants
_CURSOR_FADE_STEPS = 8
_CURSOR_DWELL_MS = 120
_CURSOR_ARC_SIZE = 15  # pixels of arc in the path
_CURSOR_GLIDE_MS = 60   # ms per step of animation

def _ensure_cursor_window():
    """Create the transparent overlay window for the agent cursor."""
    global _CURSOR_HWND
    if _CURSOR_HWND:
        try:
            if ctypes.windll.user32.IsWindow(_CURSOR_HWND):
                return _CURSOR_HWND
        except:
            pass
    try:
        hwnd = ctypes.windll.user32.CreateWindowExW(
            _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST,
            "STATIC", None,
            _WS_POPUP,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        if hwnd:
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 200, _LWA_ALPHA)
            ctypes.windll.user32.ShowWindow(hwnd, 8)  # SW_SHOWNA
            _CURSOR_HWND = hwnd
            return hwnd
    except:
        pass
    return None

def _destroy_cursor_window():
    """Destroy the cursor overlay window."""
    global _CURSOR_HWND
    if _CURSOR_HWND:
        try:
            ctypes.windll.user32.DestroyWindow(_CURSOR_HWND)
        except:
            pass
        _CURSOR_HWND = None

def set_cursor_enabled(enabled: bool):
    """Enable or disable the agent cursor overlay."""
    global _CURSOR_ENABLED
    with _CURSOR_LOCK:
        _CURSOR_ENABLED = enabled
        if not enabled:
            _destroy_cursor_window()
    return {"cursor_enabled": enabled}

def set_cursor_style(color: str = "#FF4400", size: int = 48):
    """Change cursor appearance."""
    global _CURSOR_COLOR, _CURSOR_SIZE
    with _CURSOR_LOCK:
        _CURSOR_COLOR = color
        _CURSOR_SIZE = max(16, min(64, size))
    return {"color": _CURSOR_COLOR, "size": _CURSOR_SIZE}

def show_cursor_at(x: int, y: int):
    """Show a visual cursor indicator at screen coordinates (x, y).
    
    Uses a simple Windows popup window as a fallback indicator.
    For the full animated arrow, cua-driver's overlay is preferred.
    """
    if not _CURSOR_ENABLED:
        return False
    try:
        hwnd = _ensure_cursor_window()
        if not hwnd:
            return False
        s = _CURSOR_SIZE
        ctypes.windll.user32.SetWindowPos(hwnd, -1, x - s//2, y - s//2, s, s, 0x0010)
        return True
    except:
        return False

def animate_cursor_to(x: int, y: int):
    """Animate cursor from current position to (x, y) with arc.
    
    Uses step-wise movement for visual feedback.
    Only works when cua-driver overlay is not available.
    """
    if not _CURSOR_ENABLED:
        return
    # Get current cursor position for animation start point
    try:
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        cx, cy = pt.x, pt.y
        
        import math
        steps = max(5, int(math.dist((cx, cy), (x, y)) / 20))
        steps = min(steps, 20)
        
        for i in range(1, steps + 1):
            t = i / steps
            # Linear interpolation with slight arc
            ix = cx + (x - cx) * t
            iy = cy + (y - cy) * t - _CURSOR_ARC_SIZE * math.sin(t * math.pi)
            show_cursor_at(int(ix), int(iy))
            time.sleep(_CURSOR_GLIDE_MS / 1000)
    except:
        show_cursor_at(x, y)


# ── Element-Indexed UIA Actions ──────────────────────────────────────
# Replace pixel-based clicking with "find element by name/text/automation_id"
# → click via InvokePattern. More reliable on obscured windows.

def _get_engine():
    """Import and return the UIA engine module."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import uia_engine as ue
    return ue

def uia_find_by_name(name: str) -> list:
    """Find UIA elements by name (partial match). Returns list of element info dicts."""
    ue = _get_engine()
    if not ue.UIA_READY:
        return []
    try:
        return ue.uia_find_by_name(name)
    except AttributeError:
        # Fallback: do inline search
        return _fallback_find(name)

def uia_find_by_automation_id(aid: str) -> list:
    """Find UIA elements by automation_id. Returns list of element info dicts."""
    ue = _get_engine()
    if not ue.UIA_READY:
        return []
    try:
        return ue.uia_find_by_automation_id(aid)
    except AttributeError:
        return _fallback_find(aid, mode="aid")

def uia_find_by_control_type(ctype: str) -> list:
    """Find UIA elements by control type (Button, Edit, List, etc.)."""
    ue = _get_engine()
    if not ue.UIA_READY:
        return []
    return _fallback_find(ctype, mode="ctype")

def _fallback_find(query: str, mode: str = "name"):
    """Inline fallback UIA search when engine's find function isn't exposed."""
    try:
        from pywinauto import Desktop as PyWinDesktop
        desktop = PyWinDesktop(backend="uia")
        results = []
        seen = set()
        for win in desktop.windows():
            for child in win.descendants():
                try:
                    info = child.element_info
                    if mode == "name" and query.lower() in (info.name or "").lower():
                        key = (info.automation_id or "", info.control_type or "", info.name or "")
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "name": info.name or "",
                                "control_type": info.control_type or "",
                                "automation_id": info.automation_id or "",
                                "class_name": info.class_name or "",
                                "enabled": True,
                                "visible": True,
                            })
                    elif mode == "aid" and query.lower() in (info.automation_id or "").lower():
                        key = (info.automation_id or "", info.control_type or "")
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "name": info.name or "",
                                "control_type": info.control_type or "",
                                "automation_id": info.automation_id or "",
                                "class_name": info.class_name or "",
                            })
                    elif mode == "ctype" and query.lower() == (info.control_type or "").lower():
                        key = (info.control_type or "", info.name or "")
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "name": info.name or "",
                                "control_type": info.control_type or "",
                                "automation_id": info.automation_id or "",
                                "class_name": info.class_name or "",
                            })
                except:
                    pass
        return results
    except Exception as e:
        return [{"error": str(e)}]

def uia_click_element_by_name(name: str) -> dict:
    """Click the first UIA element whose name contains the given text.
    
    Uses InvokePattern or click_input — works even when window is obscured.
    Returns success/failure dict.
    """
    ue = _get_engine()
    try:
        return ue.uia_click_element(name)
    except (AttributeError, Exception) as e:
        return {"success": False, "error": str(e)}

def uia_click_element_by_index(index: int) -> dict:
    """Click the Nth interactable UIA element.
    
    Indexes all interactable elements across all windows.
    """
    ue = _get_engine()
    try:
        return ue.uia_click_element(index)
    except (AttributeError, Exception) as e:
        return {"success": False, "error": str(e)}

def uia_get_window_tree() -> dict:
    """Get a clean tree of all UIA windows with their interactable elements.
    
    Returns structured tree suitable for rendering in a dashboard.
    """
    ue = _get_engine()
    snap = ue.uia_snapshot(timeout=5)
    return snap


# ── Stabilization / Wait-for-Element ─────────────────────────────────
# Waits until a UI element appears in the accessibility tree,
# or until a timeout expires.

def wait_for_element(
    query: str,
    mode: str = "name",
    timeout: float = 10.0,
    interval: float = 0.5
) -> dict:
    """Wait until a UIA element matching the query appears.
    
    Args:
        query: Text to search for
        mode: 'name' | 'automation_id' | 'control_type'
        timeout: Max seconds to wait
        interval: Poll interval in seconds
        
    Returns:
        dict with 'found' (bool), 'element' (dict), 'elapsed' (float)
    """
    start = time.time()
    while time.time() - start < timeout:
        if mode == "name":
            results = uia_find_by_name(query)
        elif mode == "automation_id":
            results = uia_find_by_automation_id(query)
        elif mode == "control_type":
            results = uia_find_by_control_type(query)
        else:
            return {"found": False, "error": f"Unknown mode: {mode}"}
        
        if results and "error" not in results[0]:
            return {
                "found": True,
                "element": results[0],
                "count": len(results),
                "elapsed": round(time.time() - start, 2)
            }
        time.sleep(interval)
    
    elapsed = round(time.time() - start, 2)
    return {"found": False, "elapsed": elapsed, "error": f"Element '{query}' not found in {elapsed}s"}

def wait_for_element_gone(
    query: str,
    mode: str = "name",
    timeout: float = 10.0,
    interval: float = 0.5
) -> dict:
    """Wait until a UIA element matching the query DISAPPEARS.
    
    Useful for waiting for loading spinners, dialogs to close, etc.
    """
    start = time.time()
    while time.time() - start < timeout:
        results = uia_find_by_name(query) if mode == "name" else uia_find_by_automation_id(query)
        if not results or "error" in (results[0] if results else {}):
            return {
                "gone": True,
                "elapsed": round(time.time() - start, 2)
            }
        time.sleep(interval)
    
    elapsed = round(time.time() - start, 2)
    return {"gone": False, "elapsed": elapsed, "error": f"Element '{query}' still present after {elapsed}s"}

def stabilize(max_wait: float = 5.0, min_stable: float = 0.5) -> dict:
    """Wait for the desktop to stop changing (UI stabilizes).
    
    Polls the UIA tree until it's stable for `min_stable` seconds.
    Useful before taking a screenshot to ensure it captures the final state.
    """
    ue = _get_engine()
    last_hash = None
    stable_since = None
    start = time.time()
    
    while time.time() - start < max_wait:
        snap = ue.uia_snapshot(timeout=2)
        tree = snap.get("tree", {})
        current_hash = hash(str(tree.get("children", []))[:2000])
        
        if last_hash is not None and current_hash == last_hash:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= min_stable:
                return {
                    "stable": True,
                    "elapsed": round(time.time() - start, 2),
                    "stable_duration": min_stable
                }
        else:
            stable_since = None
        
        last_hash = current_hash
        time.sleep(0.2)
    
    return {
        "stable": False,
        "elapsed": round(time.time() - start, 2),
        "error": f"Desktop did not stabilize within {max_wait}s"
    }


# ── Session Recording ────────────────────────────────────────────────
# Records action trajectories to disk for debugging/replay.

_RECORDING_ACTIVE = False
_RECORDING_DIR = None
_RECORDING_TURN = 0
_RECORDING_LOCK = threading.Lock()
_RECORDING_VIDEO = False

_MAX_KEEP_SESSIONS = 10

def _cleanup_old_sessions(rec_dir: Path, max_keep: int = 10):
    """Delete oldest session directories beyond max_keep."""
    try:
        if not rec_dir.exists():
            return
        sessions = sorted(rec_dir.glob("session_*"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
        while len(sessions) > max_keep:
            oldest = sessions.pop(0)
            import shutil
            shutil.rmtree(oldest, ignore_errors=True)
    except Exception:
        pass

def start_recording(output_dir: str = None, record_video: bool = False) -> dict:
    """Start recording action trajectories.
    
    Args:
        output_dir: Directory to save recordings (default: ~/Desktop/CoAgent_Recordings)
        record_video: Also record screen video (requires ffmpeg)
        
    Returns:
        dict with status and output directory
    """
    global _RECORDING_ACTIVE, _RECORDING_DIR, _RECORDING_TURN, _RECORDING_VIDEO
    
    with _RECORDING_LOCK:
        if _RECORDING_ACTIVE:
            return {"status": "already_active", "dir": str(_RECORDING_DIR)}
        
        if output_dir:
            rec_dir = Path(output_dir)
        else:
            rec_dir = Path.home() / "Desktop" / "CoAgent_Recordings"
        
        # Create timestamped session folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = rec_dir / f"session_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # v7.0: Auto-cleanup — keep max 10 sessions, delete oldest
        _cleanup_old_sessions(rec_dir, max_keep=_MAX_KEEP_SESSIONS)
        
        _RECORDING_DIR = session_dir
        _RECORDING_TURN = 0
        _RECORDING_ACTIVE = True
        _RECORDING_VIDEO = record_video
        
        # Save session metadata
        meta = {
            "started": datetime.now().isoformat(),
            "record_video": record_video,
            "turns": 0
        }
        (session_dir / "session.json").write_text(json.dumps(meta, indent=2))
        
        return {
            "status": "started",
            "dir": str(session_dir),
            "record_video": record_video
        }

def record_action(action_type: str, data: dict, result: dict = None):
    """Record a single action to the current recording session.
    
    Called by _execute_action after each action completes.
    """
    with _RECORDING_LOCK:
        if not _RECORDING_ACTIVE:
            return
        
        _RECORDING_TURN += 1
        turn_dir = _RECORDING_DIR / f"turn-{_RECORDING_TURN:05d}"
        turn_dir.mkdir(exist_ok=True)
        
        # Save action.json
        action_record = {
            "turn": _RECORDING_TURN,
            "timestamp": datetime.now().isoformat(),
            "type": action_type,
            "data": data,
            "result": result or {}
        }
        (turn_dir / "action.json").write_text(json.dumps(action_record, indent=2))
        
        # Try to grab a screenshot for this turn
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(str(turn_dir / "screenshot.png"))
            
            # If it's a click action, save click.png with dot
            if action_type in ("click", "doubleclick", "rightclick", "drag") and data:
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                x = data.get("x", data.get("x1", 0))
                y = data.get("y", data.get("y1", 0))
                r = 5
                draw.ellipse([x-r, y-r, x+r, y+r], fill="red")
                img.save(str(turn_dir / "click.png"))
        except:
            pass
        
        # Update session metadata
        meta = json.loads((_RECORDING_DIR / "session.json").read_text())
        meta["turns"] = _RECORDING_TURN
        meta["last_action"] = action_record["timestamp"]
        (_RECORDING_DIR / "session.json").write_text(json.dumps(meta, indent=2))

def stop_recording() -> dict:
    """Stop recording and return summary."""
    global _RECORDING_ACTIVE, _RECORDING_DIR, _RECORDING_TURN
    
    with _RECORDING_LOCK:
        if not _RECORDING_ACTIVE:
            return {"status": "not_recording"}
        
        summary = {
            "status": "stopped",
            "dir": str(_RECORDING_DIR),
            "turns": _RECORDING_TURN,
            "duration": None
        }
        
        # Update final metadata
        meta_path = _RECORDING_DIR / "session.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["ended"] = datetime.now().isoformat()
            meta["turns"] = _RECORDING_TURN
            meta_path.write_text(json.dumps(meta, indent=2))
            
            if meta.get("started"):
                from datetime import datetime as dt
                try:
                    started = dt.fromisoformat(meta["started"])
                    ended = dt.fromisoformat(meta["ended"])
                    summary["duration_seconds"] = (ended - started).total_seconds()
                except:
                    pass
        
        _RECORDING_ACTIVE = False
        return summary

def get_recording_state() -> dict:
    """Get current recording state."""
    with _RECORDING_LOCK:
        return {
            "active": _RECORDING_ACTIVE,
            "dir": str(_RECORDING_DIR) if _RECORDING_DIR else None,
            "turns": _RECORDING_TURN,
            "video": _RECORDING_VIDEO
        }


# ── UI Module Integration ────────────────────────────────────────────
# These functions are called by the Flask routes

def get_status() -> dict:
    """Get feature status summary."""
    rs = get_recording_state()
    return {
        "cursor_enabled": _CURSOR_ENABLED,
        "recording_active": rs["active"],
        "recording_turns": rs["turns"],
        "recording_dir": rs["dir"],
    }


# ── Route handlers (callable by Flask) ───────────────────────────────

def cursor_get_status():
    return {"enabled": _CURSOR_ENABLED, "color": _CURSOR_COLOR, "size": _CURSOR_SIZE}

def cursor_set_enabled(data: dict):
    enabled = data.get("enabled", True)
    return set_cursor_enabled(enabled)

def cursor_set_style(data: dict):
    return set_cursor_style(
        color=data.get("color", "#FF4400"),
        size=data.get("size", 48)
    )

def recording_start(data: dict):
    return start_recording(
        output_dir=data.get("dir"),
        record_video=data.get("video", False)
    )

def recording_stop():
    return stop_recording()

def recording_status():
    return get_recording_state()

def element_find(data: dict):
    query = data.get("query", "")
    mode = data.get("mode", "name")
    if mode == "name":
        return {"results": uia_find_by_name(query), "query": query, "mode": mode}
    elif mode == "automation_id":
        return {"results": uia_find_by_automation_id(query), "query": query, "mode": mode}
    elif mode == "control_type":
        return {"results": uia_find_by_control_type(query), "query": query, "mode": mode}
    return {"error": "Invalid mode", "valid": ["name", "automation_id", "control_type"]}

def element_click_by_name(data: dict):
    name = data.get("name", "")
    result = uia_click_element_by_name(name)
    return result

def element_click_by_index(data: dict):
    index = int(data.get("index", 0))
    result = uia_click_element_by_index(index)
    return result

def stabilize_action(data: dict):
    max_wait = float(data.get("max_wait", 5.0))
    min_stable = float(data.get("min_stable", 0.5))
    return stabilize(max_wait=max_wait, min_stable=min_stable)

def wait_element(data: dict):
    query = data.get("query", "")
    mode = data.get("mode", "name")
    timeout = float(data.get("timeout", 10.0))
    return wait_for_element(query, mode=mode, timeout=timeout)

def wait_element_gone(data: dict):
    query = data.get("query", "")
    mode = data.get("mode", "name")
    timeout = float(data.get("timeout", 10.0))
    return wait_for_element_gone(query, mode=mode, timeout=timeout)

def get_window_tree():
    return uia_get_window_tree()
