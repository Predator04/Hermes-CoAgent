# Auto-added feature: ImageMagick/ImageMagick (16934 stars)
# Description: ImageMagick is a free, open-source software suite for creating, editing, converting, and displaying images
# Source: https://github.com/ImageMagick/ImageMagick

import os
import re
import shutil
import subprocess

from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ImageMagick/ImageMagick",
    "stars": 16934,
    "desc": "ImageMagick is a free, open-source software suite for creating, editing, converting, and displaying images. Supports 200+ formats via CLI (magick/convert/identify/mogrify/composite)",
    "url": "https://github.com/ImageMagick/ImageMagick",
    "added": "2026-07-12",
    "command": "magick <convert|identify|mogrify|composite|montage|compare>",
}

# Supported ImageMagick subcommands and their purposes
SUBCOMMANDS = [
    "convert",     # Convert between formats, resize, blur, crop, etc.
    "identify",    # Describe image format and characteristics
    "mogrify",     # Transform images in-place
    "composite",   # Overlap one image over another
    "montage",     # Create a composite image from separate images
    "compare",     # Compare two images mathematically/visually
    "conjure",     # Execute a Magick Scripting Language script
    "stream",      # Stream one or more pixel components
    "import",      # Capture screenshot from X server (Linux only)
    "display",     # Display an image on any X server (Linux only)
]

# Utility mapping for common operations
FORMAT_MAP = {
    "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF",
    "bmp": "BMP", "tiff": "TIFF", "tif": "TIFF", "webp": "WEBP",
    "ico": "ICO", "svg": "SVG", "pdf": "PDF", "psd": "PSD",
}


