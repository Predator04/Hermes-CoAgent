"""OCR, screenshot, crop, and screen-describe routes."""
import io, base64, json, os, tempfile, subprocess, time, threading, hashlib
import urllib.error, urllib.request
from io import BytesIO
from pathlib import Path
from flask import Response, jsonify
from shared import _json_body, _log, _console, _missing_field, get_host_ip, COAGENT_DIR, SCREENSHOTS_DIR, TRAY_PORT

# MSS for fast screenshots (DXGI)
_MSS_AVAILABLE = False
_MSS_LOCK = threading.Lock()
try:
    import mss
    _MSS_AVAILABLE = True
except ImportError:
    pass

# Screenshot cache
SCREENSHOT_CACHE_TTL = 2.0
_last_screenshot_time = 0.0
_last_screenshot_raw = b""
_last_screenshot_hash = None
_screenshot_lock = threading.Lock()
# v7.3: Pixel hash — skip capture if screen unchanged
_PIXEL_HASH_CACHE = 0
_PIXEL_HASH_LOCK = threading.Lock()

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

def _grab_screen_mss(force=False):
    """Capture the primary monitor via MSS and return PNG bytes."""
    global _last_screenshot_time, _PIXEL_HASH_CACHE
    if not _MSS_AVAILABLE or not HAS_PIL:
        return b""
    try:
        with _MSS_LOCK:
            with mss.mss() as sct:
                mon = sct.monitors[1]
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
            if not force and hash_val == _PIXEL_HASH_CACHE and _last_screenshot_raw:
                _last_screenshot_time = time.time()
                return _last_screenshot_raw
            _PIXEL_HASH_CACHE = hash_val

        pil_img = Image.frombytes("RGB", size, raw)
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        _log(f"MSS capture failed: {type(e).__name__}: {e}")
        return b""

def _capture_raw(force=False):
    """Capture full screen as PNG bytes. Uses MSS (~5ms) then PIL fallback."""
    global _last_screenshot_time, _last_screenshot_raw, _PIXEL_HASH_CACHE
    now = time.time()
    if not force and (now - _last_screenshot_time) < SCREENSHOT_CACHE_TTL and _last_screenshot_raw:
        return _last_screenshot_raw
    with _screenshot_lock:
        if not force and (now - _last_screenshot_time) < SCREENSHOT_CACHE_TTL and _last_screenshot_raw:
            return _last_screenshot_raw
        # Method 0: MSS / DXGI-style fast capture before PIL ImageGrab fallback.
        img_bytes = _grab_screen_mss(force=force)
        if not img_bytes and HAS_PIL:
            try:
                from PIL import ImageGrab
                pil_img = ImageGrab.grab()
                buf = BytesIO()
                pil_img.save(buf, format="PNG")
                img_bytes = buf.getvalue()
            except:
                pass
        if img_bytes:
            _last_screenshot_time = now
            _last_screenshot_raw = img_bytes
        return img_bytes

def _capture_jpeg(force=False, quality=85):
    """Capture full screen as JPEG bytes."""
    data = _capture_raw(force=force)
    if not data or not HAS_PIL:
        return b""
    try:
        img = Image.open(BytesIO(data))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as e:
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
                headers={"Accept": "image/jpeg"},
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

def _probe_tray_relay(timeout=2.0):
    """Check tray relay health without fetching a full screenshot."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{TRAY_PORT}/health", timeout=timeout) as resp:
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
        return metadata.version("winrt-runtime")
    except Exception:
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
        except:
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
        data, latency_ms, relay_error = _fetch_tray_relay_screen(timeout=2.0)
        if data:
            return Response(data, mimetype="image/jpeg", headers={
                "X-Capture-Method": "tray-relay",
                "X-Relay-Latency-Ms": str(latency_ms),
            })
        _log(f"Tray relay screen unavailable; falling back to local capture: {relay_error}")
        data = _capture_jpeg()
        if data:
            return Response(data, mimetype="image/jpeg", headers={
                "X-Capture-Method": "local",
                "X-Relay-Error": (relay_error or "")[:200],
            })
        return jsonify({"error": "No screenshot"}), 500

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
        data = _capture_jpeg()
        if data:
            return jsonify({"data": base64.b64encode(data).decode(), "format": "jpeg"})
        return jsonify({"error": "No screenshot"}), 500

    @app.route("/screen/base64", methods=["GET"])
    @require_auth
    def route_screen_b64():
        data = _capture_raw()
        if data:
            return jsonify({"data": base64.b64encode(data).decode(), "format": "png"})
        return jsonify({"error": "No screenshot"}), 500

    @app.route("/screen/fresh", methods=["GET"])
    @require_auth
    def route_screen_fresh():
        data = _capture_jpeg(force=True)
        if data:
            return jsonify({"data": base64.b64encode(data).decode(), "format": "jpeg", "fresh": True})
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
        except:
            pass
        return jsonify({"mss": _MSS_AVAILABLE, "pil": HAS_PIL, "session": sid,
                        "host": get_host_ip(), "winrt_runtime": _check_winrt_version()})

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
            img = img.crop((region[0], region[1], region[0]+region[2], region[1]+region[3]))
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
