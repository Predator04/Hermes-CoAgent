"""Desktop icon layout save & restore (issue #1564).

Capture the user's exact desktop icon arrangement (per-icon position plus the
"auto arrange" and "align to grid" state) into a named profile, then put every
icon back in its spot later. Layouts get scrambled by resolution changes,
remote sessions, and monitor hot-plug; this recovers a curated icon grid.

Endpoints:
    POST /desktop/icons/save     - capture current layout as a named profile
    POST /desktop/icons/restore  - put every icon back in its saved spot
    GET  /desktop/icons/list     - enumerate saved profiles
    POST /desktop/icons/delete   - delete a saved profile

Implementation: the desktop is a SysListView32 owned by explorer.exe. Item
positions are read via LVM_GETITEMPOSITION and written via LVM_SETITEMPOSITION
using cross-process memory (VirtualAllocEx/ReadProcessMemory) for the position
and label reads. Auto-arrange / align-to-grid live in the shell bag registry
value FFlags and are captured + restored. Returns HTTP 501 on non-Windows
hosts so the Linux syntax-check CI stays green.

All Win32 handles/counters get explicit argtypes/restype (64-bit safe) and the
entire Windows-specific setup is guarded behind ``os.name == "nt"`` so the
module still imports cleanly on Linux (``ctypes.windll`` is an AttributeError,
not an ImportError, on non-Windows — so it cannot live at module scope).
"""

import ctypes
import json
import os
import threading

from flask import jsonify, request

from shared import COAGENT_DIR, _json_body, _log, _missing_field

# ---------------------------------------------------------------------------
# Win32 function prototypes + LVITEMW struct (64-bit safe, Windows only)
# ---------------------------------------------------------------------------
if os.name == "nt":
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_ssize_t, ctypes.c_ssize_t]

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    kernel32.VirtualFreeEx.restype = wintypes.BOOL
    kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.WriteProcessMemory.restype = wintypes.BOOL
    kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

    shell32.SHChangeNotify.restype = None
    shell32.SHChangeNotify.argtypes = [ctypes.c_long, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]

    class _LVITEMW(ctypes.Structure):
        _fields_ = [
            ("mask", wintypes.UINT),
            ("iItem", ctypes.c_int),
            ("iSubItem", ctypes.c_int),
            ("state", wintypes.UINT),
            ("stateMask", wintypes.UINT),
            ("pszText", ctypes.c_void_p),
            ("cchTextMax", ctypes.c_int),
            ("iImage", ctypes.c_int),
            ("lParam", ctypes.c_ssize_t),
            ("iIndent", ctypes.c_int),
            ("iGroupId", ctypes.c_int),
            ("cColumns", wintypes.UINT),
            ("puColumns", ctypes.c_void_p),
            ("piColFmt", ctypes.c_void_p),
            ("iGroup", ctypes.c_int),
        ]
else:
    wintypes = None
    user32 = kernel32 = shell32 = None
    _LVITEMW = None

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------
LVM_FIRST = 0x1000
LVM_SETITEMPOSITION = LVM_FIRST + 15  # wParam=index, lParam=MAKELONG(x,y)
LVM_GETITEMPOSITION = LVM_FIRST + 16  # wParam=index, lParam=ptr->POINT
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMTEXTW = LVM_FIRST + 115

LVIF_TEXT = 0x0001

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_ACCESS = (
    PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
)
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

# Shell bag FFlags bits (HKCU\...\Shell\Bags\1\Desktop)
FFLAGS_ALIGN_TO_GRID = 0x00000001
FFLAGS_AUTO_ARRANGE = 0x00000002

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

_DESKTOP_ICONS_FILE = COAGENT_DIR / "desktop_icons.json"
_LOCK = threading.Lock()

