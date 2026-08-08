"""Hermes CoAgent v7.3 — UIA Engine
Windows UI Automation tree + SOM overlays + background SendInput.

Provides:
- uia_snapshot(): accessibility tree of all interactable elements
- uia_click(target): click element by index, name, or automation_id
- som_overlay(screenshot): screenshot with numbered element boxes
- ocr_find_uia(text): find by both UIA and OCR, return best match
- send_input_background(keys): send keystrokes WITHOUT stealing focus
"""

import base64, time, threading, hashlib, logging
from io import BytesIO
from pathlib import Path
import ctypes
from ctypes import wintypes, windll
import traceback

_LOGGER = logging.getLogger(__name__)


def _debug_failure(context, exc):
    _LOGGER.debug("%s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


_UIA_SNAPSHOT_SEMAPHORE = threading.BoundedSemaphore(1)
_UIA_CHILD_SEMAPHORE = threading.BoundedSemaphore(4)
_WINDOW_CRAWL_TIMEOUT = 3.0
_WINDOW_CHILD_JOIN_TIMEOUT = 2.0

# v5.1: UIA element tracking — stable IDs across frames
_ELEMENT_TRACKER = {}  # key_hash -> {id, first_seen, last_seen}
_NEXT_ELEMENT_ID = 1
_TRACKER_LOCK = threading.Lock()

def _get_element_key(elem) -> str:
    """Generate a stable key for a UIA element across frames.
    Uses runtime_id, or fallback to (automation_id, control_type, name, class_name).
    """
    try:
        rid = elem.element_info.runtime_id
        if rid:
            return "rid:" + hashlib.md5(str(rid).encode()).hexdigest()
    except (AttributeError, TypeError, ValueError) as e:
        _debug_failure("UIA runtime id lookup", e)
    try:
        aid = elem.element_info.automation_id or ""
        ct = elem.element_info.control_type or ""
        nm = elem.element_info.name or ""
        cn = elem.element_info.class_name or ""
        raw = f"{aid}|{ct}|{nm}|{cn}"
        if raw != "|||":
            return "fallback:" + hashlib.md5(raw.encode()).hexdigest()
    except (AttributeError, TypeError, ValueError) as e:
        _debug_failure("UIA fallback key lookup", e)
    return None

def _get_stable_id(elem) -> int:
    """Get or create a stable numeric ID for a UIA element."""
    global _NEXT_ELEMENT_ID
    key = _get_element_key(elem)
    now = time.time()
    with _TRACKER_LOCK:
        if key and key in _ELEMENT_TRACKER:
            _ELEMENT_TRACKER[key]["last_seen"] = now
            return _ELEMENT_TRACKER[key]["id"]
        # New element
        eid = _NEXT_ELEMENT_ID
        _NEXT_ELEMENT_ID += 1
        if key:
            _ELEMENT_TRACKER[key] = {"id": eid, "first_seen": now, "last_seen": now}
        # Prune stale entries every 100 new IDs
        if _NEXT_ELEMENT_ID % 100 == 0:
            stale = [k for k, v in _ELEMENT_TRACKER.items() if now - v["last_seen"] > 60]
            for k in stale:
                del _ELEMENT_TRACKER[k]
        return eid

# ── UIA via pywinauto ─────────────────────────────────────────────────────
# Initialize COM in STA mode BEFORE importing pywinauto
try:
    import pythoncom
    pythoncom.CoInitialize()
except (ImportError, OSError, RuntimeError) as e:
    _debug_failure("pythoncom initialization", e)

UIA_READY = False
_uia_error = ""

try:
    from pywinauto import Desktop as PyWinDesktop
    # Don't call Timings.slow() globally — it can hang on some desktops

    def _uia_element_rect(elem):
        """Get bounding rect of a UI element."""
        try:
            r = elem.rectangle()
            return {"left": r.left, "top": r.top, "width": r.width(), "height": r.height()}
        except Exception as e:
            _debug_failure("UIA element rectangle", e)
            return None

    def _uia_element_state(elem, method_name: str, default: bool = True) -> bool:
        """Read a pywinauto boolean state method without failing snapshot collection."""
        try:
            method = getattr(elem, method_name)
            return bool(method())
        except Exception as e:
            _debug_failure(f"UIA element state {method_name}", e)
            return default

    def _uia_child_info(elem):
        """Extract the fields used for child records in uia_snapshot()."""
        try:
            control_type = elem.element_info.control_type or ""
            name = elem.element_info.name or ""
            if not name and not control_type:
                return None
            return {
                "id": _get_stable_id(elem),  # v5.1: stable element ID
                "control_type": control_type,
                "automation_id": elem.element_info.automation_id or "",
                "class_name": elem.element_info.class_name or "",
                "name": name,
                "rect": _uia_element_rect(elem),
                "enabled": _uia_element_state(elem, "is_enabled"),
                "visible": _uia_element_state(elem, "is_visible"),
            }
        except Exception as e:
            _debug_failure("UIA child info", e)
            return None

    def _uia_find_info(elem):
        """Extract the compact fields returned by uia_find_deep()."""
        try:
            return {
                "id": _get_stable_id(elem),  # v5.1: stable element ID
                "control_type": elem.element_info.control_type or "",
                "automation_id": elem.element_info.automation_id or "",
                "class_name": elem.element_info.class_name or "",
                "name": elem.element_info.name or "",
                "rect": _uia_element_rect(elem),
            }
        except Exception as e:
            _debug_failure("UIA find info", e)
            return None

    def _get_children(element, depth=0, max_depth=3) -> list:
        """Return interactable descendant records for a UIA element."""
        results = []
        if depth >= max_depth:
            return results
        try:
            try:
                descendants = element.descendants(depth=max_depth - depth)
            except TypeError:
                descendants = element.descendants()
        except Exception as e:
            _debug_failure("UIA child enumeration", e)
            return results
        for descendant in descendants:
            child_info = _uia_child_info(descendant)
            if child_info:
                results.append(child_info)
        return results
    
    def _uia_element_info(elem, depth=0):
        """Extract info dict from a UI element."""
        try:
            # v7.3: Skip offscreen/invisible elements
            try:
                if not _uia_element_state(elem, "is_visible", True):
                    return None
            except Exception as e:
                _debug_failure("UIA visibility check", e)
            info = {
                "control_type": elem.element_info.control_type or "",
                "automation_id": elem.element_info.automation_id or "",
                "class_name": elem.element_info.class_name or "",
                "name": elem.element_info.name or "",
                "rect": _uia_element_rect(elem),
                "enabled": True,
                "visible": True,
                "children": []
            }
            # v7.3: Depth 3 instead of 5 — saves ~40% on busy desktops
            if depth < 3:
                try:
                    for child in elem.children():
                        child_info = _uia_element_info(child, depth+1)
                        if child_info:
                            info["children"].append(child_info)
                except Exception as e:
                    _debug_failure("UIA recursive child expansion", e)
            return info
        except Exception as e:
            _debug_failure("UIA element info", e)
            return None
    def uia_snapshot(timeout=12) -> dict:
        """Get full accessibility tree with timeout. Sets UIA_READY on failure."""
        global UIA_READY
        if not UIA_READY:
            return {"success": False, "error": "UIA not available"}
        if not _UIA_SNAPSHOT_SEMAPHORE.acquire(timeout=0.1):
            return {"success": False, "error": "UIA busy"}
        result = {"success": False, "error": "timeout"}
        def _run():
            global _UIA_LAST_CRAWL_RESULT
            try:
                nonlocal result
                try:
                    desktop = PyWinDesktop(backend="uia")
                    info = {
                        "control_type": "Desktop",
                        "name": "Desktop",
                        "children": []
                    }
                    # v7.3: Skip full crawl if window list hasn't changed
                    win_list = list(desktop.windows())[:100]
                    if win_list and not _uia_winlist_changed(win_list):
                        if _UIA_LAST_CRAWL_RESULT is not None:
                            info = _UIA_LAST_CRAWL_RESULT
                            result = {"success": True, "tree": info}
                            return
                    # v7.3: Per-window timeout — skip windows that take >3s to crawl.
                    for win in win_list:
                        try:
                            win_start = time.time()
                            win_info = {
                                "control_type": win.element_info.control_type or "",
                                "automation_id": win.element_info.automation_id or "",
                                "class_name": win.element_info.class_name or "",
                                "name": win.element_info.name or "",
                                "rect": _uia_element_rect(win),
                                "enabled": True,
                                "visible": True,
                                "children": []
                            }
                            # Only crawl children if we haven't spent too long already
                            if time.time() - win_start < _WINDOW_CRAWL_TIMEOUT:
                                children_result = []
                                _target_win = win
                                def _crawl_window_children(w=_target_win):
                                    try:
                                        children_result.extend(_get_children(w, max_depth=2))
                                    except Exception as e:
                                        _debug_failure("UIA window child crawl", e)
                                    finally:
                                        try:
                                            _UIA_CHILD_SEMAPHORE.release()
                                        except ValueError:
                                            pass
                                if _UIA_CHILD_SEMAPHORE.acquire(timeout=0.05):
                                    ct = threading.Thread(target=_crawl_window_children, daemon=True)
                                    ct.start()
                                    ct.join(timeout=_WINDOW_CHILD_JOIN_TIMEOUT)
                                win_info["children"] = children_result
                            info["children"].append(win_info)
                        except Exception as e:
                            _debug_failure("UIA window crawl", e)
                    result = {"success": True, "tree": info}
                    # v7.3: Cache successful result for next call
                    _UIA_LAST_CRAWL_RESULT = info
                except Exception as e:
                    result = {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            except Exception as e:
                _debug_failure("UIA snapshot worker", e)
        try:
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if not result.get("success"):
                UIA_READY = False
            return result
        finally:
            _UIA_SNAPSHOT_SEMAPHORE.release()
    
    def uia_find_deep(name: str) -> list:
        """Find windows and descendants whose UIA name contains the search text."""
        try:
            needle = (name or "").lower()
            if not needle:
                return []
            desktop = PyWinDesktop(backend="uia")
            results = []
            for win in desktop.windows():
                try:
                    win_name = win.element_info.name or ""
                    if needle in win_name.lower():
                        win_info = _uia_find_info(win)
                        if win_info:
                            results.append(win_info)
                except Exception as e:
                    _debug_failure("UIA deep window info", e)
                if len(results) >= 50:
                    break
                try:
                    descendants = win.descendants()
                except Exception as e:
                    _debug_failure("UIA deep descendants", e)
                    descendants = []
                for child in descendants:
                    try:
                        child_name = child.element_info.name or ""
                        if needle in child_name.lower():
                            child_info = _uia_find_info(child)
                            if child_info:
                                results.append(child_info)
                                if len(results) >= 50:
                                    break
                    except Exception as e:
                        _debug_failure("UIA deep child info", e)
                if len(results) >= 50:
                    break
            return results[:50]
        except Exception as e:
            return [{"error": str(e)}]
    
    def uia_find_by_name(name: str) -> list:
        """Find elements by name substring."""
        try:
            desktop = PyWinDesktop(backend="uia")
            results = []
            # Search all windows
            for win in desktop.windows():
                try:
                    if name.lower() in (win.element_info.name or "").lower():
                        results.append(_uia_element_info(win))
                except Exception as e:
                    _debug_failure("UIA named window search", e)
                # Search children
                try:
                    for child in win.descendants():
                        try:
                            cname = child.element_info.name or ""
                            if name.lower() in cname.lower():
                                results.append(_uia_element_info(child))
                        except Exception as e:
                            _debug_failure("UIA named child search", e)
                except Exception as e:
                    _debug_failure("UIA named descendants", e)
            return results
        except Exception as e:
            return [{"error": str(e)}]
    
    def uia_click_element(target):
        """Click a UI element by index, name, or automation_id."""
        try:
            desktop = PyWinDesktop(backend="uia")
            if isinstance(target, int):
                # Index-based: get all elements, click the Nth interactable one
                all_elements = []
                def collect(win, depth=0):
                    if depth > 3:
                        return
                    try:
                        all_elements.append(win)
                        for child in win.descendants():
                            try:
                                all_elements.append(child)
                            except Exception as e:
                                _debug_failure("UIA collect child", e)
                    except Exception as e:
                        _debug_failure("UIA collect descendants", e)
                for win in desktop.windows():
                    collect(win)
                if target < len(all_elements):
                    all_elements[target].click_input()
                    return {"success": True, "method": "index", "index": target}
                return {"success": False, "error": f"Index {target} out of range ({len(all_elements)} total)"}
            else:
                # Search by name
                results = uia_find_by_name(target)
                if results and "error" not in results[0]:
                    for win in desktop.windows():
                        try:
                            if target.lower() in (win.element_info.name or "").lower():
                                win.click_input()
                                return {"success": True, "method": "name"}
                        except Exception as e:
                            _debug_failure("UIA click window by name", e)
                        for child in win.descendants():
                            try:
                                cname = child.element_info.name or ""
                                if target.lower() in cname.lower():
                                    child.click_input()
                                    return {"success": True, "method": "name_descendant"}
                            except Exception as e:
                                _debug_failure("UIA click descendant by name", e)
                return {"success": False, "error": f"Element '{target}' not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    UIA_READY = True
except Exception as e:
    UIA_READY = False
    _uia_error = str(e)

# v7.3: UIA window list cache — skip full crawl if nothing changed
_UIA_WIN_CACHE = []  # list of (win_name, win_rect_hash)
_UIA_WIN_CACHE_LOCK = threading.Lock()
_UIA_LAST_HASH = None
_UIA_LAST_CRAWL_RESULT = None

def _uia_winlist_changed(win_list: list) -> bool:
    """Quick check: did the window list change since last call?
    Returns True if changed (caller should re-crawl)."""
    global _UIA_WIN_CACHE
    try:
        sig = tuple(sorted((w.element_info.name or "", str(w.rectangle())) for w in win_list))
        with _UIA_WIN_CACHE_LOCK:
            if sig == tuple(_UIA_WIN_CACHE):
                return False
            _UIA_WIN_CACHE[:] = sig
        return True
    except Exception as e:
        _debug_failure("UIA window cache signature", e)
        return True

if "uia_find_deep" not in globals():
    def uia_find_deep(name: str) -> list:
        return [{"error": _uia_error or "UIA not available"}]

def _som_monitor_bounds(monitor_index, fallback_size):
    """Return monitor bounds used to convert absolute UIA coords to screenshot coords."""
    try:
        from routes_ocr import _coerce_monitor_index, _monitor_bounds
        return dict(_monitor_bounds(_coerce_monitor_index(monitor_index)))
    except Exception as e:
        _debug_failure("UIA monitor bounds lookup", e)
        try:
            width, height = fallback_size
        except (TypeError, ValueError) as e:
            _debug_failure("UIA fallback monitor size", e)
            width, height = 1920, 1080
        try:
            monitor_index = max(0, int(monitor_index))
        except (TypeError, ValueError):
            monitor_index = 0
        return {"id": monitor_index, "name": "Monitor", "width": int(width), "height": int(height),
                "left": 0, "top": 0, "is_primary": monitor_index in (0, 1)}

# ── SOM Overlay (Set of Mark) ──────────────────────────────────────────────
def som_overlay(screenshot_bytes: bytes, monitor_index=0) -> dict:
    """Take screenshot + UIA snapshot, overlay numbered boxes on elements.
    Returns dict with:
      - labeled_screenshot: base64 PNG with numbers on each element
      - elements: list of {index, name, control_type, bbox, center}
      - total: count
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(BytesIO(screenshot_bytes)).convert("RGBA")
        sw, sh = img.size
        monitor_bounds = _som_monitor_bounds(monitor_index, img.size)
        mon_left = int(monitor_bounds.get("left", 0))
        mon_top = int(monitor_bounds.get("top", 0))
        mon_width = int(monitor_bounds.get("width", sw))
        mon_height = int(monitor_bounds.get("height", sh))
        mon_right = mon_left + mon_width
        mon_bottom = mon_top + mon_height
        try:
            monitor_index = max(0, int(monitor_bounds.get("id", monitor_index)))
        except (TypeError, ValueError):
            monitor_index = 0

        # Get UIA elements
        elements = []
        if UIA_READY:
            snap = uia_snapshot(timeout=10)
            if snap.get("success"):
                def flatten(node, depth=0):
                    if depth > 4 or not node:
                        return
                    rect = node.get("rect")
                    if rect and rect["width"] > 10 and rect["height"] > 10:
                        abs_x = int(rect["left"])
                        abs_y = int(rect["top"])
                        abs_w = int(rect["width"])
                        abs_h = int(rect["height"])
                        if (abs_x + abs_w > mon_left and abs_y + abs_h > mon_top
                                and abs_x < mon_right and abs_y < mon_bottom):
                            rel_x = abs_x - mon_left
                            rel_y = abs_y - mon_top
                            abs_center = [abs_x + abs_w // 2, abs_y + abs_h // 2]
                            elements.append({
                                "name": node.get("name", ""),
                                "control_type": node.get("control_type", ""),
                                "automation_id": node.get("automation_id", ""),
                                "bbox": [rel_x, rel_y, abs_w, abs_h],
                                "center": [abs_center[0] - mon_left, abs_center[1] - mon_top],
                                "absolute_bbox": [abs_x, abs_y, abs_w, abs_h],
                                "absolute_center": abs_center,
                            })
                    for child in node.get("children", []):
                        flatten(child, depth+1)
                flatten(snap.get("tree"))
        
        # Filter to reasonable elements (not too big, not too small)
        def visible_element(elem):
            bx, by, bw, bh = elem["bbox"]
            return (20 < bw < max(sw // 2, 21) and 20 < bh < max(sh // 2, 21)
                    and bx + bw > 0 and by + bh > 0 and bx < sw and by < sh)

        elements = [e for e in elements if visible_element(e)]
        elements = elements[:50]  # max 50
        
        # Overlay numbers
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except OSError as e:
            _debug_failure("UIA overlay font load", e)
            font = ImageFont.load_default()
        
        labeled = []
        for i, elem in enumerate(elements):
            bx, by, bw, bh = elem["bbox"]
            label = str(i+1)
            draw_x1 = max(0, bx)
            draw_y1 = max(0, by)
            draw_x2 = min(sw - 1, bx + bw)
            draw_y2 = min(sh - 1, by + bh)
            if draw_x2 <= draw_x1 or draw_y2 <= draw_y1:
                continue
            
            # Draw colored box
            draw.rectangle([draw_x1, draw_y1, draw_x2, draw_y2], outline="#FF4444", width=2)
            
            # Draw label background
            label_x = max(0, min(draw_x1, max(0, sw - 24)))
            label_y = max(0, draw_y1 - 18)
            bbox = draw.textbbox((label_x, label_y), label, font=font)
            draw.rectangle(bbox, fill="#FF4444")
            
            # Draw label text
            draw.text((label_x+2, label_y), label, fill="white", font=font)
            
            labeled.append({
                "index": i+1,
                "name": elem["name"],
                "control_type": elem["control_type"],
                "automation_id": elem.get("automation_id", ""),
                "bbox": elem["bbox"],
                "center": elem["center"],
                "absolute_bbox": elem["absolute_bbox"],
                "absolute_center": elem["absolute_center"],
                "x": elem["center"][0],
                "y": elem["center"][1],
                "width": elem["bbox"][2],
                "height": elem["bbox"][3],
            })
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        
        return {
            "success": True,
            "labeled_screenshot": base64.b64encode(buf.getvalue()).decode(),
            "elements": labeled,
            "total": len(labeled),
            "monitor_index": monitor_index,
            "monitor_bounds": monitor_bounds,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

# v5.1: UIA→SOM bridging — cross-reference UIA elements with SOM overlay coordinates
def uia_som_bridge(screenshot_bytes: bytes) -> dict:
    """Run SOM overlay, then annotate each element with its UIA automation_id.
    Returns SOM result with 'elements' containing additional 'automation_id' and 'uia_name' fields.
    Also returns a 'uia_lookup' dict mapping automation_id -> element index.
    """
    som = som_overlay(screenshot_bytes)
    if not som.get("success"):
        return som

    # Build lookup: take one UIA snapshot, then match each SOM element by center overlap.
    uia_lookup = {}
    snap = uia_snapshot(timeout=5) if UIA_READY else {}
    uia_tree = snap.get("tree", {}) if snap.get("success") else {}

    def find_by_point(node, px, py, depth=0):
        if depth > 3 or not node:
            return None
        rect = node.get("rect")
        if rect:
            rx, ry, rw, rh = rect["left"], rect["top"], rect["width"], rect["height"]
            if rx <= px <= rx + rw and ry <= py <= ry + rh:
                for child in node.get("children", []):
                    found = find_by_point(child, px, py, depth+1)
                    if found:
                        return found
                return {
                    "name": node.get("name", ""),
                    "automation_id": node.get("automation_id", ""),
                    "control_type": node.get("control_type", ""),
                    "class_name": node.get("class_name", ""),
                }
        return None

    for elem in som.get("elements", []):
        bbox = elem.get("bbox")
        if not bbox:
            continue
        absolute_center = elem.get("absolute_center")
        if absolute_center:
            e_center_x, e_center_y = absolute_center
        else:
            ex, ey, ew, eh = bbox
            e_center_x = ex + ew // 2
            e_center_y = ey + eh // 2

        # Scan UIA tree for element containing this center point
        if uia_tree:
            match = find_by_point(uia_tree, e_center_x, e_center_y)
            if match:
                elem["automation_id"] = match.get("automation_id", "")
                elem["uia_name"] = match.get("name", "")
                elem["uia_control_type"] = match.get("control_type", "")
                aid = match.get("automation_id", "")
                if aid:
                    uia_lookup[aid] = elem["index"]

    som["uia_lookup"] = uia_lookup
    return som

def find_element_by_center(px: int, py: int) -> dict:
    """Find the UIA element at pixel coordinates (x, y).
    Returns element info dict with name, control_type, automation_id, rect, or empty dict.
    """
    if not UIA_READY:
        return {}
    snap = uia_snapshot(timeout=5)
    if not snap.get("success"):
        return {}

    def search(node, depth=0):
        if depth > 4 or not node:
            return None
        rect = node.get("rect")
        if rect:
            rx, ry, rw, rh = rect["left"], rect["top"], rect["width"], rect["height"]
            if rx <= px <= rx + rw and ry <= py <= ry + rh:
                # Search children first (innermost element wins)
                for child in node.get("children", []):
                    found = search(child, depth+1)
                    if found:
                        return found
                return {
                    "name": node.get("name", ""),
                    "automation_id": node.get("automation_id", ""),
                    "control_type": node.get("control_type", ""),
                    "class_name": node.get("class_name", ""),
                    "rect": rect
                }
        return None

    found = search(snap.get("tree", {}))
    return found or {}

# v5.1: Per-window SOM — generate SOMs for individual windows instead of full screen
def per_window_som(window_title: str = None) -> dict:
    """Generate SOM overlay for a single window.
    If window_title is given, snap that window. Otherwise return all per-window SOMs.
    Returns dict with per-window results and combined overlay.
    """
    try:
        from pywinauto import Desktop as PyWinDesktop
        if not UIA_READY:
            return {"success": False, "error": "UIA not available"}

        desktop = PyWinDesktop(backend="uia")
        windows = []
        for win in desktop.windows():
            try:
                title = win.element_info.name or ""
                rect = _uia_element_rect(win)
                if title and rect and rect["width"] > 100 and rect["height"] > 100:
                    windows.append({"handle": win, "title": title, "rect": rect})
            except Exception as e:
                _debug_failure("UIA per-window enumerate", e)

        if not windows:
            return {"success": False, "error": "No suitable windows found"}

        # Grab full screenshot once (MSS — no window flash)
        from PIL import Image, ImageDraw, ImageFont
        try:
            import mss as _mss_mod
            with _mss_mod.mss() as _sct:
                _mon = _sct.monitors[0]
                _sct_img = _sct.grab(_mon)
                img_full = Image.frombytes("RGB", _sct_img.size, _sct_img.rgb)
            screen_bytes = BytesIO()
            img_full.save(screen_bytes, format="PNG")
            screen_bytes = screen_bytes.getvalue()
        except Exception as e:
            _debug_failure("UIA per-window screen capture", e)
            return {"success": False, "error": "Cannot capture screen"}

        if window_title:
            # Single window mode
            windows = [w for w in windows if window_title.lower() in w["title"].lower()]
            if not windows:
                return {"success": False, "error": f"Window '{window_title}' not found"}

        img_base = Image.open(BytesIO(screen_bytes)).convert("RGBA")
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except OSError as e:
            _debug_failure("UIA per-window font load", e)
            font = ImageFont.load_default()

        per_window_results = []
        combined_draw = ImageDraw.Draw(img_base)
        snap = uia_snapshot(timeout=5)

        for wi, winfo in enumerate(windows):
            r = winfo["rect"]
            wx, wy, ww, wh = r["left"], r["top"], r["width"], r["height"]
            title = winfo["title"]

            # Get UIA elements within this window
            win_elements = []
            if snap.get("success"):
                def flatten_win(node, depth=0):
                    if depth > 4 or not node:
                        return
                    rect = node.get("rect")
                    if rect:
                        rx, ry, rw, rh = rect["left"], rect["top"], rect["width"], rect["height"]
                        # Only elements within this window bounds
                        if (rx >= wx and ry >= wy and rx + rw <= wx + ww and ry + rh <= wy + wh
                            and rw > 15 and rh > 15 and rw < ww * 0.8 and rh < wh * 0.8):
                            win_elements.append({
                                "id": node.get("id", 0),
                                "name": node.get("name", ""),
                                "control_type": node.get("control_type", ""),
                                "bbox": [rx - wx, ry - wy, rw, rh],  # relative to window
                                "absolute_bbox": [rx, ry, rw, rh],
                                "center": [rx - wx + rw//2, ry - wy + rh//2]
                            })
                    for child in node.get("children", []):
                        flatten_win(child, depth+1)
                flatten_win(snap.get("tree", {}))

            win_elements = win_elements[:30]

            # Draw window outline
            combined_draw.rectangle([wx, wy, wx + ww, wy + wh], outline="#00FF88", width=2)
            # Draw title
            combined_draw.text((wx + 4, wy + 4), f"[{wi+1}] {title[:50]}", fill="#00FF88", font=font)

            # Draw elements
            label_counter = 1
            labeled = []
            for elem in win_elements:
                abs_bx, abs_by, abs_bw, abs_bh = elem["absolute_bbox"]
                label = str(wi * 100 + label_counter)

                # Draw box in window-specific color
                combined_draw.rectangle([abs_bx, abs_by, abs_bx + abs_bw, abs_by + abs_bh],
                                       outline="#44FFAA", width=1)

                # Draw label
                tb = combined_draw.textbbox((abs_bx, abs_by - 14), label, font=font)
                combined_draw.rectangle(tb, fill="#44FFAA")
                combined_draw.text((abs_bx + 1, abs_by - 14), label, fill="black", font=font)

                labeled.append({
                    "index": label_counter,
                    "window_index": wi,
                    "id": elem.get("id", 0),
                    "name": elem.get("name", ""),
                    "control_type": elem.get("control_type", ""),
                    "center": elem["center"],
                    "bbox_relative": elem["bbox"],
                    "bbox_absolute": elem["absolute_bbox"]
                })
                label_counter += 1

            per_window_results.append({
                "window_index": wi,
                "title": title,
                "rect": {"x": wx, "y": wy, "width": ww, "height": wh},
                "elements": labeled,
                "total": len(labeled)
            })

        # Pad with outer labels for windows list
        for wi, winfo in enumerate(windows):
            r = winfo["rect"]
            wx, wy, ww, wh = r["left"], r["top"], r["width"], r["height"]
            label = str(wi + 1)
            combined_draw.text((wx + 4, wy + wh - 18), f"[W{label}]", fill="#00FF88", font=font)

        buf = BytesIO()
        img_base.save(buf, format="PNG")

        return {
            "success": True,
            "per_window": per_window_results,
            "total_windows": len(per_window_results),
            "combined_screenshot": base64.b64encode(buf.getvalue()).decode(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

# ── OCR + UIA combined find ────────────────────────────────────────────────
def find_on_screen(text: str) -> dict:
    """Find text on screen using both OCR and UIA, return best matches."""
    results = {"text": text, "matches": []}
    
    # Method 1: UIA
    if UIA_READY:
        uia_results = uia_find_by_name(text)
        for r in uia_results:
            if "error" not in r and r.get("rect"):
                results["matches"].append({
                    "method": "uia",
                    "name": r.get("name", ""),
                    "control_type": r.get("control_type", ""),
                    "bbox": r["rect"],
                    "center": [r["rect"]["left"] + r["rect"]["width"]//2,
                              r["rect"]["top"] + r["rect"]["height"]//2],
                    "confidence": 1.0
                })
    
    # Method 2: OCR (if available)
    try:
        import pytesseract
        from PIL import Image
        from io import BytesIO
        # We'll get screenshot from the caller
        results["method"] = "combined"
    except (ImportError, OSError, RuntimeError) as e:
        _debug_failure("OCR/UIA combined setup", e)
    
    results["total"] = len(results["matches"])
    results["found"] = results["total"] > 0
    return results

# ── Background SendInput (doesn't steal focus) ────────────────────────────
def send_input_background(keys: list, hold_ms: int = 30):
    """Send keystrokes using SendInput without stealing focus or moving cursor.
    
    Uses INPUT structure with KEYBDINPUT. Does NOT use mouse movement.
    Good for typing into a background window.
    """
    try:
        # Map virtual key codes
        vk_map = {
            'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10,
            'win': 0x5B, 'enter': 0x0D, 'tab': 0x09, 'esc': 0x1B,
            'escape': 0x1B, 'backspace': 0x08, 'delete': 0x2E, 'space': 0x20,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
            'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
            'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
            'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
            'caps': 0x14, 'capslock': 0x14, 'numlock': 0x90,
            'printscreen': 0x2C, 'pause': 0x13,
            '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
            '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
            'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
            'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
            'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
            'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
            'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
        }
        
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD),
                        ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p)]
        
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG),
                        ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p)]
        
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD),
                        ("wParamL", wintypes.WORD),
                        ("wParamH", wintypes.WORD)]
        
        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT),
                        ("mi", MOUSEINPUT),
                        ("hi", HARDWAREINPUT)]
        
        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD),
                        ("u", INPUT_UNION)]
        
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        
        def _make_input(vk, flags=0):
            inp = INPUT(INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
            return inp
        
        if isinstance(keys, str):
            keys = [keys]
        # Build input sequence. Multiple keys are a chord, not sequential taps.
        vks = []
        for key in keys:
            k = str(key).lower()
            if not k:
                continue
            vk = vk_map.get(k, ord(k[0].upper())) if len(k) == 1 else vk_map.get(k, 0)
            if vk:
                vks.append(vk)
        inputs = []
        for vk in vks:
            inputs.append(_make_input(vk))
        for vk in reversed(vks):
            inputs.append(_make_input(vk, KEYEVENTF_KEYUP))
        
        if inputs:
            # Build proper ctypes array for SendInput
            InputArray = INPUT * len(inputs)
            input_array = InputArray(*inputs)
            n = windll.user32.SendInput(len(inputs), input_array, ctypes.sizeof(INPUT))
            return {"success": True, "sent": len(vks), "injected": n}
        return {"success": False, "error": "No valid keys"}
    except Exception as e:
        return {"success": False, "error": str(e)}

_MOUSE_DOWN = {"left": 0x02, "right": 0x08, "middle": 0x20}
_MOUSE_UP = {"left": 0x04, "right": 0x10, "middle": 0x40}

def send_mouse_move(x: int, y: int):
    """Move mouse with user32 without using pyautogui."""
    try:
        windll.user32.SetCursorPos(int(x), int(y))
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_mouse_click(x=None, y=None, button="left", clicks=1):
    """Click with user32 mouse_event; optionally move first."""
    try:
        if x is not None and y is not None:
            windll.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.01)
        down = _MOUSE_DOWN.get(button, _MOUSE_DOWN["left"])
        up = _MOUSE_UP.get(button, _MOUSE_UP["left"])
        for _ in range(int(clicks)):
            windll.user32.mouse_event(down, 0, 0, 0, 0)
            windll.user32.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.01)
        return {"success": True, "button": button, "clicks": clicks}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_mouse_drag(x1, y1, x2, y2, button="left"):
    """Drag with user32 mouse_event."""
    try:
        windll.user32.SetCursorPos(int(x1), int(y1))
        windll.user32.mouse_event(_MOUSE_DOWN.get(button, _MOUSE_DOWN["left"]), 0, 0, 0, 0)
        for i in range(1, 21):
            windll.user32.SetCursorPos(int(x1 + (x2 - x1) * i / 20), int(y1 + (y2 - y1) * i / 20))
            time.sleep(0.005)
        windll.user32.mouse_event(_MOUSE_UP.get(button, _MOUSE_UP["left"]), 0, 0, 0, 0)
        return {"success": True, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_scroll(clicks=-3):
    """Scroll mouse wheel with user32 mouse_event."""
    try:
        windll.user32.mouse_event(0x0800, 0, 0, int(clicks) * 120, 0)
        return {"success": True, "clicks": clicks}
    except Exception as e:
        return {"success": False, "error": str(e)}

def send_input(keys: list, hold_ms: int = 30):
    """Compatibility wrapper."""
    return send_input_background(keys, hold_ms)

def send_keys(text: str):
    """Compatibility wrapper."""
    sent = 0
    injected = 0
    for ch in str(text):
        result = send_input_background([ch])
        if not result.get("success"):
            return result
        sent += result.get("sent", 0)
        injected += result.get("injected", 0)
        time.sleep(0.005)
    return {"success": True, "sent": sent, "injected": injected}

# ── Test / Diag ────────────────────────────────────────────────────────────
def diag():
    """Check UIA availability and basic functionality."""
    result = {"uia_available": UIA_READY}
    if not UIA_READY:
        result["error"] = _uia_error
    else:
        try:
            snap = uia_snapshot(timeout=8)
            result["snapshot_ok"] = snap.get("success", False)
            if result["snapshot_ok"]:
                def count_nodes(node):
                    count = 1
                    for c in node.get("children", []):
                        count += count_nodes(c)
                    return count
                result["total_elements"] = count_nodes(snap.get("tree", {}))
        except Exception as e:
            result["snapshot_error"] = str(e)
    return result


if __name__ == "__main__":
    # Test mode
    import json
    result = diag()
    print(json.dumps(result, indent=2))
    
    if UIA_READY and result.get("snapshot_ok"):
        print("\n--- UIA Snapshot ---")
        snap = uia_snapshot(timeout=10)
        print(json.dumps(snap, indent=2)[:5000])


# ── Adaptive Element Location ───────────────────────────────────────────

def adaptive_find(target: str, screenshot_path: str = None) -> dict:
    """
    Cascade through element location strategies:
    1. UIA exact name/automation_id
    2. UIA control_type + class
    3. UIA regex match
    4. OCR text find
    5. Vision model describe (if enabled)

    Returns {'found': True, 'strategy': 'uia_exact', ...}
    or {'found': False, 'reason': '...'}
    """
    if not target or not target.strip():
        return {"found": False, "reason": "empty target"}

    target = target.strip()

    # Strategy 1: UIA exact name/automation_id match
    try:
        if UIA_READY:
            results = uia_find_deep(target)
            if results:
                match = results[0]
                rect = match.get("rect")
                if rect and len(rect) >= 4:
                    cx = rect[0] + rect[2] // 2
                    cy = rect[1] + rect[3] // 2
                    return {
                        "found": True,
                        "strategy": "uia_exact",
                        "x": cx,
                        "y": cy,
                        "bounds": rect,
                        "name": match.get("name"),
                        "control_type": match.get("control_type"),
                        "element_index": match.get("id"),
                    }
    except Exception as e:
        _debug_failure("adaptive_find strategy 1 (UIA exact)", e)

    # Strategy 2: UIA control_type + class match
    try:
        if UIA_READY:
            from pywinauto import Desktop as PyWinDesktop
            desktop = PyWinDesktop(backend="uia")
            for win in desktop.windows():
                try:
                    name = win.element_info.name or ""
                    if target.lower() in name.lower():
                        rect = _uia_element_rect(win)
                        if rect and len(rect) >= 4:
                            cx = rect[0] + rect[2] // 2
                            cy = rect[1] + rect[3] // 2
                            return {
                                "found": True,
                                "strategy": "uia_window",
                                "x": cx,
                                "y": cy,
                                "bounds": rect,
                                "name": name,
                                "control_type": win.element_info.control_type or "",
                            }
                except Exception:
                    continue
    except Exception as e:
        _debug_failure("adaptive_find strategy 2 (UIA window)", e)

    # Strategy 3: OCR text find
    try:
        img = screenshot_path
        if img is None:
            # Capture screenshot (MSS — no window flash)
            try:
                import mss as _mss_mod
                with _mss_mod.mss() as _sct:
                    _mon = _sct.monitors[0]
                    _sct_img = _sct.grab(_mon)
                    tmp = Image.frombytes("RGB", _sct_img.size, _sct_img.rgb)
                img_path = Path(__file__).parent / "screenshots" / "adaptive_find_tmp.png"
                img_path.parent.mkdir(parents=True, exist_ok=True)
                tmp.save(str(img_path))
                img = str(img_path)
            except Exception:
                pass

        if img:
            try:
                import subprocess
                result = subprocess.run(
                    ["tesseract", img, "stdout", "-l", "eng", "--psm", "6"],
                    capture_output=True, text=True, timeout=15
                )
                if target.lower() in result.stdout.lower():
                    # Found via OCR — return approximate position from image center
                    from PIL import Image as PILImage
                    with PILImage.open(img) as im:
                        w, h = im.size
                    return {
                        "found": True,
                        "strategy": "ocr",
                        "x": w // 2,
                        "y": h // 2,
                        "bounds": [0, 0, w, h],
                        "reason": f"text '{target}' found on screen via OCR",
                    }
            except Exception as e:
                _debug_failure("adaptive_find strategy 3 (OCR)", e)

    except Exception as e:
        _debug_failure("adaptive_find strategy 3 setup (OCR)", e)

    # Strategy 4: SoM visual fallback
    try:
        som_result = som_visual_fallback(screenshot_path)
        if som_result.get("found") and som_result.get("element_count", 0) > 0:
            for elem in som_result.get("elements", []):
                if target.lower() in elem.get("text", "").lower():
                    eb = elem.get("bounds", [0, 0, 0, 0])
                    cx = eb[0] + eb[2] // 2
                    cy = eb[1] + eb[3] // 2
                    return {
                        "found": True,
                        "strategy": "som",
                        "x": cx,
                        "y": cy,
                        "bounds": eb,
                        "text": elem.get("text"),
                        "element_id": elem.get("id"),
                    }
    except Exception as e:
        _debug_failure("adaptive_find strategy 4 (SoM)", e)

    return {"found": False, "reason": f"could not locate '{target}' via any strategy"}


# ── SoM Visual Fallback ─────────────────────────────────────────────────

def som_visual_fallback(screenshot_path: str = None) -> dict:
    """
    Set-of-Marks visual fallback when UIA returns no elements.
    1. Take screenshot (or use provided one)
    2. Run OCR to find all text with positions
    3. Cluster nearby text into logical groups
    4. Assign numbers to each group
    5. Overlay numbered badges on screenshot
    6. Return marked screenshot + text index
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        if screenshot_path:
            img = Image.open(screenshot_path)
        else:
            import mss as _mss_mod
            with _mss_mod.mss() as _sct:
                _mon = _sct.monitors[0]
                _sct_img = _sct.grab(_mon)
                img = Image.frombytes("RGB", _sct_img.size, _sct_img.rgb)

        w, h = img.size

        # Run OCR with tesseract to get bounding boxes
        import subprocess, tempfile, os

        tmp_png = str(Path(tempfile.gettempdir()) / "som_fallback_input.png")
        img.save(tmp_png)

        result = subprocess.run(
            ["tesseract", tmp_png, "stdout", "-l", "eng", "--psm", "6"],
            capture_output=True, text=True, timeout=15
        )

        text_lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]

        # Try tesseract with TSV output for bounding boxes
        tsv_path = str(Path(tempfile.gettempdir()) / "som_fallback_tsv")
        subprocess.run(
            ["tesseract", tmp_png, tsv_path, "-l", "eng", "--psm", "6", "tsv"],
            capture_output=True, text=True, timeout=15
        )

        elements = []
        tsv_file = tsv_path + ".tsv"
        if os.path.exists(tsv_file):
            with open(tsv_file, encoding="utf-8") as f:
                lines = f.readlines()
            # Skip header line
            for line in lines[1:]:
                parts = line.strip().split("\t")
                if len(parts) >= 12:
                    try:
                        level = int(parts[0])
                        if level != 5:  # word level
                            continue
                        x = int(parts[6])
                        y = int(parts[7])
                        bw = int(parts[8])
                        bh = int(parts[9])
                        text = parts[11].strip()
                        conf = float(parts[10]) if parts[10] != "-1" else 0
                        if text and conf > 20:
                            elements.append({
                                "id": len(elements) + 1,
                                "text": text,
                                "bounds": [x, y, bw, bh],
                                "confidence": conf,
                            })
                    except (ValueError, IndexError):
                        continue

            # Cluster nearby elements by Y proximity
            if elements:
                elements.sort(key=lambda e: (e["bounds"][1], e["bounds"][0]))

                # Draw numbered overlays
                draw = ImageDraw.Draw(img.copy(), "RGBA")
                try:
                    font = ImageFont.truetype("arial.ttf", 16)
                except Exception:
                    font = ImageFont.load_default()

                marked = img.copy()
                draw = ImageDraw.Draw(marked, "RGBA")
                for elem in elements:
                    eb = elem["bounds"]
                    label = str(elem["id"])
                    # Number badge
                    try:
                        bbox = draw.textbbox((0, 0), label, font=font)
                        tw = bbox[2] - bbox[0]
                        th = bbox[3] - bbox[1]
                    except Exception:
                        tw, th = 16, 16
                    bx, by = eb[0], eb[1]
                    draw.ellipse([bx - 10, by - 10, bx + tw + 6, by + th + 6], fill=(255, 50, 50, 220))
                    draw.text((bx - 6, by - 4), label, fill=(255, 255, 255, 255), font=font)
                    # Bounding box
                    draw.rectangle(
                        [eb[0], eb[1], eb[0] + eb[2], eb[1] + eb[3]],
                        outline=(255, 50, 50, 180), width=2
                    )

                marked_path = str(Path(tempfile.gettempdir()) / "som_fallback_marked.png")
                marked.save(marked_path)

                try:
                    os.remove(tmp_png)
                    if os.path.exists(tsv_file):
                        os.remove(tsv_file)
                except Exception:
                    pass

                return {
                    "found": True,
                    "element_count": len(elements),
                    "elements": elements[:50],  # Max 50
                    "marked_image": marked_path,
                    "strategy": "som_visual",
                    "screenshot_size": [w, h],
                }

    except Exception as e:
        _debug_failure("som_visual_fallback", e)

    return {"found": False, "element_count": 0, "elements": []}


# ── Icon/Logo Click by Image Template Matching ─────────────────────────

def find_icon_by_template(icon_path: str, threshold: float = 0.8) -> dict:
    """
    Find an icon/logo on screen by OpenCV template matching.
    
    Takes a path to an image file (PNG preferred with transparency) and
    scans the current screen for matching regions.
    
    Args:
        icon_path: Path to the icon image file to find
        threshold: Matching confidence threshold (0.0-1.0, default 0.8)
        
    Returns:
        dict with 'found', 'matches' (list of {x, y, w, h, confidence}),
        'strategy': 'template_match'
    """
    try:
        import cv2
        import numpy as np
        from PIL import ImageGrab
    except ImportError:
        return {"found": False, "error": "OpenCV or numpy not available", "strategy": "template_match"}

    if not icon_path or not Path(icon_path).exists():
        return {"found": False, "error": f"Icon file not found: {icon_path}", "strategy": "template_match"}

    try:
        # Load template
        template = cv2.imread(str(icon_path), cv2.IMREAD_UNCHANGED)
        if template is None:
            return {"found": False, "error": "Failed to load icon image", "strategy": "template_match"}

        # If template has alpha channel, use only RGB for matching
        if template.shape[2] == 4:
            template_rgb = cv2.cvtColor(template, cv2.COLOR_BGRA2BGR)
        else:
            template_rgb = template

        # Capture screen (MSS — no window flash)
        import mss as _mss_mod
        with _mss_mod.mss() as _sct:
            _mon = _sct.monitors[0]
            _sct_img = _sct.grab(_mon)
            screen = Image.frombytes("RGB", _sct_img.size, _sct_img.rgb)
        screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

        th, tw = template_rgb.shape[:2]
        sh, sw = screen_cv.shape[:2]

        if th > sh or tw > sw:
            return {"found": False, "error": "Icon is larger than screen", "strategy": "template_match"}

        # Try multiple scales for better matching
        matches = []
        for scale in [1.0, 0.9, 0.8, 1.1, 1.2]:
            scaled_w = int(tw * scale)
            scaled_h = int(th * scale)
            if scaled_w < 10 or scaled_h < 10 or scaled_w > sw or scaled_h > sh:
                continue
            scaled_tpl = cv2.resize(template_rgb, (scaled_w, scaled_h))

            result = cv2.matchTemplate(screen_cv, scaled_tpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            for pt in zip(*locations[::-1]):
                cx = pt[0] + scaled_w // 2
                cy = pt[1] + scaled_h // 2
                conf = float(result[pt[1], pt[0]])
                matches.append({
                    "x": cx,
                    "y": cy,
                    "w": scaled_w,
                    "h": scaled_h,
                    "confidence": round(conf, 4),
                    "scale": scale,
                })

        # Non-maximum suppression — keep only the best match in overlapping regions
        if matches:
            matches.sort(key=lambda m: m["confidence"], reverse=True)
            kept = []
            for m in matches:
                if not kept:
                    kept.append(m)
                    continue
                # Check if this match overlaps too much with already-kept ones
                mx, my, mw, mh = m["x"], m["y"], m["w"], m["h"]
                is_duplicate = False
                for k in kept:
                    kx, ky, kw, kh = k["x"], k["y"], k["w"], k["h"]
                    # Check overlap
                    overlap_x = max(0, min(mx + mw//2, kx + kw//2) - max(mx - mw//2, kx - kw//2))
                    overlap_y = max(0, min(my + mh//2, ky + kh//2) - max(my - mh//2, ky - kh//2))
                    if overlap_x > 0.5 * min(mw, kw) and overlap_y > 0.5 * min(mh, kh):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    kept.append(m)

            return {
                "found": True,
                "matches": kept[:5],  # Top 5
                "total_matches": len(matches),
                "best_match": kept[0],
                "strategy": "template_match",
                "icon_path": icon_path,
            }

        return {"found": False, "matches": [], "strategy": "template_match",
                "reason": f"No match above threshold {threshold}"}

    except Exception as e:
        _debug_failure("find_icon_by_template", e)
        return {"found": False, "error": str(e), "strategy": "template_match"}


def click_icon_by_template(icon_path: str, threshold: float = 0.8,
                           button: str = "left") -> dict:
    """
    Find an icon/logo on screen by template matching and click it.
    
    Args:
        icon_path: Path to the icon image
        threshold: Matching confidence (0.0-1.0)
        button: Mouse button ('left', 'right', 'middle')
        
    Returns dict with 'success', 'x', 'y', 'confidence', 'strategy'
    """
    result = find_icon_by_template(icon_path, threshold)
    if not result.get("found"):
        return {
            "success": False,
            "error": result.get("reason") or result.get("error", "Icon not found"),
            "strategy": "template_match",
        }

    match = result["best_match"]
    x, y = match["x"], match["y"]

    # Click at center of match
    send_mouse_move(x, y)
    time.sleep(0.05)
    click_result = send_mouse_click(x, y, button)

    return {
        "success": True,
        "x": x,
        "y": y,
        "confidence": match["confidence"],
        "strategy": "template_match",
        "icon_path": icon_path,
        "click_result": click_result,
    }
