"""Transparent desktop HUD overlay routes."""

import json
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify

from shared import COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes


hud_bp = Blueprint("hud", __name__)

HUD_STATUS_FILE = COAGENT_DIR / "hud_status.json"
HUD_WIDTH = 300
HUD_HEIGHT = 60

COLOR_MAP = {
    "green": (35, 220, 90, 235),
    "yellow": (255, 205, 55, 235),
    "red": (255, 70, 70, 235),
    "cyan": (50, 210, 255, 235),
}
POSITIONS = {"top-right", "bottom-left", "top-left", "bottom-right"}

_HUD_LOCK = threading.RLock()
_HUD_STATE = {
    "visible": False,
    "text": "",
    "color": "cyan",
    "position": "top-right",
    "timeout": 0,
    "progress": None,
    "mode": "none",
    "error": None,
    "updated_at": None,
}
_HUD_STOP_EVENT = None
_HUD_THREAD = None
_HUD_TOKEN = 0


def _now_text():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _write_status(**updates):
    with _HUD_LOCK:
        _HUD_STATE.update(updates)
        _HUD_STATE["updated_at"] = _now_text()
        payload = dict(_HUD_STATE)
    try:
        tmp = HUD_STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(HUD_STATUS_FILE)
    except Exception as exc:
        _console(f"[hud] status write failed: {type(exc).__name__}: {exc}")
    return payload


