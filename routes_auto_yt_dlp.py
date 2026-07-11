# Auto-added feature: yt-dlp/yt-dlp (177236 stars)
# Description: A feature-rich command-line audio/video downloader — download videos, audio, playlists, subtitles from YouTube and 1000+ sites
# Source: https://github.com/yt-dlp/yt-dlp

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "yt-dlp/yt-dlp",
    "stars": 177236,
    "desc": "Feature-rich command-line audio/video downloader — download from YouTube and 1000+ sites with format selection, playlist support, subtitles, and metadata embedding",
    "url": "https://github.com/yt-dlp/yt-dlp",
    "added": "2026-07-11",
    "command": "yt-dlp <url> [options]",
}


def _find_yt_dlp():
    """Locate yt-dlp.exe — typically on PATH or in common install locations."""
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if exe:
        return exe
    # Common fallback paths
    for p in [
        os.path.expandvars(r"%LOCALAPPDATA%\yt-dlp\yt-dlp.exe"),
        os.path.expandvars(r"%APPDATA%\yt-dlp\yt-dlp.exe"),
        r"C:\ProgramData\chocolatey\bin\yt-dlp.exe",
        r"C:\Users\Admin\AppData\Local\Microsoft\WindowsApps\yt-dlp.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_yt_dlp_available():
    """Check yt-dlp responds by running a minimal command."""
    exe = _find_yt_dlp()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_url(value):
    """Validate and sanitize a URL for yt-dlp."""
    url = str(value or "").strip()
    if not url:
        raise ValueError("URL must not be empty")
    if len(url) > 4096:
        raise ValueError("URL too long (max 4096 chars)")
    if "\x00" in url:
        raise ValueError("URL cannot contain null bytes")
    # Basic URL validation — must have a scheme
    if not re.match(r'^https?://', url):
        raise ValueError("URL must start with http:// or https://")
    return url


def _clean_format(value):
    """Validate a youtube-dl format string."""
    fmt = str(value or "").strip()
    if fmt and len(fmt) > 200:
        raise ValueError("format string too long (max 200 chars)")
    return fmt or None


def register_routes(app, state, require_auth):
    @app.route("/auto/yt_dlp/info", methods=["GET"])
    @require_auth
    def route_auto_yt_dlp_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/yt_dlp/ping", methods=["GET"])
    @require_auth
    def route_auto_yt_dlp_ping():
        exe = _find_yt_dlp()
        available = _is_yt_dlp_available() if exe else False
        version = None
        if available:
            try:
                result = subprocess.run(
                    [exe, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                version = result.stdout.strip() if result.returncode == 0 else None
            except (subprocess.TimeoutExpired, OSError):
                pass
        return jsonify({
            "status": "ok",
            "feature": "yt-dlp/yt-dlp",
            "available": available,
            "version": version,
            "command": exe or "yt-dlp",
        })

    @app.route("/auto/yt_dlp/info_video", methods=["POST"])
    @require_auth
    def route_auto_yt_dlp_info_video():
        """Get video metadata (title, duration, formats, etc.) without downloading."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        url = body.get("url", "")
        try:
            url = _clean_url(url)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_yt_dlp()
        if not exe:
            return jsonify({"ok": False, "error": "yt-dlp not found"}), 503

        try:
            result = subprocess.run(
                [exe, "--dump-json", "--no-download", url],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "failed to get video info",
                }), 502
            import json as json_mod
            try:
                info = json_mod.loads(result.stdout.strip().split("\n")[0])
            except json_mod.JSONDecodeError:
                return jsonify({
                    "ok": False,
                    "error": "failed to parse video metadata",
                    "raw": result.stdout.strip()[:1000],
                }), 502

            return jsonify({
                "ok": True,
                "url": url,
                "title": info.get("title"),
                "duration": info.get("duration"),
                "duration_str": _format_duration(info.get("duration")),
                "uploader": info.get("uploader"),
                "upload_date": info.get("upload_date"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "description": (info.get("description") or "")[:500],
                "formats_available": len(info.get("formats", [])),
                "extractor": info.get("extractor"),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "yt-dlp timed out fetching video info"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/yt_dlp/list_formats", methods=["POST"])
    @require_auth
    def route_auto_yt_dlp_list_formats():
        """List all available formats for a given URL."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        url = body.get("url", "")
        try:
            url = _clean_url(url)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_yt_dlp()
        if not exe:
            return jsonify({"ok": False, "error": "yt-dlp not found"}), 503

        try:
            result = subprocess.run(
                [exe, "-F", url],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "failed to list formats",
                }), 502
            return jsonify({
                "ok": True,
                "url": url,
                "formats_raw": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "yt-dlp timed out listing formats"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/yt_dlp/download", methods=["POST"])
    @require_auth
    def route_auto_yt_dlp_download():
        """Download a video/audio. Returns command-line output — actual file writes to yt-dlp's configured output dir."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        url = body.get("url", "")
        try:
            url = _clean_url(url)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_yt_dlp()
        if not exe:
            return jsonify({"ok": False, "error": "yt-dlp not found"}), 503

        format_str = _clean_format(body.get("format", ""))
        output_template = body.get("output", "%(title)s.%(ext)s")
        extract_audio = body.get("extract_audio", False)
        playlist_start = body.get("playlist_start")
        playlist_end = body.get("playlist_end")
        write_subs = body.get("write_subs", False)
        sub_langs = body.get("sub_langs", "")

        cmd = [exe]
        if format_str:
            cmd.extend(["-f", format_str])
        elif extract_audio:
            cmd.extend(["-x", "--audio-format", body.get("audio_format", "mp3")])
        cmd.extend(["-o", output_template])
        if write_subs:
            cmd.append("--write-subs")
            if sub_langs:
                cmd.extend(["--sub-langs", sub_langs])
        if playlist_start:
            cmd.extend(["--playlist-start", str(playlist_start)])
        if playlist_end:
            cmd.extend(["--playlist-end", str(playlist_end)])
        cmd.append(url)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "url": url,
                "format": format_str or "best",
                "exit_code": result.returncode,
                "stdout": result.stdout.strip()[-2000:],
                "stderr": result.stderr.strip()[-1000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "yt-dlp download timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/yt_dlp/update", methods=["POST"])
    @require_auth
    def route_auto_yt_dlp_update():
        """Update yt-dlp to the latest version."""
        exe = _find_yt_dlp()
        if not exe:
            return jsonify({"ok": False, "error": "yt-dlp not found"}), 503

        try:
            result = subprocess.run(
                [exe, "-U"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "yt-dlp update timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503


def _format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if seconds is None:
        return None
    try:
        secs = int(seconds)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"
    except (ValueError, TypeError):
        return str(seconds)