_MAX_NAME_LEN = 64
_MAX_TEXT_LEN = 260  # UTF-16 code units, generous for a file/icon name


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (desktop icon layout unavailable)"}
    if detail:
        payload["detail"] = str(detail)[:300]
    return jsonify(payload), 501


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _load_profiles():
    if not _DESKTOP_ICONS_FILE.exists():
        return {}
    try:
        data = json.loads(_DESKTOP_ICONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        raise
    return data if isinstance(data, dict) else {}


def _save_profiles(profiles):
    tmp = _DESKTOP_ICONS_FILE.with_suffix(".json.tmp")
    data = json.dumps(profiles, indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, _DESKTOP_ICONS_FILE)


# ---------------------------------------------------------------------------
# Desktop listview discovery
# ---------------------------------------------------------------------------
def _find_desktop_listview():
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return 0
    defview = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
    if not defview:
        # Windows 8+ can host the desktop under a WorkerW window.
        workerw = 0
        while True:
            workerw = user32.FindWindowExW(0, workerw, "WorkerW", None)
            if not workerw:
                break
            defview = user32.FindWindowExW(workerw, 0, "SHELLDLL_DefView", None)
            if defview:
                break
    if not defview:
        return 0
    return user32.FindWindowExW(defview, 0, "SysListView32", None)


def _get_item_position(listview, hproc, index):
    addr = kernel32.VirtualAllocEx(hproc, None, 8, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not addr:
        raise RuntimeError("VirtualAllocEx failed for position buffer")
    try:
        user32.SendMessageW(listview, LVM_GETITEMPOSITION, index, addr)
        pt = wintypes.POINT()
        read = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(hproc, addr, ctypes.byref(pt), 8, ctypes.byref(read)):
            raise RuntimeError("ReadProcessMemory failed for position")
        return pt.x, pt.y
    finally:
        kernel32.VirtualFreeEx(hproc, addr, 0, MEM_RELEASE)


def _get_item_text(listview, hproc, index):
    item = _LVITEMW()
    item.mask = LVIF_TEXT
    item.iItem = index
    item.iSubItem = 0
    item.cchTextMax = _MAX_TEXT_LEN

    text_addr = kernel32.VirtualAllocEx(
        hproc, None, _MAX_TEXT_LEN * 2, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    item_addr = kernel32.VirtualAllocEx(
        hproc, None, ctypes.sizeof(item), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    if not text_addr or not item_addr:
        if text_addr:
            kernel32.VirtualFreeEx(hproc, text_addr, 0, MEM_RELEASE)
        if item_addr:
            kernel32.VirtualFreeEx(hproc, item_addr, 0, MEM_RELEASE)
        raise RuntimeError("VirtualAllocEx failed for item text")
    try:
        item.pszText = text_addr
        written = ctypes.c_size_t()
        kernel32.WriteProcessMemory(
            hproc, item_addr, ctypes.byref(item), ctypes.sizeof(item), ctypes.byref(written)
        )
        user32.SendMessageW(listview, LVM_GETITEMTEXTW, index, item_addr)
        buf = ctypes.create_unicode_buffer(_MAX_TEXT_LEN)
        kernel32.ReadProcessMemory(
            hproc, text_addr, buf, _MAX_TEXT_LEN * 2, ctypes.byref(written)
        )
        return buf.value
    finally:
        kernel32.VirtualFreeEx(hproc, text_addr, 0, MEM_RELEASE)
        kernel32.VirtualFreeEx(hproc, item_addr, 0, MEM_RELEASE)


def _capture_icons():
    """Return (icons, fflags) for the live desktop, or raise RuntimeError."""
    listview = _find_desktop_listview()
    if not listview:
        raise RuntimeError("desktop icon listview not found")
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(listview, ctypes.byref(pid))
    hproc = kernel32.OpenProcess(PROCESS_ACCESS, False, pid.value)
    if not hproc:
        raise RuntimeError("cannot open explorer.exe process (access denied)")
    try:
        count = user32.SendMessageW(listview, LVM_GETITEMCOUNT, 0, 0)
        if count < 0 or count > 100000:
            raise RuntimeError("unexpected icon count")
        icons = []
        for index in range(count):
            x, y = _get_item_position(listview, hproc, index)
            try:
                name = _get_item_text(listview, hproc, index)
            except Exception:
                name = ""
            icons.append({"index": index, "name": name, "x": x, "y": y})
        return icons, _read_fflags()
    finally:
        kernel32.CloseHandle(hproc)


# ---------------------------------------------------------------------------
# Auto-arrange / align-to-grid (shell bag FFlags)
# ---------------------------------------------------------------------------
def _read_fflags():
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Bags\1\Desktop",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "FFlags")
            return int(value)
    except Exception:
        return 0


def _write_fflags(value):
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Bags\1\Desktop",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "FFlags", 0, winreg.REG_DWORD, int(value) & 0xFFFFFFFF)
            return True
    except Exception as exc:  # noqa: BLE001
        _log(f"desktop_icons: failed to write FFlags: {exc}")
        return False


def _refresh_desktop():
    try:
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception as exc:  # noqa: BLE001
        _log(f"desktop_icons: SHChangeNotify failed: {exc}")


def _restore_icons(profile):
    """Apply a saved profile. Returns count of icons restored."""
    listview = _find_desktop_listview()
    if not listview:
        raise RuntimeError("desktop icon listview not found")

    saved_icons = profile.get("icons", [])
    saved_fflags = profile.get("fflags", 0)

    # Snapshot current icon names for name-based matching.
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(listview, ctypes.byref(pid))
    hproc = kernel32.OpenProcess(PROCESS_ACCESS, False, pid.value)
    if not hproc:
        raise RuntimeError("cannot open explorer.exe process (access denied)")

    count = user32.SendMessageW(listview, LVM_GETITEMCOUNT, 0, 0)
    try:
        current_names = {}
        for index in range(count):
            try:
                current_names[index] = _get_item_text(listview, hproc, index)
            except Exception:
                current_names[index] = ""
    finally:
        kernel32.CloseHandle(hproc)

    name_to_index = {}
    for index, name in current_names.items():
        if name:
            name_to_index.setdefault(name, index)

    # Temporarily disable auto-arrange so explicit positions stick.
    _write_fflags(saved_fflags & ~(FFLAGS_AUTO_ARRANGE | FFLAGS_ALIGN_TO_GRID))

    restored = 0
    for icon in saved_icons:
        name = icon.get("name", "")
        saved_index = icon.get("index", 0)
        target = name_to_index.get(name) if name else None
        if target is None:
            target = saved_index
        if target >= count:
            continue
        x = int(icon.get("x", 0))
        y = int(icon.get("y", 0))
        # lParam = MAKELONG(x, y) = (y << 16) | (x & 0xFFFF)
        lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        user32.SendMessageW(listview, LVM_SETITEMPOSITION, target, lparam)
        restored += 1

    # Restore the original auto-arrange / align-to-grid state.
    _write_fflags(saved_fflags)
    _refresh_desktop()
    return restored


def _valid_name(name):
    return isinstance(name, str) and 0 < len(name) <= _MAX_NAME_LEN


def _now_iso():
    from datetime import datetime
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def register_routes(app, state=None, require_auth=None):
    def _name_from(payload):
        return (payload.get("name") or "").strip() if isinstance(payload, dict) else ""

    @app.route("/desktop/icons/save", methods=["POST"])
    def desktop_icons_save():
        if os.name != "nt":
            return _windows_only("not Windows")
        payload = _json_body()
        name = _name_from(payload)
        if not _valid_name(name):
            return _missing_field("name")
        try:
            icons, fflags = _capture_icons()
        except Exception as exc:  # noqa: BLE001
            _log(f"desktop_icons: save failed: {exc}")
            return jsonify({"error": "Failed to capture desktop icons", "detail": str(exc)}), 500

        with _LOCK:
            profiles = _load_profiles()
            profiles[name] = {
                "icons": icons,
                "fflags": fflags,
                "count": len(icons),
                "captured_at": _now_iso(),
            }
            _save_profiles(profiles)

        return jsonify({
            "ok": True,
            "name": name,
            "count": len(icons),
            "fflags": fflags,
            "auto_arrange": bool(fflags & FFLAGS_AUTO_ARRANGE),
            "align_to_grid": bool(fflags & FFLAGS_ALIGN_TO_GRID),
        })

    @app.route("/desktop/icons/restore", methods=["POST"])
    def desktop_icons_restore():
        if os.name != "nt":
            return _windows_only("not Windows")
        payload = _json_body()
        name = _name_from(payload)
        if not _valid_name(name):
            return _missing_field("name")

        with _LOCK:
            profiles = _load_profiles()
            profile = profiles.get(name)

        if not profile:
            return jsonify({"error": f"No saved profile named '{name}'"}), 404

        try:
            restored = _restore_icons(profile)
        except Exception as exc:  # noqa: BLE001
            _log(f"desktop_icons: restore failed: {exc}")
            return jsonify({"error": "Failed to restore desktop icons", "detail": str(exc)}), 500

        return jsonify({"ok": True, "name": name, "restored": restored})

    @app.route("/desktop/icons/list", methods=["GET"])
    def desktop_icons_list():
        with _LOCK:
            profiles = _load_profiles()
        items = [
            {
                "name": name,
                "count": prof.get("count", len(prof.get("icons", []))),
                "captured_at": prof.get("captured_at"),
            }
            for name, prof in profiles.items()
        ]
        return jsonify({"profiles": items})

    @app.route("/desktop/icons/delete", methods=["POST"])
    def desktop_icons_delete():
        payload = _json_body()
        name = _name_from(payload)
        if not _valid_name(name):
            return _missing_field("name")
        with _LOCK:
            profiles = _load_profiles()
            if name not in profiles:
                return jsonify({"error": f"No saved profile named '{name}'"}), 404
            del profiles[name]
            _save_profiles(profiles)
        return jsonify({"ok": True, "deleted": name})
