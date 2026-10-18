"""Full-screen pulsing glow border overlay — mirrors the Android GlowBorderView.

Shows a pulsing rainbow (or solid-color) border around the entire screen while
CoAgent is actively working. Pulses until an explicit stop/done; stops on
'/glow/done' just like the Android 'done' action.

Routes:
  POST /glow/start  {color, speed}   (color: rainbow|red|blue|green|cyan|purple|amber|white)
  POST /glow/stop                    (hide immediately)
  POST /glow/done                    (alias for stop — parity with Android)
  GET  /glow/status
"""

import ctypes
import math
import threading
import time
from ctypes import wintypes

from flask import Blueprint, jsonify

from shared import _console, _json_body, _wrap_registered_blueprint_routes

glow_bp = Blueprint("glow", __name__)

GLOW_COLORS = {
    "rainbow": None,
    "red": (248, 81, 73),
    "blue": (88, 166, 255),
    "green": (63, 185, 80),
    "cyan": (0, 200, 255),
    "purple": (163, 113, 247),
    "amber": (255, 166, 87),
    "white": (255, 255, 255),
}
GLOW_SPEED_MS = {"slow": 6000, "normal": 3000, "fast": 1500}
DRAW_SCALE = 4           # draw the border small, then scale up (fast + soft)
FRAME_SEC = 0.1          # ~10fps animation

_LOCK = threading.RLock()
_STATE = {"active": False, "color": "rainbow", "speed": "slow", "mode": None, "error": None}
_STOP_EVENT = None
_THREAD = None
_TOKEN = 0
_WNDPROC_REF = None


