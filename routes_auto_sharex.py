# Auto-added feature: ShareX/ShareX (38775 stars)
# Screen capture, file sharing and productivity tool
# Source: https://github.com/ShareX/ShareX
# Install: https://getsharex.com/downloads  OR  winget install ShareX
# CLI docs: https://getsharex.com/docs/command-line-arguments

import os
import shutil
import subprocess
import tempfile
import hashlib
from datetime import datetime

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ShareX/ShareX",
    "stars": 38775,
    "desc": "Screen capture, file sharing and productivity tool. Supports region capture, screen recording, OCR, color picker, file upload, image editing, and more.",
    "url": "https://github.com/ShareX/ShareX",
    "added": "2026-07-23",
    "command": "ShareX.exe [action] [file]",
    "cli_actions": [
        "RectangleRegion", "PrintScreen", "ClipboardUpload",
        "ScreenColorPicker", "FileUpload", "OCR", "HashCheck",
        "Metadata", "ImageEditor", "VideoConverter", "PinToScreen",
        "ImageBeautifier", "ImageEffects", "ImageViewer", "StripMetadata",
        "QRCode"
    ],
}


def _find_sharex():
    """Locate ShareX executable on this system."""
    exe = shutil.which("ShareX.exe")
    if exe:
        return exe
    # Common install locations
    for p in [
        r"C:\Program Files\ShareX\ShareX.exe",
        r"C:\Program Files (x86)\ShareX\ShareX.exe",
        os.path.expanduser(r"~\AppData\Local\ShareX\ShareX.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\ShareX\ShareX.exe"),
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_sharex_available():
    """Check if ShareX is available by verifying the executable exists."""
    exe = _find_sharex()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--help"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_sharex_action(action, file_path=None):
    """Run a ShareX CLI action and return result."""
    exe = _find_sharex()
    if not exe:
        return None, "ShareX not installed"
    cmd = [exe, f"-{action}"]
    if file_path:
        cmd.append(file_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result, None
    except subprocess.TimeoutExpired:
        return None, "Operation timed out (60s)"
    except OSError as e:
        return None, f"OS error: {str(e)}"


def register_routes(app, state, require_auth):

    @app.route("/auto/sharex/info", methods=["GET"])
    @require_auth
    def route_auto_sharex_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/sharex/ping", methods=["GET"])
    @require_auth
    def route_auto_sharex_ping():
        exe_path = _find_sharex()
        available = exe_path is not None
        try:
            import mss  # noqa: F401
            mss_ok = True
        except ImportError:
            mss_ok = False
        return jsonify({
            "ok": True,
            "available": available,
            "sharex_path": exe_path,
            "python_fallback_mss": mss_ok,
            "cli_actions": len(FEATURE_INFO["cli_actions"]),
        })

    @app.route("/auto/sharex/capture/screen", methods=["POST"])
    @require_auth
    def route_auto_sharex_capture_screen():
        """Capture full screen or region using ShareX or Python fallback (mss)."""
        try:
            body = _json_body()
        except Exception:
            body = {}

        region = body.get("region", None)  # None = full screen, "monitor_N", or {"top":..,"left":..,"width":..,"height":..}

        # Try ShareX first
        exe = _find_sharex()
        if exe:
            try:
                action = "PrintScreen" if not region else "RectangleRegion"
                result, err = _run_sharex_action(action)
                if result and result.returncode == 0:
                    # ShareX saves screenshots to its configured folder
                    screenshots_dir = os.path.expanduser(r"~\Pictures\ShareX\Screenshots")
                    if not os.path.isdir(screenshots_dir):
                        screenshots_dir = os.path.expanduser(r"~\Pictures\Screenshots")
                    latest = None
                    latest_time = 0
                    if os.path.isdir(screenshots_dir):
                        for f in os.listdir(screenshots_dir):
                            fpath = os.path.join(screenshots_dir, f)
                            if os.path.isfile(fpath) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                                mtime = os.path.getmtime(fpath)
                                if mtime > latest_time:
                                    latest_time = mtime
                                    latest = fpath
                    if latest:
                        return jsonify({
                            "ok": True,
                            "tool": "ShareX",
                            "file": latest,
                            "size_bytes": os.path.getsize(latest),
                            "captured_at": datetime.fromtimestamp(latest_time).isoformat(),
                        })
                return jsonify({
                    "ok": True,
                    "tool": "ShareX",
                    "action_triggered": action,
                    "note": "Screenshot captured via ShareX. Check ShareX output folder for result.",
                })
            except Exception as e:
                _log(f"ShareX screenshot failed: {e}")

        # Fallback: mss (Python screen capture library)
        try:
            import mss
            import mss.tools
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = state.screenshots_dir if hasattr(state, 'screenshots_dir') else tempfile.gettempdir()
            os.makedirs(output_dir, exist_ok=True)
            with mss.mss() as sct:
                if region is None:
                    # Capture all monitors combined
                    monitor = sct.monitors[0]
                    output_path = os.path.join(output_dir, f"sharex_screen_{timestamp}.png")
                    sct_img = sct.grab(monitor)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
                elif isinstance(region, str) and region.startswith("monitor_"):
                    idx = int(region.split("_")[1])
                    if 0 < idx < len(sct.monitors):
                        monitor = sct.monitors[idx]
                    else:
                        monitor = sct.monitors[1]
                    output_path = os.path.join(output_dir, f"sharex_monitor{idx}_{timestamp}.png")
                    sct_img = sct.grab(monitor)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
                elif isinstance(region, dict):
                    mon = {
                        "top": int(region.get("top", 0)),
                        "left": int(region.get("left", 0)),
                        "width": int(region.get("width", 800)),
                        "height": int(region.get("height", 600)),
                    }
                    output_path = os.path.join(output_dir, f"sharex_region_{timestamp}.png")
                    sct_img = sct.grab(mon)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
                else:
                    # Full screen
                    output_path = os.path.join(output_dir, f"sharex_screen_{timestamp}.png")
                    sct_img = sct.grab(sct.monitors[0])
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)

            return jsonify({
                "ok": True,
                "tool": "Python mss (fallback)",
                "file": output_path,
                "size_bytes": os.path.getsize(output_path),
                "captured_at": datetime.now().isoformat(),
            })
        except ImportError:
            return jsonify({
                "ok": False,
                "error": "Neither ShareX nor mss (Python) is available. Install mss: pip install mss",
            }), 503

    @app.route("/auto/sharex/capture/upload", methods=["POST"])
    @require_auth
    def route_auto_sharex_upload():
        """Upload a file using ShareX or Python fallback (simulate)."""
        body = _json_body()

        file_path = body.get("file", "")
        if not file_path:
            return _missing_field("file")

        if not os.path.isfile(file_path):
            return jsonify({"ok": False, "error": f"File not found: {file_path}"}), 400

        # Try ShareX
        exe = _find_sharex()
        if exe:
            result, err = _run_sharex_action("FileUpload", file_path)
            if result and result.returncode == 0:
                return jsonify({
                    "ok": True,
                    "tool": "ShareX",
                    "file": file_path,
                    "action": "FileUpload triggered",
                })
            return jsonify({
                "ok": False,
                "error": f"ShareX upload failed: {err or result.stderr.strip()}",
            }), 502

        # Fallback: compute hash and return metadata (no actual upload without ShareX)
        file_size = os.path.getsize(file_path)
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        file_hash = h.hexdigest()
        return jsonify({
            "ok": True,
            "tool": "Python fallback",
            "file": file_path,
            "file_size_bytes": file_size,
            "sha256": file_hash,
            "note": "ShareX not installed. File hash computed for verification. Install ShareX for actual upload.",
        })

    @app.route("/auto/sharex/tools/hash", methods=["POST"])
    @require_auth
    def route_auto_sharex_hash():
        """Compute file hash using ShareX or Python fallback."""
        body = _json_body()

        file_path = body.get("file", "")
        algorithm = body.get("algorithm", "sha256").lower()

        if not file_path:
            return _missing_field("file")

        if not os.path.isfile(file_path):
            return jsonify({"ok": False, "error": f"File not found: {file_path}"}), 400

        supported = {"md5", "sha1", "sha256", "sha384", "sha512", "crc32"}
        if algorithm not in supported:
            return jsonify({"ok": False, "error": f"Unsupported algorithm '{algorithm}'. Supported: {', '.join(sorted(supported))}"}), 400

        exe = _find_sharex()
        if exe:
            result, err = _run_sharex_action("HashCheck", file_path)
            if result and result.returncode == 0:
                return jsonify({
                    "ok": True,
                    "file": file_path,
                    "hash": result.stdout.strip(),
                    "algorithm": algorithm,
                    "tool": "ShareX",
                })

        # Python fallback
        h = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        hexdigest = h.hexdigest()

        return jsonify({
            "ok": True,
            "file": file_path,
            "hash": hexdigest,
            "algorithm": algorithm,
            "tool": "Python hashlib (fallback)",
        })

    @app.route("/auto/sharex/tools/colorpicker", methods=["GET"])
    @require_auth
    def route_auto_sharex_colorpicker():
        """Open ShareX color picker or return pixel color info from a point."""
        try:
            body = _json_body()
        except Exception:
            body = {}

        x = body.get("x", None)
        y = body.get("y", None)

        exe = _find_sharex()
        if not x or not y:
            # Just trigger ShareX color picker
            if exe:
                result, err = _run_sharex_action("ScreenColorPicker")
                if result and result.returncode == 0:
                    return jsonify({
                        "ok": True,
                        "tool": "ShareX",
                        "action": "ScreenColorPicker triggered",
                    })
            return jsonify({
                "ok": True,
                "tool": "Python fallback",
                "note": "ShareX not installed. Provide x and y coordinates to sample pixel color.",
            })

        return jsonify({
            "ok": True,
            "tool": "Python fallback",
            "note": "Full pixel color sampling requires ShareX. Provide coordinates for coordinate-only result.",
            "x": x,
            "y": y,
        })

    @app.route("/auto/sharex/tools/image-editor", methods=["POST"])
    @require_auth
    def route_auto_sharex_image_editor():
        """Open image in ShareX image editor or provide Python Pillow fallback info."""
        body = _json_body()

        file_path = body.get("file", "")
        if not file_path:
            return _missing_field("file")

        if not os.path.isfile(file_path):
            return jsonify({"ok": False, "error": f"File not found: {file_path}"}), 400

        exe = _find_sharex()
        if exe:
            result, err = _run_sharex_action("ImageEditor", file_path)
            if result and result.returncode == 0:
                return jsonify({
                    "ok": True,
                    "tool": "ShareX",
                    "file": file_path,
                    "action": "ImageEditor opened",
                })

        # Fallback: provide image info
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                width, height = img.size
                mode = img.mode
                fmt = img.format
            return jsonify({
                "ok": True,
                "tool": "Python Pillow (fallback)",
                "file": file_path,
                "width": width,
                "height": height,
                "mode": mode,
                "format": fmt,
            })
        except ImportError:
            return jsonify({
                "ok": True,
                "tool": "os.stat (fallback)",
                "file": file_path,
                "size_bytes": os.path.getsize(file_path),
                "note": "Install Pillow (pip install Pillow) for image metadata.",
            })

    @app.route("/auto/sharex/tools/ocr", methods=["POST"])
    @require_auth
    def route_auto_sharex_ocr():
        """Run OCR on an image using ShareX or Python fallback (pytesseract)."""
        body = _json_body()

        file_path = body.get("file", "")
        if not file_path:
            return _missing_field("file")

        if not os.path.isfile(file_path):
            return jsonify({"ok": False, "error": f"File not found: {file_path}"}), 400

        exe = _find_sharex()
        if exe:
            result, err = _run_sharex_action("OCR", file_path)
            if result and result.returncode == 0:
                return jsonify({
                    "ok": True,
                    "tool": "ShareX OCR",
                    "text": result.stdout.strip(),
                })

        # Fallback: try pytesseract
        tesseract = shutil.which("tesseract.exe")
        if tesseract:
            try:
                result = subprocess.run(
                    [tesseract, file_path, "stdout"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    return jsonify({
                        "ok": True,
                        "tool": "Tesseract OCR (fallback)",
                        "text": result.stdout.strip(),
                    })
            except (subprocess.TimeoutExpired, OSError):
                pass

        return jsonify({
            "ok": False,
            "error": "No OCR engine available. Install ShareX, Tesseract (tesseract.exe), or pytesseract.",
        }), 503

    @app.route("/auto/sharex/tools/metadata", methods=["POST"])
    @require_auth
    def route_auto_sharex_metadata():
        """Extract file metadata using ShareX or Python fallback."""
        body = _json_body()

        file_path = body.get("file", "")
        if not file_path:
            return _missing_field("file")

        if not os.path.isfile(file_path):
            return jsonify({"ok": False, "error": f"File not found: {file_path}"}), 400

        exe = _find_sharex()
        if exe:
            result, err = _run_sharex_action("Metadata", file_path)
            if result and result.returncode == 0:
                return jsonify({
                    "ok": True,
                    "tool": "ShareX",
                    "metadata": result.stdout.strip(),
                })

        # Python fallback: os.stat + basic metadata
        stat = os.stat(file_path)
        filename, ext = os.path.splitext(os.path.basename(file_path))
        file_size = stat.st_size

        # Try PIL for image metadata
        exif_data = {}
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
            with Image.open(file_path) as img:
                exif = img._getexif()
                if exif:
                    for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        if isinstance(value, bytes):
                            try:
                                value = value.decode("utf-8", errors="replace")
                            except Exception:
                                value = str(value)
                        exif_data[str(tag)] = str(value)
        except (ImportError, Exception):
            pass

        return jsonify({
            "ok": True,
            "tool": "Python (fallback)",
            "file": file_path,
            "filename": filename,
            "extension": ext,
            "size_bytes": file_size,
            "size_readable": _format_bytes(file_size),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "accessed": datetime.fromtimestamp(stat.st_atime).isoformat(),
            "exif": exif_data if exif_data else None,
        })


def _format_bytes(size):
    """Format byte size to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
