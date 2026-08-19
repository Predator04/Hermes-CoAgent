"""Self-diagnostics routes — health-check every CoAgent subsystem."""
import os
import shutil
import subprocess
import sys
import threading
import time

from flask import jsonify
from shared import AGENT_NAME, VERSION, _log

_STATE_REF = None


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_screen_capture():
    backends = {}
    try:
        from routes_ocr import HAS_DXCAM, HAS_PIL, _MSS_AVAILABLE
        backends = {"dxcam": HAS_DXCAM, "mss": _MSS_AVAILABLE, "pil": HAS_PIL}
    except Exception as exc:
        return {"status": "error", "detail": f"routes_ocr import: {exc}", "backends": backends}

    if not any(backends.values()):
        return {"status": "error", "backends": backends,
                "fix": "pip install mss Pillow"}

    try:
        from routes_ocr import _capture_jpeg
        data = _capture_jpeg(force=True, quality=60)
        if data and len(data) > 500:
            return {"status": "ok", "backends": backends, "capture_bytes": len(data)}
        return {"status": "warning", "backends": backends,
                "detail": "Capture returned empty or tiny frame"}
    except Exception as exc:
        return {"status": "error", "backends": backends, "detail": str(exc),
                "fix": "Ensure a display is attached and the process has desktop access"}


def _check_ocr():
    try:
        import pytesseract
    except ImportError:
        return {"status": "warning", "pytesseract": False,
                "fix": "pip install pytesseract  (also install Tesseract-OCR binary)"}

    path = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
        raw = (r.stdout or r.stderr).strip()
        version = raw.splitlines()[0] if raw else "unknown"
        return {"status": "ok", "path": path, "version": version}
    except FileNotFoundError:
        return {"status": "error", "path": path,
                "fix": "Install Tesseract-OCR and set pytesseract.pytesseract.tesseract_cmd"}
    except Exception as exc:
        return {"status": "error", "path": path, "detail": str(exc)}


def _check_uia():
    try:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        uia = comtypes.client.CreateObject(
            "{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
            interface=comtypes.IUnknown,
        )
        del uia
        return {"status": "ok", "backend": "comtypes", "detail": "UIA COM initialized"}
    except Exception as exc_com:
        try:
            import pywinauto
            d = pywinauto.Desktop(backend="uia")
            count = len(d.windows())
            return {"status": "ok", "backend": "pywinauto",
                    "detail": f"UIA via pywinauto ({count} desktop windows)"}
        except Exception as exc_pw:
            return {
                "status": "warning",
                "detail": f"comtypes: {exc_com}; pywinauto: {exc_pw}",
                "fix": "pip install comtypes pywinauto",
            }


def _check_mouse_keyboard():
    has_pa, has_si = False, False
    pa_version = None
    try:
        import pyautogui
        pyautogui.size()
        has_pa = True
        pa_version = getattr(pyautogui, "__version__", "installed")
    except Exception:
        pass
    try:
        import ctypes
        if hasattr(ctypes, "windll"):
            ctypes.windll.user32.GetSystemMetrics(0)
            has_si = True
    except Exception:
        pass
    status = "ok" if (has_pa or has_si) else "error"
    return {
        "status": status,
        "pyautogui": has_pa,
        "pyautogui_version": pa_version,
        "sendinput": has_si,
        "fix": "pip install pyautogui" if not has_pa else None,
    }


def _check_browser():
    try:
        import playwright as _pw_mod
        pl_version = getattr(_pw_mod, "__version__", "installed")
    except ImportError:
        return {
            "status": "warning",
            "playwright": False,
            "fix": "pip install playwright && python -m playwright install chromium",
        }

    try:
        from playwright.sync_api import sync_playwright
        chromium_path = None
        chromium_ok = False
        with sync_playwright() as pw:
            chromium_path = pw.chromium.executable_path
            chromium_ok = os.path.exists(chromium_path)
        return {
            "status": "ok" if chromium_ok else "warning",
            "playwright": pl_version,
            "chromium": chromium_ok,
            "chromium_path": chromium_path,
            "fix": None if chromium_ok else "python -m playwright install chromium",
        }
    except Exception as exc:
        return {"status": "warning", "playwright": pl_version, "detail": str(exc)}


def _check_audio():
    try:
        import winsound
        return {"status": "ok", "backend": "winsound"}
    except ImportError:
        pass
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        return {"status": "ok", "backend": "sounddevice", "device_count": len(devs)}
    except Exception:
        pass
    return {
        "status": "warning",
        "detail": "No audio backend available",
        "fix": "Ensure Windows audio service is running",
    }


