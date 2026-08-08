"""OCR, screenshot, crop, and screen-describe routes."""
import base64
import json
import logging
import os
import tempfile
import subprocess
import time
import threading
import hashlib
import urllib.error, urllib.request
from io import BytesIO
from flask import Response, jsonify, request
from shared import _json_body, _log, _missing_field, get_host_ip, TRAY_PORT
from shared_fallbacks import FallbackChain

_LOGGER = logging.getLogger(__name__)


def _debug_backend_failure(backend, exc):
    _LOGGER.debug("%s failed: %s: %s", backend, type(exc).__name__, exc, exc_info=True)

# MSS for fast screenshots (DXGI)
_MSS_AVAILABLE = False
_MSS_LOCK = threading.Lock()
try:
    import mss
    _MSS_AVAILABLE = True
except ImportError:
    pass

# DXCam — fully lazy import (crashes from Session 0)
_DXCAM_MODULE = None
HAS_DXCAM = False

_DXCAM_LOCK = threading.Lock()
_DXCAM_CAMERAS = {}

# Screenshot cache
SCREENSHOT_CACHE_TTL = 2.0
_last_screenshot_time = 0.0
_last_screenshot_raw = b""
_last_screenshot_hash = None
_screenshot_lock = threading.Lock()
_LAST_CAPTURE_METHOD = {}
# v7.3: Pixel hash — skip capture if screen unchanged
_PIXEL_HASH_CACHE = {}
_PIXEL_HASH_LOCK = threading.Lock()
_SCREENSHOT_CACHE = {}

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

def _coerce_monitor_index(monitor_index=0):
    try:
        return max(0, int(monitor_index))
    except (TypeError, ValueError):
        return 0

def get_monitor_list():
    """Return monitor metadata, using MSS when available."""
    if _MSS_AVAILABLE:
        try:
            with _MSS_LOCK:
                with mss.mss() as sct:
                    monitors = []
                    for idx, mon in enumerate(sct.monitors):
                        monitors.append({
                            "id": idx,
                            "name": "All monitors" if idx == 0 else f"Monitor {idx}",
                            "width": int(mon.get("width", 0)),
                            "height": int(mon.get("height", 0)),
                            "left": int(mon.get("left", 0)),
                            "top": int(mon.get("top", 0)),
                            "is_primary": idx == 1,
                        })
                    if monitors:
                        return monitors
        except Exception as e:
            _debug_backend_failure("MSS monitor enumeration", e)
            _log(f"MSS monitor enumeration failed: {type(e).__name__}: {e}")
    try:
        import pyautogui
        w, h = pyautogui.size()
        return [{"id": 0, "name": "Primary monitor", "width": int(w), "height": int(h),
                 "left": 0, "top": 0, "is_primary": True}]
    except (ImportError, OSError, RuntimeError) as e:
        _debug_backend_failure("pyautogui monitor fallback", e)
        return [{"id": 0, "name": "Primary monitor", "width": 1920, "height": 1080,
                 "left": 0, "top": 0, "is_primary": True}]

def _monitor_bounds(monitor_index=0):
    monitor_index = _coerce_monitor_index(monitor_index)
    monitors = get_monitor_list()
    for mon in monitors:
        if mon.get("id") == monitor_index:
            return mon
    return monitors[0] if monitors else {"id": 0, "name": "Primary monitor", "width": 1920,
                                         "height": 1080, "left": 0, "top": 0,
                                         "is_primary": True}

def _request_monitor(default=0):
    return _coerce_monitor_index(request.args.get("monitor", default))