def _find_magick():
    """Locate ImageMagick binaries — magick, convert, identify."""
    candidates = ["magick", "magick.exe", "convert", "convert.exe",
                  "identify", "identify.exe"]
    for name in candidates:
        exe = shutil.which(name)
        if exe:
            return exe
    for p in [
        r"C:\Program Files\ImageMagick-7.1.11-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.1.10-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.1.9-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.10-Q16\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.11-Q16\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.12-Q16\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.13-Q16\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.14-Q16\magick.exe",
        r"C:\Program Files\ImageMagick-6.9.12-Q16\convert.exe",
        r"C:\Program Files\ImageMagick-6.9.11-Q16\convert.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_magick_available():
    exe = _find_magick()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and "ImageMagick" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _get_magick_version():
    """Get ImageMagick version string."""
    exe = _find_magick()
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.split("\n")[0].strip() if result.stdout else None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _safe_path(path):
    """Validate and sanitize a file path."""
    if not path or not isinstance(path, str):
        raise ValueError("path must be a non-empty string")
    if len(path) > 4096:
        raise ValueError("path too long")
    # Block path traversal
    normalized = os.path.normpath(path)
    # Must not contain .. that escapes
    if ".." in normalized.replace("\\", "/").split("/"):
        raise ValueError("path traversal detected")
    return path


def _safe_output_format(fmt):
    """Validate output image format."""
    fm = fmt.strip().lower()
    if fm not in FORMAT_MAP:
        raise ValueError(f"unsupported format '{fmt}'. Supported: {', '.join(sorted(FORMAT_MAP.keys()))}")
    return fm


def _run_magick(args, timeout=30):
    """Run magick with args and return (stdout, stderr, exit_code)."""
    exe = _find_magick()
    if not exe:
        raise RuntimeError("ImageMagick not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def register_routes(app, state, require_auth):
    @app.route("/auto/imagemagick/info", methods=["GET"])
    @require_auth
    def route_auto_imagemagick_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/imagemagick/ping", methods=["GET"])
    @require_auth
    def route_auto_imagemagick_ping():
        exe = _find_magick()
        available = _is_magick_available() if exe else False
        version = _get_magick_version() if available else None
        return jsonify({
            "ok": True,
            "available": available,
            "version": version,
            "exe": exe,
        })

    @app.route("/auto/imagemagick/identify", methods=["POST"])
    @require_auth
    def route_auto_imagemagick_identify():
        """Get detailed image information: format, dimensions, colorspace, size."""
        body = _json_body()
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        path = body.get("path", "")
        if not path:
            return jsonify({"ok": False, "error": _missing_field("path")}), 400

        try:
            safe_path = _safe_path(path)
            if not os.path.isfile(safe_path):
                return jsonify({"ok": False, "error": f"file not found: {path}"}), 404
            stdout, stderr, code = _run_magick(["identify", "-verbose", safe_path], timeout=15)
            if code != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "identify failed"}), 502

            # Parse key details from verbose output
            info = {"path": path, "raw_output": stdout}
            for line in stdout.split("\n"):
                line_s = line.strip()
                if line_s.startswith("Format:"):
                    info["format"] = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Geometry:"):
                    info["geometry"] = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Depth:"):
                    info["depth"] = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Colorspace:"):
                    info["colorspace"] = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Channel statistics:"):
                    pass  # parsing stops here normally

            # Also get simple identify output
            simple, _, _ = _run_magick(["identify", safe_path], timeout=10)
            info["simple"] = simple.strip() if simple else None
            info["ok"] = True
            return jsonify(info)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "identify timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

    @app.route("/auto/imagemagick/convert", methods=["POST"])
    @require_auth
    def route_auto_imagemagick_convert():
        """Convert an image from one format to another with optional resize."""
        body = _json_body()
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        source = body.get("source", "")
        dest = body.get("dest", "")
        options = body.get("options", "")

        if not source or not dest:
            return jsonify({"ok": False, "error": _missing_field("source and dest")}), 400

        try:
            safe_source = _safe_path(source)
            safe_dest = _safe_path(dest)
            if not os.path.isfile(safe_source):
                return jsonify({"ok": False, "error": f"source file not found: {source}"}), 404

            # Validate source is actually an image via identify
            check_out, _, check_code = _run_magick(["identify", safe_source], timeout=10)
            if check_code != 0:
                return jsonify({"ok": False, "error": "source is not a valid image file"}), 400

            args = [safe_source]
            if options:
                # Only allow safe options: -resize, -quality, -strip, -colorspace, -flatten
                safe_ops_re = re.compile(
                    r'^(?:-(?:resize|quality|strip|colorspace|flatten|background|alpha|gravity|extent|crop|rotate|flip|flop|threshold|negate|modulate|blur|sharpen|enhance|normalize|contrast|brightness-contrast|level|gamma|auto-gamma|auto-level|auto-orient)'
                    r'(?:\s+[a-zA-Z0-9_%#x.,+\-]+)*)'
                    r'(?:\s+-(?:resize|quality|strip|colorspace|flatten|background|alpha|gravity|extent|crop|rotate|flip|flop|threshold|negate|modulate|blur|sharpen|enhance|normalize|contrast|brightness-contrast|level|gamma|auto-gamma|auto-level|auto-orient)'
                    r'(?:\s+[a-zA-Z0-9_%#x.,+\-]+)*)*$'
                )
                if not safe_ops_re.match(options.strip()):
                    return jsonify({"ok": False, "error": "options contain unsafe flags"}), 400
                args.extend(options.strip().split())
            args.append(safe_dest)

            stdout, stderr, code = _run_magick(args, timeout=60)
            if code != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "conversion failed"}), 502

            if os.path.isfile(safe_dest):
                size = os.path.getsize(safe_dest)
                return jsonify({
                    "ok": True,
                    "source": source,
                    "dest": dest,
                    "size_bytes": size,
                    "stderr": stderr.strip() if stderr else None,
                })
            else:
                return jsonify({
                    "ok": True,
                    "source": source,
                    "dest": dest,
                    "note": "conversion completed but output file not found — may be a streaming operation",
                    "stderr": stderr.strip() if stderr else None,
                })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "conversion timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

    @app.route("/auto/imagemagick/compare", methods=["POST"])
    @require_auth
    def route_auto_imagemagick_compare():
        """Compare two images and produce a difference metric."""
        body = _json_body()
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        ref = body.get("reference", "")
        test = body.get("test", "")
        metric = body.get("metric", "AE")

        if not ref or not test:
            return jsonify({"ok": False, "error": _missing_field("reference and test")}), 400

        try:
            safe_ref = _safe_path(ref)
            safe_test = _safe_path(test)
            if not os.path.isfile(safe_ref):
                return jsonify({"ok": False, "error": f"reference file not found: {ref}"}), 404
            if not os.path.isfile(safe_test):
                return jsonify({"ok": False, "error": f"test file not found: {test}"}), 404

            # -metric AE gives absolute error count, MAE gives mean error, RMSE etc.
            valid_metrics = ["AE", "MAE", "RMSE", "MSE", "PAE", "PSNR", "SSIM", "PHASH"]
            if metric.upper() not in valid_metrics:
                return jsonify({
                    "ok": False,
                    "error": f"unsupported metric '{metric}'. Valid: {', '.join(valid_metrics)}"
                }), 400

            stdout, stderr, code = _run_magick(
                ["compare", "-metric", metric.upper(), safe_ref, safe_test, "null:"],
                timeout=30
            )
            # ImageMagick outputs the metric value to stderr
            metric_value = stderr.strip() if stderr else stdout.strip()
            return jsonify({
                "ok": True,
                "reference": ref,
                "test": test,
                "metric": metric.upper(),
                "value": metric_value,
                "identical": code == 0,
            })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "compare timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

    @app.route("/auto/imagemagick/resize", methods=["POST"])
    @require_auth
    def route_auto_imagemagick_resize():
        """Resize an image to specified dimensions."""
        body = _json_body()
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        source = body.get("source", "")
        output = body.get("output", "")
        width = body.get("width", "")
        height = body.get("height", "")
        keep_aspect = body.get("keep_aspect", True)

        if not source or not output:
            return jsonify({"ok": False, "error": _missing_field("source and output")}), 400
        if not width and not height:
            return jsonify({"ok": False, "error": _missing_field("width and/or height")}), 400

        try:
            safe_source = _safe_path(source)
            safe_output = _safe_path(output)
            if not os.path.isfile(safe_source):
                return jsonify({"ok": False, "error": f"file not found: {source}"}), 404

            # Build geometry
            w = str(width) if width else ""
            h = str(height) if height else ""
            geom = f"{w}x{h}"
            if keep_aspect:
                geom += ">"  # only shrink, preserve aspect

            args = [safe_source, "-resize", geom, safe_output]
            stdout, stderr, code = _run_magick(args, timeout=60)
            if code != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "resize failed"}), 502

            if os.path.isfile(safe_output):
                new_size = os.path.getsize(safe_output)
                # Get new dimensions
                id_stdout, _, _ = _run_magick(["identify", safe_output], timeout=10)
                return jsonify({
                    "ok": True,
                    "source": source,
                    "output": output,
                    "size_bytes": new_size,
                    "geometry": geom,
                    "identify": id_stdout.strip() if id_stdout else None,
                })
            return jsonify({"ok": True, "source": source, "output": output, "geometry": geom})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "resize timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502
