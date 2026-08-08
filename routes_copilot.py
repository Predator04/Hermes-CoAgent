"""Pattern-based AI co-pilot routes."""
import ctypes
import ctypes.wintypes
import re
import subprocess
import time
import webbrowser
from flask import jsonify
from shared import _json_body, _log, _missing_field

CLICKABLE_TYPES = {
    "Button", "CheckBox", "ComboBox", "Edit", "Hyperlink", "ListItem",
    "MenuItem", "RadioButton", "TabItem", "Text",
}
OCR_CLICK_WORDS = {
    "ok", "yes", "no", "cancel", "save", "open", "close", "next", "back",
    "finish", "apply", "submit", "search", "send", "login", "sign", "run",
}
APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
}
URL_MAP = {
    "google": "https://www.google.com/",
    "youtube": "https://www.youtube.com/",
    "gmail": "https://mail.google.com/",
    "github": "https://github.com/",
}

def _rect_center(rect):
    if not isinstance(rect, dict):
        return None
    left = rect.get("left", rect.get("x", 0))
    top = rect.get("top", rect.get("y", 0))
    width = rect.get("width", 0)
    height = rect.get("height", 0)
    if not width and "right" in rect:
        width = rect.get("right", 0) - left
    if not height and "bottom" in rect:
        height = rect.get("bottom", 0) - top
    try:
        return {"x": int(left + width / 2), "y": int(top + height / 2)}
    except Exception:
        return None

def _bbox_center(bbox):
    try:
        if isinstance(bbox, dict):
            return _rect_center(bbox)
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x, y, w, h = bbox[:4]
            return {"x": int(x + w / 2), "y": int(y + h / 2)}
    except Exception:
        pass
    return None

def _get_cursor_pos():
    try:
        import pyautogui
        x, y = pyautogui.position()
        return {"x": int(x), "y": int(y)}
    except Exception:
        try:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            return {"x": int(point.x), "y": int(point.y)}
        except Exception:
            return {"x": 0, "y": 0}

def _winapi_windows(limit=80):
    wins = []
    try:
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_cb(hwnd, _):
            try:
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title:
                    wins.append({"title": title, "hwnd": int(hwnd), "source": "winapi"})
            except Exception:
                pass
            return len(wins) < limit

        cb = enum_proc(enum_cb)
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        pass
    return wins[:limit]

def _walk_uia(node, elements, windows, depth=0, limit=150):
    if len(elements) >= limit:
        return
    if not isinstance(node, dict):
        return
    name = (node.get("name") or "").strip()
    control_type = node.get("control_type") or ""
    rect = node.get("rect") or {}
    if depth == 1 and name:
        windows.append({
            "title": name,
            "control_type": control_type,
            "rect": rect,
            "source": "uia",
        })
    center = _rect_center(rect)
    if name and center and (control_type in CLICKABLE_TYPES or depth <= 2):
        elements.append({
            "source": "uia",
            "label": name,
            "control_type": control_type,
            "rect": rect,
            "center": center,
            "suggested_action": {"type": "click", **center},
        })
    for child in node.get("children", []) or []:
        _walk_uia(child, elements, windows, depth + 1, limit)

def _uia_snapshot():
    try:
        from routes_uia import _get_uia_engine
        ue = _get_uia_engine()
        snap = ue.uia_snapshot(timeout=5)
        if not snap.get("success"):
            return {"success": False, "error": snap.get("error", "UIA unavailable"),
                    "elements": [], "windows": []}
        elements = []
        windows = []
        _walk_uia(snap.get("tree", {}), elements, windows)
        return {"success": True, "elements": elements, "windows": windows,
                "tree_name": snap.get("tree", {}).get("name", "Desktop")}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}",
                "elements": [], "windows": []}

def _ocr_snapshot():
    try:
        from routes_ocr import _screen_img, _windows_ocr
        img = _screen_img(force=True)
        if img is None:
            return {"success": False, "error": "Cannot capture screen", "words": [], "text": ""}
        result = _windows_ocr(img)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "OCR unavailable"),
                    "words": [], "text": ""}
        return {"success": True, "words": result.get("words", []),
                "text": result.get("text", ""), "word_count": result.get("word_count", 0)}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "words": [], "text": ""}

def _ocr_clickables(words, limit=30):
    items = []
    for word in words or []:
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
        if normalized not in OCR_CLICK_WORDS:
            continue
        center = _bbox_center(word.get("bbox"))
        if not center:
            continue
        items.append({
            "source": "ocr",
            "label": text,
            "control_type": "Text",
            "bbox": word.get("bbox"),
            "center": center,
            "suggested_action": {"type": "click", **center},
        })
        if len(items) >= limit:
            break
    return items