def _check_network():
    import socket
    try:
        t0 = time.time()
        sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
        sock.close()
        latency_ms = round((time.time() - t0) * 1000, 1)
        return {"status": "ok", "host": "8.8.8.8:53", "latency_ms": latency_ms}
    except Exception as exc:
        return {
            "status": "warning",
            "detail": str(exc),
            "fix": "Check network connectivity and firewall rules",
        }


def _check_disk():
    try:
        drive = "C:\\" if sys.platform == "win32" else "/"
        stat = shutil.disk_usage(drive)
        free_gb = round(stat.free / (1024 ** 3), 2)
        total_gb = round(stat.total / (1024 ** 3), 2)
        used_pct = round((stat.used / stat.total) * 100, 1)
        if free_gb > 5:
            status = "ok"
        elif free_gb > 1:
            status = "warning"
        else:
            status = "error"
        result = {
            "status": status,
            "drive": drive,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "used_pct": used_pct,
        }
        if status != "ok":
            result["fix"] = f"Free up space on {drive} (only {free_gb} GB remaining)"
        return result
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_python():
    version = sys.version.split()[0]
    pkg_list = [
        "flask", "waitress", "requests", "anthropic",
        "mss", "dxcam", "playwright", "pytesseract",
        "psutil", "pyautogui", "comtypes", "win32api",
        "pywinauto", "pygetwindow", "pynput", "keyboard",
    ]
    packages = {}
    for pkg in pkg_list:
        try:
            mod = __import__(pkg.replace("-", "_"))
            packages[pkg] = getattr(mod, "__version__", "installed")
        except ImportError:
            packages[pkg] = None
    missing = [k for k, v in packages.items() if v is None]
    critical_missing = [k for k in missing if k in ("flask", "requests", "mss")]
    status = "error" if critical_missing else ("warning" if missing else "ok")
    return {
        "status": status,
        "python_version": version,
        "packages": packages,
        "missing": missing,
    }


def _check_coagent():
    uptime = None  # None means unknown/unavailable
    mem_mb = None
    cpu_pct = None
    if _STATE_REF:
        uptime = int(time.time() - getattr(_STATE_REF, "start_time", time.time()))
    try:
        import psutil
        proc = psutil.Process()
        mem_mb = round(proc.memory_info().rss / (1024 ** 2), 1)
        cpu_pct = round(proc.cpu_percent(interval=0.1), 1)
    except Exception:
        pass
    return {
        "status": "ok",
        "version": VERSION,
        "agent": AGENT_NAME,
        "uptime_s": uptime,
        "memory_mb": mem_mb,
        "cpu_pct": cpu_pct,
        "pid": os.getpid(),
    }


_CHECKS = [
    ("screen_capture", _check_screen_capture),
    ("ocr", _check_ocr),
    ("uia", _check_uia),
    ("mouse_keyboard", _check_mouse_keyboard),
    ("browser", _check_browser),
    ("audio", _check_audio),
    ("network", _check_network),
    ("disk", _check_disk),
    ("python", _check_python),
    ("coagent", _check_coagent),
]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):
    global _STATE_REF
    _STATE_REF = state

    @app.route("/diagnostics", methods=["GET"])
    @require_auth
    def route_diagnostics():
        """Run all subsystem health checks and return a unified report.

        Returns JSON: {status: ok|warning|error, elapsed_ms, checks: {...}}
        Each check has {status, detail?, fix?, ...subsystem fields}.
        """
        t0 = time.time()
        results = {}
        lock = threading.Lock()

        def _run(label, fn):
            try:
                r = fn()
            except Exception as exc:
                r = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
            with lock:
                results[label] = r

        threads = [
            threading.Thread(target=_run, args=(lbl, fn), daemon=True)
            for lbl, fn in _CHECKS
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=12)

        # Snapshot under lock so late-completing threads can't race our iteration
        with lock:
            snapshot = dict(results)

        # Backfill any checks that timed out
        for lbl, _ in _CHECKS:
            if lbl not in snapshot:
                snapshot[lbl] = {"status": "error", "detail": "Check timed out after 12 s"}

        statuses = {v.get("status", "unknown") for v in snapshot.values()}
        overall = (
            "error" if "error" in statuses
            else "warning" if "warning" in statuses
            else "ok"
        )

        _log(f"Diagnostics: {overall} in {round((time.time()-t0)*1000)}ms")
        return jsonify({
            "status": overall,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "checks": snapshot,
        })