def _hsv_to_rgb(h):
    """h in [0, 360)."""
    c = 0.85
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = 1.0 - c
    r, g, b = {
        0: (c, x, 0), 1: (x, c, 0), 2: (0, c, x),
        3: (0, x, c), 4: (x, 0, c), 5: (c, 0, x),
    }[int(h // 60) % 6]
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


def _screen_size():
    user32 = ctypes.windll.user32
    # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
    x = user32.GetSystemMetrics(76)
    y = user32.GetSystemMetrics(77)
    w = user32.GetSystemMetrics(78)
    h = user32.GetSystemMetrics(79)
    if w <= 0 or w > 100000:
        w = user32.GetSystemMetrics(0)
    if h <= 0 or h > 100000:
        h = user32.GetSystemMetrics(1)
    return x, y, w, h


def _render_border(dw, dh, full_w, full_h, rgb, pulse):
    """Draw a soft glow border only (no hard line), resize to full screen."""
    from PIL import Image, ImageDraw, ImageFilter

    t = max(2, int(min(dw, dh) * 0.02))
    glow = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    a = int(110 + 90 * pulse)
    for i in range(3):
        inset = i * 3
        gd.rounded_rectangle(
            [inset, inset, dw - 1 - inset, dh - 1 - inset],
            radius=t,
            outline=rgb + (max(15, a // (i + 1)),),
            width=max(2, t - i),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, t * 1.2)))
    if (dw, dh) != (full_w, full_h):
        glow = glow.resize((full_w, full_h), Image.BILINEAR)
    return glow


def _premultiplied_bgra(image):
    import numpy as np

    arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    out = np.empty_like(arr)
    out[..., 0] = (arr[..., 2].astype(np.uint16) * arr[..., 3] // 255).astype(np.uint8)
    out[..., 1] = (arr[..., 1].astype(np.uint16) * arr[..., 3] // 255).astype(np.uint8)
    out[..., 2] = (arr[..., 0].astype(np.uint16) * arr[..., 3] // 255).astype(np.uint8)
    out[..., 3] = arr[..., 3]
    return out.tobytes()


def _run_glow(config, stop_event, token, ready_event):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WS_POPUP = 0x80000000
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
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
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        HWND, HMENU, HINSTANCE, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = HWND
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = HDC
    user32.ReleaseDC.argtypes = [HWND, HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    COLORREF = getattr(wintypes, "COLORREF", wintypes.DWORD)
    user32.UpdateLayeredWindow.argtypes = [
        HWND, HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
        HDC, ctypes.POINTER(POINT), COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.DestroyWindow.argtypes = [HWND]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = HINSTANCE
    gdi32.CreateCompatibleDC.argtypes = [HDC]
    gdi32.CreateCompatibleDC.restype = HDC
    gdi32.CreateDIBSection.argtypes = [
        HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
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
    global _WNDPROC_REF
    _WNDPROC_REF = wnd_proc_ref

    screen_x, screen_y, screen_w, screen_h = _screen_size()
    dw, dh = screen_w // DRAW_SCALE, screen_h // DRAW_SCALE

    class_name = "HermesCoAgentGlowBorder"
    hinstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc = ctypes.cast(wnd_proc_ref, ctypes.c_void_p).value
    wc.hInstance = hinstance
    wc.lpszClassName = class_name
    ctypes.set_last_error(0)
    atom = user32.RegisterClassW(ctypes.byref(wc))
    reg_err = ctypes.get_last_error()
    if not atom and reg_err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
        raise OSError(f"RegisterClassW failed: {reg_err}")

    ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(
        ex_style, class_name, "Hermes CoAgent Glow", WS_POPUP,
        screen_x, screen_y, screen_w, screen_h, None, None, hinstance, None,
    )
    if not hwnd:
        raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")

    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = None
    old_bitmap = None
    try:
        bits = ctypes.c_void_p()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = screen_w
        bmi.bmiHeader.biHeight = -screen_h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not bitmap or not bits:
            raise OSError("CreateDIBSection failed")
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

        dst = POINT(screen_x, screen_y)
        size = SIZE(screen_w, screen_h)
        src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        solid = GLOW_COLORS.get(config["color"])
        hue_ms = GLOW_SPEED_MS.get(config.get("speed") or "slow", 6000)
        hue = 0.0
        start_t = time.monotonic()
        user32.ShowWindow(hwnd, 8)
        with _LOCK:
            _STATE.update(active=True, mode="native", error=None, color=config["color"], speed=config.get("speed") or "slow")
        ready_event.set()

        def _paint():
            pulse = 0.5 + 0.5 * math.sin((time.monotonic() - start_t) * (2 * math.pi) / 1.2)
            rgb = solid if solid else _hsv_to_rgb(hue % 360)
            img = _render_border(dw, dh, screen_w, screen_h, rgb, pulse)
            data = _premultiplied_bgra(img)
            ctypes.memmove(bits, data, len(data))
            if not user32.UpdateLayeredWindow(
                hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
                mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
            ):
                raise OSError("UpdateLayeredWindow failed")

        _paint()
        _console("[glow] border painted")
        msg = MSG()
        last = time.monotonic()
        while not stop_event.is_set():
            while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            now = time.monotonic()
            if now - last >= FRAME_SEC:
                last = now
                if not solid:
                    hue += (FRAME_SEC * 360.0) / (hue_ms / 1000.0)
                try:
                    _paint()
                except OSError:
                    break
            time.sleep(0.01)
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
        with _LOCK:
            if token == _TOKEN:
                _STATE.update(active=False, mode=None, error=None)


def _get_monitors():
    """Return [(x, y, w, h), ...] for each monitor via EnumDisplayMonitors."""
    user32 = ctypes.windll.user32
    monitors = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(RECT), wintypes.LPARAM,
    )

    def _cb(hmon, hdc, rect, lparam):
        r = rect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    cb = MONITORENUMPROC(_cb)
    user32.EnumDisplayMonitors(None, None, cb, 0)
    if not monitors:
        _, _, w, h = _screen_size()
        monitors = [(0, 0, w, h)]
    return monitors


def _banner_for_monitor(stop_event, mx, my, mw, mh):
    """Top banner on one monitor: 'Controlled by Hermes CoAgent' + Stop button."""
    try:
        import tkinter as tk
    except ImportError:
        return
    H = 44
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{mw}x{H}+{mx}+{my}")
    root.configure(bg="#0d141e")
    frame = tk.Frame(root, bg="#0d141e")
    frame.pack(fill="both", expand=True)

    def _stop():
        stop_event.set()
        try:
            root.destroy()
        except Exception:
            pass

    lbl = tk.Label(frame, text="Computer being controlled by Coagent", bg="#0d141e",
                   fg="#58a6ff", font=("Segoe UI", 12, "bold"))
    lbl.pack(side="left", padx=(18, 8))
    btn = tk.Button(frame, text="Stop", command=_stop, bg="#1f6feb", fg="white",
                    activebackground="#1158c7", activeforeground="white", relief="flat",
                    font=("Segoe UI", 11, "bold"), bd=0, highlightthickness=0,
                    padx=16, pady=2, cursor="hand2")
    btn.pack(side="right", padx=(8, 18))

    def _poll():
        if stop_event.is_set():
            try:
                root.destroy()
            except Exception:
                pass
        else:
            root.after(200, _poll)

    root.after(200, _poll)
    root.mainloop()


def _run_banner(stop_event):
    """Spawn one banner+stop thread per monitor."""
    for m in _get_monitors():
        threading.Thread(
            target=_banner_for_monitor, args=(stop_event, *m),
            name="glow-banner", daemon=True,
        ).start()


def _start_glow(config):
    global _STOP_EVENT, _THREAD, _TOKEN
    with _LOCK:
        prev = _THREAD
        if _STOP_EVENT:
            _STOP_EVENT.set()
        _TOKEN += 1
        token = _TOKEN
        stop_event = threading.Event()
        ready_event = threading.Event()
        _STOP_EVENT = stop_event
    if prev is not None and prev.is_alive():
        prev.join(timeout=0.3)
    try:
        import ctypes  # noqa: F401
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("Windows desktop APIs unavailable")
        thread = threading.Thread(
            target=_run_glow, args=(config, stop_event, token, ready_event),
            name="glow-border", daemon=True,
        )
        with _LOCK:
            _THREAD = thread
        thread.start()
        _run_banner(stop_event)  # one "Controlled by Hermes CoAgent" + Stop banner per monitor
        ready_event.wait(timeout=1.0)
        with _LOCK:
            return dict(_STATE)
    except Exception as exc:
        with _LOCK:
            _STATE.update(active=False, mode="fallback", error=f"{type(exc).__name__}: {exc}")
            return dict(_STATE)


def _stop_glow():
    with _LOCK:
        if _STOP_EVENT:
            _STOP_EVENT.set()
        _STATE.update(active=False, mode=None, error=None)
        return dict(_STATE)


@glow_bp.route("/glow/start", methods=["POST"])
def route_glow_start():
    data = _json_body()
    color = str(data.get("color") or "rainbow").strip().lower()
    speed = str(data.get("speed") or "slow").strip().lower()
    if color not in GLOW_COLORS:
        return jsonify({"error": f"color must be one of {sorted(GLOW_COLORS)}"}), 400
    if speed not in GLOW_SPEED_MS:
        return jsonify({"error": f"speed must be one of {sorted(GLOW_SPEED_MS)}"}), 400
    return jsonify(_start_glow({"color": color, "speed": speed}))


@glow_bp.route("/glow/stop", methods=["POST"])
def route_glow_stop():
    return jsonify(_stop_glow())


@glow_bp.route("/glow/done", methods=["POST"])
def route_glow_done():
    return jsonify(_stop_glow())


@glow_bp.route("/glow/status", methods=["GET"])
def route_glow_status():
    with _LOCK:
        return jsonify(dict(_STATE))


def register_routes(app, state, require_auth):
    app.register_blueprint(glow_bp)
    _wrap_registered_blueprint_routes(app, glow_bp.name, require_auth)
    state.glow_border = {"status": "registered"}