def _dedupe_elements(elements, limit=60):
    seen = set()
    output = []
    for item in elements:
        center = item.get("center") or {}
        key = (
            item.get("source"),
            item.get("label", "").lower(),
            int(center.get("x", 0) / 8),
            int(center.get("y", 0) / 8),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    return output

def _window_suggestions(windows):
    suggestions = []
    titles = " ".join((w.get("title") or "").lower() for w in windows)
    if any(name in titles for name in ("chrome", "edge", "firefox", "browser")):
        suggestions.append({"prompt": "open youtube", "action": "open_url",
                            "reason": "Browser window is open"})
        suggestions.append({"prompt": "search for <text>", "action": "type_search",
                            "reason": "Browser window is open"})
    if "notepad" in titles:
        suggestions.append({"prompt": "type hello", "action": "type_text",
                            "reason": "Notepad is open"})
    if "file explorer" in titles or "explorer" in titles:
        suggestions.append({"prompt": "click search", "action": "click_text",
                            "reason": "Explorer window is open"})
    if not suggestions:
        suggestions.append({"prompt": "open notepad", "action": "open_app",
                            "reason": "No app-specific pattern matched"})
    return suggestions[:6]

def _collect_desktop_state(include_ocr=True):
    uia = _uia_snapshot()
    windows = uia.get("windows") or _winapi_windows()
    ocr = _ocr_snapshot() if include_ocr else {"success": False, "words": [], "text": ""}
    return {"uia": uia, "ocr": ocr, "windows": windows}

def _record_action(state, action, status="ok", detail=None):
    entry = {
        "time": time.time(),
        "source": "copilot",
        "action": action,
        "status": status,
    }
    if detail:
        entry["detail"] = detail
    try:
        history = getattr(state, "action_history", None)
        if history is not None:
            history.append(entry)
            max_history = int(getattr(state, "max_history", 1000))
            del history[:-max_history]
    except Exception:
        pass
    return entry

def _recent_actions(state, limit=20):
    actions = []
    try:
        actions.extend(list(getattr(state, "action_history", []) or []))
    except Exception:
        pass
    try:
        import routes_media
        actions.extend(list(getattr(routes_media, "_action_history", []) or []))
    except Exception:
        pass
    actions.sort(key=lambda a: a.get("time", 0) if isinstance(a, dict) else 0)
    return actions[-limit:]

def _launch_app_or_url(target):
    target = target.strip().strip('"').strip("'")
    lowered = target.lower()
    if lowered in URL_MAP:
        webbrowser.open_new_tab(URL_MAP[lowered])
        return {"status": "ok", "kind": "url", "target": target, "url": URL_MAP[lowered]}
    if re.match(r"^https?://", target):
        webbrowser.open_new_tab(target)
        return {"status": "ok", "kind": "url", "target": target, "url": target}
    if "." in lowered and " " not in lowered:
        url = "https://" + target if not lowered.startswith("http") else target
        webbrowser.open_new_tab(url)
        return {"status": "ok", "kind": "url", "target": target, "url": url}
    for key, exe in APP_MAP.items():
        if key in lowered:
            create_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=create_flags)
            return {"status": "ok", "kind": "app", "target": target, "app": exe}
    return {"status": "error", "error": f"No app or URL pattern matched '{target}'"}

def _find_click_target(target):
    target = target.strip()
    if not target:
        return None
    try:
        from routes_uia import _get_uia_engine
        ue = _get_uia_engine()
        result = ue.find_on_screen(target)
        for match in result.get("matches", []):
            center = None
            raw_center = match.get("center")
            if isinstance(raw_center, (list, tuple)) and len(raw_center) >= 2:
                center = {"x": int(raw_center[0]), "y": int(raw_center[1])}
            elif isinstance(raw_center, dict):
                center = {"x": int(raw_center.get("x", 0)), "y": int(raw_center.get("y", 0))}
            if center is None:
                center = _bbox_center(match.get("bbox"))
            if center:
                return {"source": "uia", "label": match.get("name", target), "center": center}
    except Exception:
        pass

    ocr = _ocr_snapshot()
    needle = target.lower()
    for word in ocr.get("words", []):
        text = str(word.get("text", ""))
        if needle in text.lower():
            center = _bbox_center(word.get("bbox"))
            if center:
                return {"source": "ocr", "label": text, "center": center}
    return None

def _split_prompt(prompt):
    parts = re.split(r"\s+(?:and then|then|and)\s+", prompt.strip(), flags=re.I)
    return [p.strip(" .") for p in parts if p.strip(" .")]

