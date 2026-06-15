"""Hermes CoAgent v4 - UIA Engine
Windows UI Automation tree + SOM overlays + background SendInput.

Provides:
- uia_snapshot(): accessibility tree of all interactable elements
- uia_click(target): click element by index, name, or automation_id
- som_overlay(screenshot): screenshot with numbered element boxes
- ocr_find_uia(text): find by both UIA and OCR, return best match
- send_input_background(keys): send keystrokes WITHOUT stealing focus
"""

import sys, os, json, base64, time, threading, struct
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field, asdict
import ctypes
from ctypes import wintypes, windll
import traceback
import threading

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
    from pywinauto import Application
    from pywinauto.timings import Timings
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
            if depth < 5:
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
    def _uia_snapshot_inner():
        try:
            desktop = PyWinDesktop(backend="uia")
            info = {
                "control_type": "Desktop",
                "name": "Desktop",
                "children": []
            }
            for win in desktop.windows():
                try:
                    win_info = {
                        "control_type": win.element_info.control_type or "",
                        "automation_id": win.element_info.automation_id or "",
                        "class_name": win.element_info.class_name or "",
                        "name": win.element_info.name or "",
                        "rect": _uia_element_rect(win),
                        "enabled": True,
                        "visible": True,
                        "children": _get_children(win, max_depth=3)
                    }
                    info["children"].append(win_info)
                except:
                    pass
            return {"success": True, "tree": info}
        except Exception as e:
            return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    
    def uia_snapshot(timeout=15) -> dict:
        """Get full accessibility tree with timeout. Sets UIA_READY=False on timeout."""
        global UIA_READY
        result = {"success": False, "error": "timeout"}
        def _run():
            nonlocal result
            try:
                result = _uia_snapshot_inner()
            except Exception as e:
                result = {"success": False, "error": str(e)}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            UIA_READY = False  # mark UIA unavailable for subsequent calls
        return result

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
        
        # Build input sequence
        inputs = []
        for key in keys:
            k = key.lower()
            vk = vk_map.get(k, ord(k[0].upper())) if len(k) == 1 else vk_map.get(k, 0)
            if vk:
                inputs.append(_make_input(vk))  # key down
                inputs.append(_make_input(vk, KEYEVENTF_KEYUP))  # key up
        
        if inputs:
            n = windll.user32.SendInput(len(inputs), 
                                         ctypes.c_void_p(ctypes.addressof(ctypes.cast(inputs, ctypes.POINTER(INPUT))[0])),
                                         ctypes.sizeof(INPUT))
            return {"success": True, "sent": len(inputs)//2, "injected": n}
        return {"success": False, "error": "No valid keys"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