def _grab_screen_mss(force=False, monitor_index=0):
    """Capture a monitor via MSS and return PNG bytes."""
    global _last_screenshot_time, _PIXEL_HASH_CACHE
    if not _MSS_AVAILABLE or not HAS_PIL:
        return b""
    monitor_index = _coerce_monitor_index(monitor_index)
    try:
        with _MSS_LOCK:
            with mss.mss() as sct:
                if monitor_index >= len(sct.monitors):
                    monitor_index = 0
                mon = sct.monitors[monitor_index]
                sct_img = sct.grab(mon)
                raw = sct_img.rgb
                size = sct_img.size

        # v7.3: Quick pixel hash to detect screen changes before PNG encode.
        step = 100
        sample = bytearray()
        for i in range(0, len(raw) // 3, step):
            base = 3 * i
            sample.extend(raw[base:base + 3])
        hash_val = hashlib.blake2b(bytes(sample), digest_size=8).digest()
        with _PIXEL_HASH_LOCK:
            cached = _SCREENSHOT_CACHE.get(monitor_index, {})
            cached_raw = cached.get("raw", b"")
            if not force and hash_val == _PIXEL_HASH_CACHE.get(monitor_index) and cached_raw:
                _last_screenshot_time = time.time()
                return cached_raw
            _PIXEL_HASH_CACHE[monitor_index] = hash_val

        pil_img = Image.frombytes("RGB", size, raw)
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        # Cache the encoded PNG so next identical-frame request skips encode
        with _PIXEL_HASH_LOCK:
            _SCREENSHOT_CACHE[monitor_index] = {"raw": png_bytes, "time": time.time()}
        return png_bytes
    except Exception as e:
        _debug_backend_failure("MSS capture", e)
        _log(f"MSS capture failed: {type(e).__name__}: {e}")
        return b""

def _screenshot_dxcam(force=False, monitor_index=0):
    """Capture via DXCam and return JPEG bytes, or None on failure.
    Handles monitor_index=0 (all monitors/virtual screen) by falling through
    to MSS/PIL which handle virtual screen capture correctly."""
    global HAS_DXCAM, _DXCAM_MODULE
    with _DXCAM_LOCK:
        if not HAS_DXCAM and _DXCAM_MODULE is None:
            try:
                import dxcam as m
                _DXCAM_MODULE = m
                HAS_DXCAM = True
            except Exception as e:
                _debug_backend_failure("DXCam import", e)
                _DXCAM_MODULE = "__failed__"
            dxcam_module = _DXCAM_MODULE
    if _DXCAM_MODULE in (None, "__failed__") or not HAS_PIL:
        return None
    monitor_index = _coerce_monitor_index(monitor_index)
    # monitor_index=0 means "all monitors" (virtual screen) — DXCAM can only capture
    # individual monitors, not the virtual screen. Fall through so MSS/PIL can handle it.
    if monitor_index == 0:
        return None
    output_idx = max(0, monitor_index - 1)
    try:
        with _DXCAM_LOCK:
            camera = _DXCAM_CAMERAS.get(output_idx)
            if camera is None:
                camera = _DXCAM_MODULE.create(output_idx=output_idx, output_color="RGB")
                _DXCAM_CAMERAS[output_idx] = camera
            frame = camera.grab()
        if frame is None:
            return None
        img = Image.fromarray(frame)
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception as e:
        _debug_backend_failure("DXCam capture", e)
        _log(f"DXCam capture failed: {type(e).__name__}: {e}")
        return None

def _screenshot_mss(force=False, monitor_index=0):
    data = _grab_screen_mss(force=force, monitor_index=monitor_index)
    return data or None

def _screenshot_pil(force=False, monitor_index=0):
    if not HAS_PIL:
        return None
    try:
        from PIL import ImageGrab
        monitor_index = _coerce_monitor_index(monitor_index)
        if monitor_index:
            bounds = _monitor_bounds(monitor_index)
            left = bounds.get("left", 0)
            top = bounds.get("top", 0)
            bbox = (left, top, left + bounds.get("width", 0), top + bounds.get("height", 0))
            pil_img = ImageGrab.grab(bbox=bbox)
        else:
            try:
                pil_img = ImageGrab.grab(all_screens=True)
            except TypeError:
                pil_img = ImageGrab.grab()
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        _debug_backend_failure("PIL capture", e)
        _log(f"PIL capture failed: {type(e).__name__}: {e}")
        return None

def _screenshot_win32(force=False, monitor_index=0):
    if not HAS_PIL:
        return None
    hwnd = hwnd_dc = src_dc = mem_dc = bitmap = None
    try:
        import win32con
        import win32gui
        import win32ui

        bounds = _monitor_bounds(monitor_index)
        left = int(bounds.get("left", 0))
        top = int(bounds.get("top", 0))
        width = int(bounds.get("width", 0)) or 1920
        height = int(bounds.get("height", 0)) or 1080
        hwnd = win32gui.GetDesktopWindow()
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)
        mem_dc.BitBlt((0, 0), (width, height), src_dc, (left, top), win32con.SRCCOPY)
        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        )
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        _debug_backend_failure("Win32 capture", e)
        _log(f"Win32 capture failed: {type(e).__name__}: {e}")
        return None
    finally:
        try:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
        except Exception as e:
            _debug_backend_failure("Win32 bitmap cleanup", e)
        try:
            if mem_dc is not None:
                mem_dc.DeleteDC()
        except Exception as e:
            _debug_backend_failure("Win32 memory DC cleanup", e)
        try:
            if src_dc is not None:
                src_dc.DeleteDC()
        except Exception as e:
            _debug_backend_failure("Win32 source DC cleanup", e)
        try:
            if hwnd and hwnd_dc:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception as e:
            _debug_backend_failure("Win32 window DC cleanup", e)

