"""Windows Recycle Bin inspection and management routes.

Endpoints:
  GET  /recyclebin/size   -- total item count and byte size of the Recycle Bin
  GET  /recyclebin/list   -- enumerate items (name, original path, date deleted, size)
  POST /recyclebin/empty  -- empty the Recycle Bin (requires confirm=true)

Windows-only. Size/empty use SHELL32 via ctypes; list uses PowerShell's
Shell.Application COM (Namespace 10 == Recycle Bin), because the items and
their "original path" / "date deleted" columns are not exposed through a
plain Win32 call.

No third-party dependencies -- stdlib (ctypes, subprocess, json) + Flask.
"""

import ctypes
import json
import subprocess

from flask import jsonify

from shared import _json_body


# ----- ctypes bindings for SHQueryRecycleBinW / SHEmptyRecycleBinW ----------

class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),      # DWORD
        ("i64Size", ctypes.c_longlong),  # LONGLONG
        ("i64NumItems", ctypes.c_longlong),
    ]


def _shell32():
    """Return SHELL32 with argtypes/restype configured for the two calls we use."""
    shell = ctypes.windll.shell32

    # HRESULT SHQueryRecycleBinW(LPCWSTR pszRootPath, LPSHQUERYRBINFO pSHQueryRBInfo)
    shell.SHQueryRecycleBinW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_SHQUERYRBINFO)]
    shell.SHQueryRecycleBinW.restype = ctypes.c_int  # HRESULT

    # HRESULT SHEmptyRecycleBinW(HWND hwnd, LPCWSTR pszRootPath, DWORD dwFlags)
    shell.SHEmptyRecycleBinW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
    shell.SHEmptyRecycleBinW.restype = ctypes.c_int

    return shell


# ----- PowerShell script for /recyclebin/list -------------------------------

# Pure ASCII. Uses Shell.Application COM to walk the Recycle Bin namespace
# and emits a JSON array to stdout. The single-item case is wrapped
# explicitly because ConvertTo-Json on a 1-length array emits a bare object.
_LIST_PS = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$shell = New-Object -ComObject Shell.Application
$ns = $shell.Namespace(10)
$arr = @()
if ($ns -ne $null) {
  foreach ($item in $ns.Items()) {
    $arr += [PSCustomObject]@{
      name = $item.Name
      original_path = $ns.GetDetailsOf($item, 1)
      date_deleted = $ns.GetDetailsOf($item, 2)
      size = $item.Size
    }
  }
}
if ($arr.Count -eq 0) {
  Write-Output '[]'
} elseif ($arr.Count -eq 1) {
  Write-Output ('[' + (ConvertTo-Json -InputObject $arr[0] -Depth 4 -Compress) + ']')
} else {
  Write-Output (ConvertTo-Json -InputObject $arr -Depth 4 -Compress)
}
'''


def _truthy_confirm(value):
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "confirm", "empty")
    return False


def register_routes(app, state, require_auth):

    @app.route("/recyclebin/size", methods=["GET"])
    @require_auth
    def route_recyclebin_size():
        try:
            info = _SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
            info.i64Size = 0
            info.i64NumItems = 0
            hr = _shell32().SHQueryRecycleBinW(None, ctypes.byref(info))
            if hr != 0:
                return jsonify({
                    "ok": False,
                    "error": "SHQueryRecycleBin failed: HRESULT 0x{0:08X}".format(hr & 0xFFFFFFFF),
                }), 500
            size_bytes = int(info.i64Size)
            return jsonify({
                "ok": True,
                "count": int(info.i64NumItems),
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024.0 * 1024.0), 3),
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/recyclebin/list", methods=["GET"])
    @require_auth
    def route_recyclebin_list():
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", _LIST_PS],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": "powershell exited {0}: {1}".format(
                        result.returncode, (result.stderr or "").strip()
                    ),
                }), 500
            raw = (result.stdout or "").strip().lstrip("\ufeff")
            if not raw:
                return jsonify({"ok": False, "error": "empty powershell output"}), 500
            try:
                items = json.loads(raw)
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": "failed to parse powershell JSON: {0}".format(exc),
                }), 500
            if not isinstance(items, list):
                items = [items]
            return jsonify({"ok": True, "count": len(items), "items": items})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/recyclebin/empty", methods=["POST"])
    @require_auth
    def route_recyclebin_empty():
        try:
            body = _json_body() or {}
            if not _truthy_confirm(body.get("confirm")):
                return jsonify({"ok": False, "error": "confirm field required"}), 400
            hr = _shell32().SHEmptyRecycleBinW(None, None, 0)
            if hr != 0:
                return jsonify({
                    "ok": False,
                    "error": "SHEmptyRecycleBin failed: HRESULT 0x{0:08X}".format(hr & 0xFFFFFFFF),
                }), 500
            return jsonify({"ok": True, "emptied": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