def _render_hud_bitmap(text, color_name):
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    fg = COLOR_MAP.get(color_name, COLOR_MAP["cyan"])
    image = Image.new("RGBA", (HUD_WIDTH, HUD_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, HUD_WIDTH - 1, HUD_HEIGHT - 1], radius=8, fill=(12, 18, 24, 190), outline=fg, width=2)
    draw.ellipse([14, 21, 28, 35], fill=fg)
    try:
        font = ImageFont.truetype("segoeui.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    clean = " ".join(str(text or "").split())[:80]
    bbox = draw.textbbox((0, 0), clean, font=font)
    text_h = bbox[3] - bbox[1]
    draw.text((38, max(8, (HUD_HEIGHT - text_h) // 2 - 1)), clean, fill=(245, 250, 255, 245), font=font)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return image


def _position_xy(position):
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    screen_w = int(user32.GetSystemMetrics(0))
    screen_h = int(user32.GetSystemMetrics(1))
    if screen_w <= 0 or screen_w > 100000:
        screen_w = 1920
    if screen_h <= 0 or screen_h > 100000:
        screen_h = 1080
    margin = 18
    if position == "top-left":
        return margin, margin
    if position == "bottom-left":
        return margin, max(margin, screen_h - HUD_HEIGHT - margin)
    if position == "bottom-right":
        return max(margin, screen_w - HUD_WIDTH - margin), max(margin, screen_h - HUD_HEIGHT - margin)
    return max(margin, screen_w - HUD_WIDTH - margin), margin


def _premultiplied_bgra(image):
    rgba = image.convert("RGBA")
    raw = bytearray()
    for r, g, b, a in rgba.getdata():
        raw.extend((
            (b * a) // 255,
            (g * a) // 255,
            (r * a) // 255,
            a,
        ))
    return bytes(raw)


def _run_native_hud(config, stop_event, token, ready_event):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WS_POPUP = 0x80000000
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01
    BI_RGB = 0
    DIB_RGB_COLORS = 0
    WM_DESTROY = 0x0002
    PM_REMOVE = 0x0001

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_byte),
            ("BlendFlags", ctypes.c_byte),
            ("SourceConstantAlpha", ctypes.c_byte),
            ("AlphaFormat", ctypes.c_byte),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [
            ("rgbBlue", ctypes.c_byte),
            ("rgbGreen", ctypes.c_byte),
            ("rgbRed", ctypes.c_byte),
            ("rgbReserved", ctypes.c_byte),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

    HINSTANCE = getattr(wintypes, "HINSTANCE", wintypes.HANDLE)
    HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
    HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
    HWND = getattr(wintypes, "HWND", wintypes.HANDLE)
    HDC = getattr(wintypes, "HDC", wintypes.HANDLE)
    HBITMAP = getattr(wintypes, "HBITMAP", wintypes.HANDLE)
    HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
    ATOM = getattr(wintypes, "ATOM", wintypes.WORD)
    WPARAM = getattr(wintypes, "WPARAM", ctypes.c_size_t)
    LPARAM = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)
    LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", HWND),
            ("message", wintypes.UINT),
            ("wParam", WPARAM),
            ("lParam", LPARAM),
            ("time", wintypes.DWORD),
            ("pt", POINT),
        ]

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, WPARAM, LPARAM)

    user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        HWND,
        HMENU,
        HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = HWND
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = HDC
    user32.ReleaseDC.argtypes = [HWND, HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    COLORREF = getattr(wintypes, "COLORREF", wintypes.DWORD)
    user32.UpdateLayeredWindow.argtypes = [
        HWND,
        HDC,
        ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE),
        HDC,
        ctypes.POINTER(POINT),
        COLORREF,
        ctypes.POINTER(BLENDFUNCTION),
        wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.DestroyWindow.argtypes = [HWND]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = HINSTANCE
    gdi32.CreateCompatibleDC.argtypes = [HDC]
    gdi32.CreateCompatibleDC.restype = HDC
    gdi32.CreateDIBSection.argtypes = [
        HDC,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = HBITMAP
    gdi32.SelectObject.argtypes = [HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [HDC]

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wnd_proc_ref = WNDPROC(wnd_proc)
    class_name = "HermesCoAgentHudOverlay"
    hinstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc = ctypes.cast(wnd_proc_ref, ctypes.c_void_p).value
    wc.hInstance = hinstance
    wc.lpszClassName = class_name
    ctypes.set_last_error(0)
    atom = user32.RegisterClassW(ctypes.byref(wc))
    register_error = ctypes.get_last_error()
    if not atom and register_error != 1410:  # ERROR_CLASS_ALREADY_EXISTS
        raise OSError(f"RegisterClassW failed: {register_error}")

    x, y = _position_xy(config["position"])
    ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
    ctypes.set_last_error(0)
    hwnd = user32.CreateWindowExW(
        ex_style,
        class_name,
        "Hermes CoAgent HUD",
        WS_POPUP,
        x,
        y,
        HUD_WIDTH,
        HUD_HEIGHT,
        None,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")

    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = None
    old_bitmap = None
    try:
        image = _render_hud_bitmap(config["text"], config["color"])
        bits = ctypes.c_void_p()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = HUD_WIDTH
        bmi.bmiHeader.biHeight = -HUD_HEIGHT
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not bitmap or not bits:
            raise OSError("CreateDIBSection failed")
        data = _premultiplied_bgra(image)
        ctypes.memmove(bits, data, len(data))
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
        dst = POINT(x, y)
        size = SIZE(HUD_WIDTH, HUD_HEIGHT)
        src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size), mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        if not ok:
            raise OSError("UpdateLayeredWindow failed")
        user32.ShowWindow(hwnd, 8)
        _write_status(visible=True, mode="native", error=None, **config)
        ready_event.set()
        deadline = time.time() + float(config["timeout"]) if float(config["timeout"]) > 0 else None
        msg = MSG()
        while not stop_event.is_set():
            while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if deadline and time.time() >= deadline:
                break
            time.sleep(0.05)
    finally:
        if old_bitmap:
            gdi32.SelectObject(mem_dc, old_bitmap)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        if screen_dc:
            user32.ReleaseDC(None, screen_dc)
        if hwnd:
            user32.DestroyWindow(hwnd)
        with _HUD_LOCK:
            current = token == _HUD_TOKEN
        if current:
            _write_status(visible=False, mode="native", error=None)


def _fallback_show(config, error=None):
    payload = _write_status(visible=True, mode="fallback", error=error, **config)
    return payload


def _start_hud(config):
    global _HUD_STOP_EVENT, _HUD_THREAD, _HUD_TOKEN
    with _HUD_LOCK:
        if _HUD_STOP_EVENT:
            _HUD_STOP_EVENT.set()
        _HUD_TOKEN += 1
        token = _HUD_TOKEN
        stop_event = threading.Event()
        ready_event = threading.Event()
        _HUD_STOP_EVENT = stop_event

    try:
        import ctypes
        from PIL import Image  # noqa: F401
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("Windows desktop APIs unavailable")
        thread = threading.Thread(
            target=_native_hud_thread_wrapper,
            args=(config, stop_event, token, ready_event),
            name="hud-overlay",
            daemon=True,
        )
        with _HUD_LOCK:
            _HUD_THREAD = thread
        thread.start()
        ready_event.wait(timeout=0.75)
        with _HUD_LOCK:
            return dict(_HUD_STATE)
    except Exception as exc:
        return _fallback_show(config, error=f"{type(exc).__name__}: {exc}")


def _native_hud_thread_wrapper(config, stop_event, token, ready_event):
    try:
        _run_native_hud(config, stop_event, token, ready_event)
    except Exception as exc:
        _fallback_show(config, error=f"{type(exc).__name__}: {exc}")
        ready_event.set()


@hud_bp.route("/hud/show", methods=["POST"])
def route_hud_show():
    data = _json_body()
    text = str(data.get("text") or "CoAgent").strip()[:160]
    color = str(data.get("color") or "cyan").strip().lower()
    position = str(data.get("position") or "top-right").strip().lower()
    if color not in COLOR_MAP:
        return jsonify({"error": "color must be green, yellow, red, or cyan"}), 400
    if position not in POSITIONS:
        return jsonify({"error": "position must be top-right, bottom-left, top-left, or bottom-right"}), 400
    try:
        timeout = max(0, min(int(data.get("timeout", 30)), 24 * 60 * 60))
    except (TypeError, ValueError):
        timeout = 30
    config = {"text": text, "color": color, "position": position, "timeout": timeout}
    return jsonify(_start_hud(config))


@hud_bp.route("/hud/hide", methods=["POST"])
def route_hud_hide():
    with _HUD_LOCK:
        if _HUD_STOP_EVENT:
            _HUD_STOP_EVENT.set()
    return jsonify(_write_status(visible=False, mode="none", error=None))


@hud_bp.route("/hud/text", methods=["POST"])
def route_hud_text():
    data = _json_body()
    text = str(data.get("text") or "").strip()[:160]
    if not text:
        return jsonify({"error": "text is required"}), 400
    updates = {"text": text}
    color = str(data.get("color") or "").strip().lower()
    if color:
        if color not in COLOR_MAP:
            return jsonify({"error": "color must be green, yellow, red, or cyan"}), 400
        updates["color"] = color
    return jsonify(_write_status(**updates))


@hud_bp.route("/hud/progress", methods=["POST"])
def route_hud_progress():
    data = _json_body()
    try:
        progress = max(0, min(100, int(data.get("progress", data.get("value")))))
    except (TypeError, ValueError):
        return jsonify({"error": "progress is required"}), 400
    updates = {"progress": progress}
    if data.get("text") is not None:
        updates["text"] = str(data.get("text") or "").strip()[:160]
    return jsonify(_write_status(**updates))


@hud_bp.route("/hud/status", methods=["GET"])
def route_hud_status():
    with _HUD_LOCK:
        payload = dict(_HUD_STATE)
    if HUD_STATUS_FILE.exists():
        try:
            payload["file"] = json.loads(HUD_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            payload["file"] = None
    return jsonify(payload)


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def register_routes(app, state, require_auth):
    app.register_blueprint(hud_bp)
    _wrap_registered_blueprint_routes(app, hud_bp.name, require_auth)
    state.hud_overlay = {"status_file": str(HUD_STATUS_FILE)}