def _screenshot_relay(force=False, monitor_index=0):
    data, _latency_ms, relay_error = _fetch_tray_relay_screen(timeout=2.0)
    if data:
        return data
    if relay_error:
        _debug_backend_failure("PowerShell relay capture", RuntimeError(relay_error))
        _log(f"PowerShell relay capture failed: {relay_error}")
    return None

def _ensure_png_bytes(data):
    if not data:
        return b""
    if data.startswith(b"\x89PNG"):
        return data
    if not HAS_PIL:
        return data
    try:
        img = Image.open(BytesIO(data))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        _debug_backend_failure("PNG coercion", e)
        return data

def _capture_raw(force=False, monitor_index=0):
    """Capture full screen as PNG bytes through the configured fallback chain.
    Flash-causing methods (PIL ImageGrab, Win32 BitBlt) are only used as
    absolute last resort and gated behind HERMES_COAGENT_ALLOW_FLASH_CAPTURE=1."""
    global _last_screenshot_time, _last_screenshot_raw, _PIXEL_HASH_CACHE
    monitor_index = _coerce_monitor_index(monitor_index)
    now = time.time()
    cached = _SCREENSHOT_CACHE.get(monitor_index, {})
    if not force and cached.get("raw") and (now - cached.get("time", 0)) < SCREENSHOT_CACHE_TTL:
        return cached["raw"]
    with _screenshot_lock:
        cached = _SCREENSHOT_CACHE.get(monitor_index, {})
        if not force and cached.get("raw") and (now - cached.get("time", 0)) < SCREENSHOT_CACHE_TTL:
            return cached["raw"]
        screenshot_chain = FallbackChain("screenshot")
        screenshot_chain.add_method("dxcam", _screenshot_dxcam, force, monitor_index)
        screenshot_chain.add_method("mss", _screenshot_mss, force, monitor_index)
        # PIL and Win32 cause window flashes — only use if explicitly enabled
        if os.environ.get("HERMES_COAGENT_ALLOW_FLASH_CAPTURE", "").lower() in ("1", "true", "yes"):
            screenshot_chain.add_method("pil", _screenshot_pil, force, monitor_index)
            screenshot_chain.add_method("win32", _screenshot_win32, force, monitor_index)
        # PowerShell relay is the last resort fallback
        screenshot_chain.add_method("powershell_relay", _screenshot_relay, force, monitor_index)
        try:
            img_bytes = _ensure_png_bytes(screenshot_chain.execute())
            _LAST_CAPTURE_METHOD[monitor_index] = screenshot_chain.last_success
        except Exception as e:
            _debug_backend_failure("screenshot fallback chain", e)
            _log(f"Screenshot fallback chain failed: {type(e).__name__}: {e}")
            img_bytes = b""
        if img_bytes:
            _last_screenshot_time = now
            _last_screenshot_raw = img_bytes
            _SCREENSHOT_CACHE[monitor_index] = {
                "time": now,
                "raw": img_bytes,
                "method": _LAST_CAPTURE_METHOD.get(monitor_index),
            }
        return img_bytes

