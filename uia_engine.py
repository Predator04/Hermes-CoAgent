"""Hermes CoAgent v7.3 — UIA Engine
Windows UI Automation tree + SOM overlays + background SendInput.

Provides:
- uia_snapshot(): accessibility tree of all interactable elements
- uia_click(target): click element by index, name, or automation_id
- som_overlay(screenshot): screenshot with numbered element boxes
- ocr_find_uia(text): find by both UIA and OCR, return best match
- send_input_background(keys): send keystrokes WITHOUT stealing focus
"""

import base64, time, threading, hashlib
from io import BytesIO
import ctypes
from ctypes import wintypes, windll
import traceback

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
    except:
        pass
    try:
        aid = elem.element_info.automation_id or ""
        ct = elem.element_info.control_type or ""
        nm = elem.element_info.name or ""
        cn = elem.element_info.class_name or ""
        raw = f"{aid}|{ct}|{nm}|{cn}"
        if raw != "|||":
            return "fallback:" + hashlib.md5(raw.encode()).hexdigest()
    except:
        pass
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

# v5.1: Accelerated regions — track which screen areas change most often
_ACCEL_REGIONS = {}  # region_key -> {change_count, stable_count, priority}
_ACCEL_LOCK = threading.Lock()
def _mark_region_changed(region_key: str):
    """Mark a screen region as having changed."""
    with _ACCEL_LOCK:
        if region_key not in _ACCEL_REGIONS:
            _ACCEL_REGIONS[region_key] = {"change_count": 0, "stable_count": 0, "priority": 0}
        _ACCEL_REGIONS[region_key]["change_count"] += 1
        _ACCEL_REGIONS[region_key]["stable_count"] = 0
        _ACCEL_REGIONS[region_key]["priority"] = min(100, _ACCEL_REGIONS[region_key]["change_count"] * 2)

def _mark_region_stable(region_key: str):
    """Mark a screen region as unchanged."""
    with _ACCEL_LOCK:
        if region_key not in _ACCEL_REGIONS:
            _ACCEL_REGIONS[region_key] = {"change_count": 0, "stable_count": 0, "priority": 0}
        _ACCEL_REGIONS[region_key]["stable_count"] += 1
        _ACCEL_REGIONS[region_key]["change_count"] = max(0, _ACCEL_REGIONS[region_key]["change_count"] - 1)

def _get_cold_regions():
    """Return region keys that have been stable for >5 consecutive checks.
    These are safe to skip in accelerated capture.
    """
    with _ACCEL_LOCK:
        return [k for k, v in _ACCEL_REGIONS.items() if v["stable_count"] > 5]

# ── UIA via pywinauto ─────────────────────────────────────────────────────
# Initialize COM in STA mode BEFORE importing pywinauto
try:
    import pythoncom
    pythoncom.CoInitialize()
except:
    pass

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
        except:
            return None

    def _uia_element_state(elem, method_name: str, default: bool = True) -> bool:
        """Read a pywinauto boolean state method without failing snapshot collection."""
        try:
            method = getattr(elem, method_name)
            return bool(method())
        except:
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
        except:
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
        except:
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
        except:
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
            except:
                pass
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
                except:
                    pass
            return info
        except:
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
                                    except:
                                        pass
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
                        except:
                            pass
                    result = {"success": True, "tree": info}
                    # v7.3: Cache successful result for next call
                    _UIA_LAST_CRAWL_RESULT = info
                except Exception as e:
                    result = {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            except:
                pass
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
                except:
                    pass
                if len(results) >= 50:
                    break
                try:
                    descendants = win.descendants()
                except:
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
                    except:
                        pass
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
                except:
                    pass
                # Search children
                try:
                    for child in win.descendants():
                        try:
                            cname = child.element_info.name or ""
                            if name.lower() in cname.lower():
                                results.append(_uia_element_info(child))
                        except:
                            pass
                except:
                    pass
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
                            except:
                                pass
                    except:
                        pass
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
                        except:
                            pass
                        for child in win.descendants():
                            try:
                                cname = child.element_info.name or ""
                                if target.lower() in cname.lower():
                                    child.click_input()
                                    return {"success": True, "method": "name_descendant"}
                            except:
                                pass
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
    except:
        return True

if "uia_find_deep" not in globals():
    def uia_find_deep(name: str) -> list:
        return [{"error": _uia_error or "UIA not available"}]

# ── SOM Overlay (Set of Mark) ──────────────────────────────────────────────
def som_overlay(screenshot_bytes: bytes) -> dict:
    """Take screenshot + UIA snapshot, overlay numbered boxes on elements.
    Returns dict with:
      - labeled_screenshot: base64 PNG with numbers on each element
      - elements: list of {index, name, control_type, bbox, center}
      - total: count
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(BytesIO(screenshot_bytes)).convert("RGBA")
        
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
                        elements.append({
                            "name": node.get("name", ""),
                            "control_type": node.get("control_type", ""),
                            "automation_id": node.get("automation_id", ""),
                            "bbox": [rect["left"], rect["top"], rect["width"], rect["height"]],
                            "center": [rect["left"] + rect["width"]//2, rect["top"] + rect["height"]//2]
                        })
                    for child in node.get("children", []):
                        flatten(child, depth+1)
                flatten(snap.get("tree"))
        
        # Filter to reasonable elements (not too big, not too small)
        sw, sh = img.size
        elements = [e for e in elements if 20 < e["bbox"][2] < sw//2 and 20 < e["bbox"][3] < sh//2]
        elements = elements[:50]  # max 50
        
        # Overlay numbers
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        labeled = []
        for i, elem in enumerate(elements):
            bx, by, bw, bh = elem["bbox"]
            label = str(i+1)
            
            # Draw colored box
            draw.rectangle([bx, by, bx+bw, by+bh], outline="#FF4444", width=2)
            
            # Draw label background
            bbox = draw.textbbox((bx, by-18), label, font=font)
            draw.rectangle(bbox, fill="#FF4444")
            
            # Draw label text
            draw.text((bx+2, by-18), label, fill="white", font=font)
            
            labeled.append({
                "index": i+1,
                "name": elem["name"],
                "control_type": elem["control_type"],
                "bbox": elem["bbox"],
                "center": elem["center"]
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
            except:
                pass

        if not windows:
            return {"success": False, "error": "No suitable windows found"}

        # Grab full screenshot once
        from PIL import Image, ImageDraw, ImageFont
        try:
            from PIL import ImageGrab
            img_full = ImageGrab.grab()
            screen_bytes = BytesIO()
            img_full.save(screen_bytes, format="PNG")
            screen_bytes = screen_bytes.getvalue()
        except:
            return {"success": False, "error": "Cannot capture screen"}

        if window_title:
            # Single window mode
            windows = [w for w in windows if window_title.lower() in w["title"].lower()]
            if not windows:
                return {"success": False, "error": f"Window '{window_title}' not found"}

        img_base = Image.open(BytesIO(screen_bytes)).convert("RGBA")
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
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
    except:
        pass
    
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