def _run_clause(clause, state):
    lowered = clause.lower().strip()
    if not lowered:
        return False, {"action": "noop", "status": "skipped"}
    if getattr(state, "emergency_stop", False):
        return True, {"action": "blocked", "status": "error", "error": "Emergency stop engaged"}

    m = re.match(r"^(open|launch|start)\s+(.+)$", clause, flags=re.I)
    if m:
        target = m.group(2)
        result = _launch_app_or_url(target)
        status = result.pop("status")
        if status == "ok":
            time.sleep(0.75)
        return True, {"action": "open", "target": target, "status": status, **result}

    m = re.match(r"^(type|write|enter text)\s+(.+)$", clause, flags=re.I)
    if m:
        text = m.group(2).strip().strip('"').strip("'")
        from routes_mouse import _key_action
        _key_action("type", text, state)
        return True, {"action": "type", "text": text, "status": "ok"}

    m = re.match(r"^(click|select|press)\s+(.+)$", clause, flags=re.I)
    if m:
        target = m.group(2).strip()
        key_match = re.match(r"^(ctrl|control|alt|shift|win|enter|tab|esc|escape|backspace|delete|space|f\d{1,2})(?:[+\s].*)?$",
                             target, flags=re.I)
        if lowered.startswith("press ") and key_match:
            keys = [k for k in re.split(r"[+\s]+", target.lower()) if k]
            from routes_mouse import _key_action
            _key_action("hotkey", keys, state)
            return True, {"action": "hotkey", "keys": keys, "status": "ok"}
        match = _find_click_target(target)
        if not match:
            return True, {"action": "click", "target": target, "status": "error",
                          "error": "No matching UIA or OCR element found"}
        from routes_mouse import _execute_action_wrapper
        center = match["center"]
        _execute_action_wrapper({"type": "click", "x": center["x"], "y": center["y"],
                                 "background": True}, state)
        return True, {"action": "click", "target": target, "status": "ok",
                      "source": match.get("source"), "x": center["x"], "y": center["y"]}

    m = re.match(r"^scroll(?:\s+(up|down))?(?:\s+(-?\d+))?$", clause, flags=re.I)
    if m:
        direction = (m.group(1) or "down").lower()
        clicks = int(m.group(2) or (3 if direction == "up" else -3))
        from routes_mouse import _execute_action_wrapper
        _execute_action_wrapper({"type": "scroll", "clicks": clicks}, state)
        return True, {"action": "scroll", "clicks": clicks, "status": "ok"}

    m = re.match(r"^wait(?:\s+(\d+(?:\.\d+)?))?", clause, flags=re.I)
    if m:
        seconds = min(float(m.group(1) or 1), 10.0)
        time.sleep(seconds)
        return True, {"action": "wait", "seconds": seconds, "status": "ok"}

    m = re.match(r"^(search for|search)\s+(.+)$", clause, flags=re.I)
    if m:
        text = m.group(2).strip()
        from routes_mouse import _key_action
        _key_action("type", text, state)
        _key_action("hotkey", ["enter"], state)
        return True, {"action": "search", "text": text, "status": "ok"}

    return False, {"action": "unknown", "text": clause, "status": "error",
                   "error": "No automation pattern matched"}

def register_routes(app, state, require_auth):
    @app.route("/copilot/suggest", methods=["GET"])
    @require_auth
    def route_copilot_suggest():
        started = time.time()
        desktop = _collect_desktop_state(include_ocr=True)
        uia_elements = desktop["uia"].get("elements", [])
        ocr_elements = _ocr_clickables(desktop["ocr"].get("words", []))
        elements = _dedupe_elements(uia_elements + ocr_elements)
        suggestions = _window_suggestions(desktop.get("windows", []))
        _log(f"CoPilot suggest: elements={len(elements)} ocr={desktop['ocr'].get('success')}")
        return jsonify({
            "status": "ok",
            "clickable_elements": elements,
            "count": len(elements),
            "suggestions": suggestions,
            "windows": desktop.get("windows", [])[:30],
            "ocr": {
                "success": desktop["ocr"].get("success", False),
                "word_count": desktop["ocr"].get("word_count", len(desktop["ocr"].get("words", []))),
                "text_preview": desktop["ocr"].get("text", "")[:500],
                "error": desktop["ocr"].get("error"),
            },
            "uia": {
                "success": desktop["uia"].get("success", False),
                "error": desktop["uia"].get("error"),
            },
            "elapsed_ms": round((time.time() - started) * 1000, 1),
        })

    @app.route("/copilot/automate", methods=["POST"])
    @require_auth
    def route_copilot_automate():
        d = _json_body()
        prompt = str(d.get("prompt", "")).strip()
        if not prompt:
            return _missing_field("prompt")
        steps = []
        handled_any = False
        _log(f"CoPilot automate prompt: {prompt[:300]}")
        for clause in _split_prompt(prompt):
            handled, step = _run_clause(clause, state)
            handled_any = handled_any or handled
            step["clause"] = clause
            step["step"] = len(steps) + 1
            steps.append(step)
            _record_action(state, {"prompt": prompt, "clause": clause, "step": step},
                           status=step.get("status", "ok"))
            if step.get("status") == "error" and d.get("stop_on_error", True):
                break
        status = "ok" if steps and all(s.get("status") == "ok" for s in steps) else "partial"
        code = 200 if handled_any else 400
        return jsonify({"status": status, "prompt": prompt, "steps": steps}), code

    @app.route("/copilot/observe", methods=["GET"])
    @require_auth
    def route_copilot_observe():
        desktop = _collect_desktop_state(include_ocr=False)
        windows = desktop.get("windows") or _winapi_windows()
        recent = _recent_actions(state)
        _log(f"CoPilot observe: windows={len(windows)} recent={len(recent)}")
        return jsonify({
            "status": "ok",
            "windows": windows[:80],
            "window_count": len(windows),
            "cursor": _get_cursor_pos(),
            "recent_actions": recent,
            "recent_activity_count": len(recent),
            "uia": {
                "success": desktop["uia"].get("success", False),
                "error": desktop["uia"].get("error"),
            },
        })