def _capture_jpeg(force=False, quality=85, monitor_index=0):
    """Capture full screen as JPEG bytes."""
    data = _capture_raw(force=force, monitor_index=monitor_index)
    if not data or not HAS_PIL:
        return b""
    try:
        img = Image.open(BytesIO(data))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as e:
        _debug_backend_failure("JPEG capture", e)
        _log(f"JPEG capture failed: {type(e).__name__}: {e}")
        return b""

def _fetch_tray_relay_screen(timeout=2.0):
    """Return (jpeg_bytes, latency_ms, error) from the Session 1 tray relay."""
    start = time.perf_counter()
    errors = []
    for path in ("/screen", "/screen?format=jpeg"):
        remaining = max(0.1, timeout - (time.perf_counter() - start))
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{TRAY_PORT}{path}",
                headers=_tray_relay_headers(),
            )
            with urllib.request.urlopen(req, timeout=remaining) as resp:
                data = resp.read()
                latency_ms = round((time.perf_counter() - start) * 1000, 1)
                status = getattr(resp, "status", 200)
                content_type = resp.headers.get("Content-Type", "")
                if status == 200 and data and ("jpeg" in content_type.lower() or data.startswith(b"\xff\xd8")):
                    return data, latency_ms, None
                errors.append(f"{path}: status={status} content_type={content_type}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            errors.append(f"{path}: {type(e).__name__}: {e}")
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    return b"", latency_ms, "; ".join(errors) or "relay unavailable"


def _tray_relay_headers():
    headers = {"Accept": "image/jpeg"}
    token = ""
    try:
        import auth as _auth_mod
        if getattr(_auth_mod, "AUTH_ENABLED", False):
            token = getattr(_auth_mod, "AUTH_TOKEN", "") or ""
    except (ImportError, AttributeError) as e:
        _debug_backend_failure("auth token lookup", e)
        token = ""
    token = token or os.environ.get("COAGENT_TOKEN", "") or os.environ.get("HERMES_COAGENT_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def _probe_tray_relay(timeout=2.0):
    """Check tray relay health without fetching a full screenshot."""
    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{TRAY_PORT}/health",
            headers=_tray_relay_headers(),
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096)
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            payload = json.loads(body.decode("utf-8", errors="replace") or "{}")
            ok = getattr(resp, "status", 200) == 200 and payload.get("status") == "ok"
            return {"available": ok, "latency_ms": latency_ms, "status": payload.get("status"), "error": None}
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return {"available": False, "latency_ms": latency_ms, "status": None,
                "error": f"{type(e).__name__}: {e}"}

def _grab_screen_bytes(force=False):
    """Alias for _capture_raw."""
    return _capture_raw(force)

def _screen_img(force=False):
    """Return PIL Image from screenshot."""
    data = _capture_raw(force)
    if data and HAS_PIL:
        return Image.open(BytesIO(data))
    return None

def _check_winrt_version():
    """Return the installed winrt-runtime version for OCR diagnostics."""
    try:
        from importlib import metadata
    except ImportError as e:
        _debug_backend_failure("winrt metadata import", e)
        return None
    try:
        return metadata.version("winrt-runtime")
    except metadata.PackageNotFoundError as e:
        _debug_backend_failure("winrt metadata lookup", e)
        return None

def _windows_ocr(pil_image):
    """Use Windows.Media.Ocr to recognize text. WinRT direct path."""
    try:
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        buf.seek(0)
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.media.ocr as ocr
        import winrt.windows.storage.streams as streams
        ras = streams.InMemoryRandomAccessStream()
        ras.write_async(buf.read()).get()
        ras.seek(0)
        decoder = imaging.BitmapDecoder.create_async(ras).get()
        bitmap = decoder.get_software_bitmap_async().get()
        ocr_engine = ocr.OcrEngine.try_create_from_user_profile_languages()
        if ocr_engine is None:
            import winrt.windows.globalization as globalization
            lang = globalization.Language("en-US")
            ocr_engine = ocr.OcrEngine.try_create_from_language(lang)
        if ocr_engine is None:
            return {"success": False, "error": "No OCR engine"}
        result = ocr_engine.recognize_async(bitmap).get()
        words = []
        for line in result.lines:
            for word in line.words:
                bbox = word.bounding_rect
                words.append({"text": word.text, "confidence": 100,
                              "bbox": [int(bbox.x), int(bbox.y), int(bbox.width), int(bbox.height)]})
        return {"success": True, "words": words, "text": " ".join(w["text"] for w in words),
                "line_count": len(result.lines), "word_count": len(words)}
    except (ImportError, AttributeError, TypeError) as e:
        _log(f"WinRT OCR direct path unavailable; falling back to PowerShell: {type(e).__name__}: {e}")
        try:
            return _windows_ocr_powershell(pil_image)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            _debug_backend_failure("Windows OCR PowerShell fallback", e)
            return {"success": False, "error": "Windows OCR unavailable", "winrt_runtime": _check_winrt_version()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _windows_ocr_powershell(pil_image):
    """Fallback: Windows OCR via PowerShell (temp file approach)."""
    tmp_img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_img_path = tmp_img.name
    pil_image.save(tmp_img, format="PNG")
    tmp_img.close()
    tmp_ps1 = tempfile.NamedTemporaryFile(suffix=".ps1", mode="w", delete=False)
    tmp_ps1_path = tmp_ps1.name
    tmp_ps1.write(f"""$imgPath = "{tmp_img_path}"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$bytes = [System.IO.File]::ReadAllBytes($imgPath)
$stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
$stream.WriteAsync($bytes) | Out-Null
$stream.Seek(0)
$decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream).GetAwaiter().GetResult()
$bitmap = $decoder.GetSoftwareBitmapAsync().GetAwaiter().GetResult()
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) {{
    $lang = [Windows.Globalization.Language]::new("en-US")
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}}
$result = $engine.RecognizeAsync($bitmap).GetAwaiter().GetResult()
$output = @{{lines=@()}}
foreach ($line in $result.Lines) {{
    $words = @()
    foreach ($w in $line.Words) {{
        $words += @{{text=$w.Text; x=$w.BoundingRect.X; y=$w.BoundingRect.Y; w=$w.BoundingRect.Width; h=$w.BoundingRect.Height}}
    }}
    $output.lines += @{{text=$line.Text; words=$words}}
}}
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($output | ConvertTo-Json -Depth 10)))
Remove-Item "$imgPath" -Force -ErrorAction SilentlyContinue
""")
    tmp_ps1.close()
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_ps1_path],
                           capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(base64.b64decode(r.stdout.strip()).decode())
            words = []
            for line in data.get("lines", []):
                for w in line.get("words", []):
                    words.append({"text": w["text"], "confidence": 100,
                                  "bbox": [w["x"], w["y"], w["w"], w["h"]]})
            return {"success": True, "words": words, "text": " ".join(w["text"] for w in words),
                    "line_count": len(data.get("lines", [])), "word_count": len(words)}
        return {"success": False, "error": r.stderr[:200] if r.stderr else "unknown"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "PowerShell timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        for path in (tmp_ps1_path, tmp_img_path):
            try:
                os.unlink(path)
            except OSError:
                pass

def ocr_find_text(text, pil_img=None):
    """Find text on screen, return matches with positions."""
    if pil_img is None:
        pil_img = _screen_img(force=True)
    if pil_img is None:
        return []
    try:
        import pytesseract
        ocr_data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
        matches = []
        needle = text.lower()
        for i in range(len(ocr_data["text"])):
            if needle in ocr_data["text"][i].lower():
                x, y, w, h = (ocr_data["left"][i], ocr_data["top"][i],
                              ocr_data["width"][i], ocr_data["height"][i])
                if w > 5 and h > 5:
                    matches.append({"text": ocr_data["text"][i], "confidence": ocr_data["conf"][i],
                                    "center": {"x": x + w // 2, "y": y + h // 2},
                                    "bounds": {"x": x, "y": y, "width": w, "height": h}})
        return matches
    except ImportError:
        return [{"error": "pytesseract not installed"}]
    except Exception as e:
        return [{"error": str(e)}]

def register_routes(app, state, require_auth):
    @app.route("/screen", methods=["GET"])
    @require_auth
    def route_screen():
        monitor_requested = "monitor" in request.args
        monitor_index = _request_monitor(0)
        data = _capture_jpeg(force=True, monitor_index=monitor_index)
        if data:
            method = (_LAST_CAPTURE_METHOD.get(monitor_index) or "unknown").replace("_", "-")
            return Response(data, mimetype="image/jpeg", headers={
                "X-Capture-Method": method,
                "X-Monitor-Index": str(monitor_index) if monitor_requested else "0",
            })
        return jsonify({"error": "No screenshot", "monitor_index": monitor_index}), 500

    @app.route("/screen/probe", methods=["GET"])
    @require_auth
    def route_screen_probe():
        relay_health = _probe_tray_relay(timeout=2.0)
        relay_data, relay_latency_ms, relay_error = _fetch_tray_relay_screen(timeout=2.0)
        relay = {
            "available": bool(relay_data),
            "health": relay_health,
            "latency_ms": relay_latency_ms,
            "bytes": len(relay_data) if relay_data else 0,
            "error": relay_error,
        }
        start = time.perf_counter()
        local = {"available": False, "latency_ms": None, "bytes": 0, "error": None}
        try:
            data = _capture_jpeg(force=True)
            local["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            local["bytes"] = len(data) if data else 0
            local["available"] = bool(data)
            local["method"] = _LAST_CAPTURE_METHOD.get(0)
            if not data:
                local["error"] = "local capture returned no bytes"
        except Exception as e:
            local["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            local["error"] = f"{type(e).__name__}: {e}"
        if relay["available"]:
            method = "tray-relay"
        elif local["available"]:
            method = "local"
        else:
            method = "unavailable"
        return jsonify({
            "tray_relay": relay,
            "local_capture": local,
            "method": method,
            "screen_endpoint": "/screen returns image/jpeg bytes directly",
        })

    @app.route("/screen/jpeg", methods=["GET"])
    @require_auth
    def route_screen_jpeg():
        monitor_index = _request_monitor(0)
        data = _capture_jpeg(monitor_index=monitor_index)
        if data:
            payload = {"data": base64.b64encode(data).decode(), "format": "jpeg"}
            if "monitor" in request.args:
                payload["monitor_index"] = monitor_index
            return jsonify(payload)
        return jsonify({"error": "No screenshot"}), 500

    @app.route("/screen/base64", methods=["GET"])
    @require_auth
    def route_screen_b64():
        monitor_index = _request_monitor(0)
        data = _capture_raw(monitor_index=monitor_index)
        if data:
            payload = {"data": base64.b64encode(data).decode(), "format": "png"}
            if "monitor" in request.args:
                payload["monitor_index"] = monitor_index
            return jsonify(payload)
        return jsonify({"error": "No screenshot"}), 500

    @app.route("/screen/fresh", methods=["GET"])
    @require_auth
    def route_screen_fresh():
        monitor_index = _request_monitor(0)
        data = _capture_jpeg(force=True, monitor_index=monitor_index)
        if data:
            payload = {"data": base64.b64encode(data).decode(), "format": "jpeg", "fresh": True}
            if "monitor" in request.args:
                payload["monitor_index"] = monitor_index
            return jsonify(payload)
        return jsonify({"error": "No screenshot"}), 500

    @app.route("/screen/diag", methods=["GET"])
    @require_auth
    def route_screen_diag():
        sid = 1
        try:
            import os as _os
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", f"(Get-Process -Id {_os.getpid()}).SessionId"],
                               capture_output=True, text=True, timeout=5)
            sid = int(r.stdout.strip()) if r.stdout.strip() else 0
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            _debug_backend_failure("OCR diagnostics session lookup", e)
        monitors = get_monitor_list()
        return jsonify({"dxcam": HAS_DXCAM, "mss": _MSS_AVAILABLE, "pil": HAS_PIL, "session": sid,
                        "host": get_host_ip(), "winrt_runtime": _check_winrt_version(),
                        "monitors": monitors, "monitor_count": len(monitors),
                        "last_capture_method": dict(_LAST_CAPTURE_METHOD)})

    @app.route("/ocr/find", methods=["POST"])
    @require_auth
    def route_ocr_find():
        d = _json_body()
        text = d.get("text", "")
        if not text:
            return _missing_field("text")
        matches = ocr_find_text(text)
        return jsonify({"query": text, "count": len(matches), "matches": matches})

    @app.route("/visual/find", methods=["POST"])
    @require_auth
    def route_visual_find():
        d = _json_body()
        text = d.get("text", "")
        if not text:
            return _missing_field("text")
        matches = ocr_find_text(text)
        return jsonify({"query": text, "count": len(matches), "matches": matches})

    @app.route("/crop", methods=["POST"])
    @require_auth
    def route_crop():
        d = _json_body()
        img = _screen_img(force=True)
        if img is None:
            return jsonify({"error": "Cannot capture screen"}), 500
        region = d.get("region")
        if region:
            if not (isinstance(region, (list, tuple)) and len(region) == 4):
                return jsonify({"error": "region must be [x, y, width, height]"}), 400
            try:
                rx, ry, rw, rh = [max(0, int(v)) for v in region]
            except (ValueError, TypeError):
                return jsonify({"error": "region values must be integers"}), 400
            # Clamp to image bounds
            iw, ih = img.size
            rx, ry = min(rx, iw), min(ry, ih)
            rw, rh = min(rw, iw - rx), min(rh, ih - ry)
            if rw <= 0 or rh <= 0:
                return jsonify({"error": "region has zero area after clamping"}), 400
            img = img.crop((rx, ry, rx + rw, ry + rh))
        import pytesseract, pyperclip
        text = pytesseract.image_to_string(img)
        pyperclip.copy(text.strip())
        return jsonify({"status": "ok", "text": text.strip(), "chars": len(text.strip())})

    @app.route("/describe", methods=["GET"])
    @require_auth
    def route_describe():
        img = _screen_img(force=True)
        if img is None:
            return jsonify({"error": "Cannot capture screen"}), 500
        win_ocr = _windows_ocr(img)
        if win_ocr.get("success"):
            lines = [l.strip() for l in win_ocr["text"].split(" ") if l.strip()]
            return jsonify({"status": "ok", "description": "\n".join(lines[:100]) if lines else "(blank)",
                            "lines": len(lines), "full_text": win_ocr["text"].strip(), "engine": "windows_ocr"})
        try:
            import pytesseract
            text = pytesseract.image_to_string(img)
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            return jsonify({"status": "ok", "description": "\n".join(lines[:100]) if lines else "(blank)",
                            "lines": len(lines), "full_text": text.strip()})
        except ImportError:
            return jsonify({"error": "OCR not available", "description": "OCR not available", "lines": 0}), 200
        except Exception as e:
            return jsonify({"error": str(e), "description": f"OCR failed: {e}", "lines": 0}), 200
