"""Per-application audio mixer routes.

Endpoints:
  GET/POST /audio_mixer/sessions - list audio sessions with per-app volume/mute
  POST     /audio_mixer/set      - set volume and/or mute for a matching session

Backend priority:
  1. pycaw + comtypes (full per-session control)
  2. PowerShell + CoreAudio COM via Add-Type (fallback with same coverage)

On non-Windows hosts the endpoints return HTTP 501 rather than failing at
import time, so the Linux syntax-check CI stays green.
"""

import json as _json
import os
import re
import shutil
import subprocess

from flask import jsonify

from shared import _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Match a Windows process name (e.g. "chrome.exe"). Kept tight to avoid
# any risk of injection into the PowerShell fallback script below.
_PROCESS_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-+ ()]{1,128}$")

# Optional pycaw import. Windows-only; wrapped in try/except so Linux CI
# syntax-check passes without the dependency installed.
_HAVE_PYCAW = False
try:
    if os.name == "nt":
        from pycaw.pycaw import AudioUtilities  # type: ignore  # noqa: F401
        _HAVE_PYCAW = True
except Exception:
    _HAVE_PYCAW = False


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_powershell():
    return (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _run_ps(script, timeout=25):
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return "", "powershell.exe not found", -1
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _parse_json_output(text):
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = _json.loads(text)
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _clamp_volume(raw):
    """Coerce a JSON-supplied volume to a float in [0.0, 1.0], or None."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val < 0.0:
        val = 0.0
    if val > 1.0:
        val = 1.0
    return val


def _coerce_bool(raw):
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
    return None


def _session_matches(match_pid, match_name, pid, name):
    if match_pid is not None:
        try:
            if int(pid) == int(match_pid):
                return True
        except (TypeError, ValueError):
            pass
    if match_name:
        target = match_name.lower()
        pname = (name or "").lower()
        # Match both "chrome" and "chrome.exe" against a "chrome.exe" session.
        if pname and (pname == target or pname == target + ".exe" or pname.rsplit(".", 1)[0] == target):
            return True
    return False


# ---------------------------------------------------------------------------
# pycaw backend
# ---------------------------------------------------------------------------

def _pycaw_list():
    from pycaw.pycaw import AudioUtilities  # type: ignore
    out = []
    for s in AudioUtilities.GetAllSessions():
        proc = s.Process
        pid = None
        pname = ""
        if proc is not None:
            try:
                pid = proc.pid
            except Exception:
                pid = None
            try:
                pname = proc.name()
            except Exception:
                pname = ""
        volume = None
        mute = None
        vol = s.SimpleAudioVolume
        if vol is not None:
            try:
                volume = float(vol.GetMasterVolume())
            except Exception:
                volume = None
            try:
                mute = bool(vol.GetMute())
            except Exception:
                mute = None
        out.append({
            "pid": pid,
            "process": pname,
            "display_name": s.DisplayName or "",
            "volume": volume,
            "mute": mute,
        })
    return out


def _pycaw_set(match_pid, match_name, volume, mute):
    from pycaw.pycaw import AudioUtilities  # type: ignore
    matched = []
    for s in AudioUtilities.GetAllSessions():
        proc = s.Process
        pid = None
        pname = ""
        if proc is not None:
            try:
                pid = proc.pid
            except Exception:
                pid = None
            try:
                pname = proc.name()
            except Exception:
                pname = ""
        if not _session_matches(match_pid, match_name, pid, pname):
            continue
        vol = s.SimpleAudioVolume
        if vol is None:
            continue
        applied = {"pid": pid, "process": pname}
        if volume is not None:
            try:
                vol.SetMasterVolume(float(volume), None)
                applied["volume"] = float(volume)
            except Exception as exc:
                applied["volume_error"] = str(exc)
        if mute is not None:
            try:
                vol.SetMute(1 if mute else 0, None)
                applied["mute"] = bool(mute)
            except Exception as exc:
                applied["mute_error"] = str(exc)
        matched.append(applied)
    return matched


# ---------------------------------------------------------------------------
# PowerShell + CoreAudio fallback
# ---------------------------------------------------------------------------
#
# All literals below are pure ASCII. The C# blob is passed as a here-string
# to Add-Type at runtime; we never interpolate user input into the script.
# Per-session control uses ISimpleAudioVolume which is the same interface
# pycaw wraps, so behavior matches the primary backend.
_CS_CORE_AUDIO = r"""
using System;
using System.Runtime.InteropServices;

namespace CoAgentAudio {
  public enum EDataFlow { eRender, eCapture, eAll }
  public enum ERole { eConsole, eMultimedia, eCommunications }

  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
  public class MMDeviceEnumerator { }

  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IMMDeviceEnumerator {
    int NotImpl_0();
    [PreserveSig] int GetDefaultAudioEndpoint(EDataFlow dataFlow, ERole role, out IMMDevice endpoint);
  }

  [Guid("D666063F-1587-4E43-81F1-B948E807363F"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams,
        [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
  }

  [Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IAudioSessionManager2 {
    int NotImpl_0();
    int NotImpl_1();
    [PreserveSig] int GetSessionEnumerator(out IAudioSessionEnumerator SessionEnum);
  }

  [Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IAudioSessionEnumerator {
    [PreserveSig] int GetCount(out int SessionCount);
    [PreserveSig] int GetSession(int SessionCount, out IAudioSessionControl2 Session);
  }

  [Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IAudioSessionControl2 {
    // IAudioSessionControl (8 methods)
    int NotImpl_0(); int NotImpl_1(); int NotImpl_2(); int NotImpl_3();
    int NotImpl_4(); int NotImpl_5(); int NotImpl_6(); int NotImpl_7();
    // IAudioSessionControl2
    [PreserveSig] int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string pRetVal);
    [PreserveSig] int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string pRetVal);
    [PreserveSig] int GetProcessId(out uint pRetVal);
    [PreserveSig] int IsSystemSoundsSession();
    int NotImpl_12();
  }

  [Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface ISimpleAudioVolume {
    [PreserveSig] int SetMasterVolume(float fLevel, ref Guid EventContext);
    [PreserveSig] int GetMasterVolume(out float pfLevel);
    [PreserveSig] int SetMute(bool bMute, ref Guid EventContext);
    [PreserveSig] int GetMute(out bool pbMute);
  }

  public static class Mixer {
    static readonly Guid IID_IAudioSessionManager2 = new Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F");
    static readonly Guid IID_ISimpleAudioVolume    = new Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8");
    const int CLSCTX_ALL = 23;

    static IAudioSessionEnumerator OpenEnumerator() {
      var e = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
      IMMDevice dev; e.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eMultimedia, out dev);
      Guid iid = IID_IAudioSessionManager2; object o;
      dev.Activate(ref iid, CLSCTX_ALL, IntPtr.Zero, out o);
      var mgr = (IAudioSessionManager2)o;
      IAudioSessionEnumerator en; mgr.GetSessionEnumerator(out en);
      return en;
    }

    public class Entry {
      public uint Pid; public string SessionId; public bool IsSystem;
      public float Volume; public bool Mute;
    }

    public static System.Collections.Generic.List<Entry> List() {
      var results = new System.Collections.Generic.List<Entry>();
      var en = OpenEnumerator();
      int n; en.GetCount(out n);
      for (int i = 0; i < n; i++) {
        IAudioSessionControl2 ctl; en.GetSession(i, out ctl);
        uint pid = 0; ctl.GetProcessId(out pid);
        string sid = null; ctl.GetSessionIdentifier(out sid);
        int sys = ctl.IsSystemSoundsSession();
        var vol = (ISimpleAudioVolume)ctl;
        float lvl = 0; vol.GetMasterVolume(out lvl);
        bool mute = false; vol.GetMute(out mute);
        results.Add(new Entry {
          Pid = pid, SessionId = sid ?? "", IsSystem = (sys == 0),
          Volume = lvl, Mute = mute
        });
      }
      return results;
    }

    // Apply level/mute to every session whose PID matches. Returns count.
    public static int Apply(uint pid, bool setVol, float level, bool setMute, bool mute) {
      int applied = 0;
      var en = OpenEnumerator();
      int n; en.GetCount(out n);
      Guid ctx = Guid.Empty;
      for (int i = 0; i < n; i++) {
        IAudioSessionControl2 ctl; en.GetSession(i, out ctl);
        uint p = 0; ctl.GetProcessId(out p);
        if (p != pid) continue;
        var vol = (ISimpleAudioVolume)ctl;
        if (setVol)  vol.SetMasterVolume(level, ref ctx);
        if (setMute) vol.SetMute(mute, ref ctx);
        applied++;
      }
      return applied;
    }
  }
}
"@
"""


def _ps_list_script():
    # Uses Get-Process to translate PIDs into names for the caller.
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$src = @\"" + _CS_CORE_AUDIO + "; "
        "Add-Type -TypeDefinition $src -Language CSharp | Out-Null; "
        "$entries = [CoAgentAudio.Mixer]::List(); "
        "$out = foreach ($e in $entries) { "
        "  $name = ''; "
        "  if ($e.Pid -gt 0) { "
        "    try { $name = (Get-Process -Id $e.Pid -ErrorAction Stop).ProcessName } catch { $name = '' } "
        "  } "
        "  [pscustomobject]@{ "
        "    pid = [int]$e.Pid; process = $name; display_name = $e.SessionId; "
        "    volume = [double]$e.Volume; mute = [bool]$e.Mute; "
        "    is_system = [bool]$e.IsSystem "
        "  } "
        "}; "
        "ConvertTo-Json -InputObject @($out) -Depth 3 -Compress"
    )


def _ps_apply_script(pid_value, set_vol, level, set_mute, mute):
    # pid_value is guaranteed int (validated in caller). level is 0..1 float.
    lvl_lit = "{:.6f}".format(float(level) if level is not None else 0.0)
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$src = @\"" + _CS_CORE_AUDIO + "; "
        "Add-Type -TypeDefinition $src -Language CSharp | Out-Null; "
        "$n = [CoAgentAudio.Mixer]::Apply("
        f"[uint32]{int(pid_value)}, "
        f"${'true' if set_vol else 'false'}, "
        f"[float]{lvl_lit}, "
        f"${'true' if set_mute else 'false'}, "
        f"${'true' if bool(mute) else 'false'}"
        "); "
        "[pscustomobject]@{ applied = [int]$n } | ConvertTo-Json -Compress"
    )


def _ps_list():
    out, err, rc = _run_ps(_ps_list_script(), timeout=25)
    if rc != 0:
        return None, err.strip() or f"CoreAudio enumeration failed (rc={rc})"
    return _parse_json_output(out), None


def _ps_resolve_pids(match_name):
    """Return list of PIDs for a process name via Get-Process."""
    if not match_name or not _PROCESS_NAME_RE.fullmatch(match_name):
        return [], "invalid process name"
    base = match_name
    if base.lower().endswith(".exe"):
        base = base[:-4]
    # ASCII-only single-quoted arg; regex above already banned quotes and
    # anything that could break out of the string literal below.
    script = (
        "Get-Process -Name '" + base + "' -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Id | ConvertTo-Json -Compress"
    )
    out, err, rc = _run_ps(script, timeout=15)
    if rc != 0:
        return [], err.strip() or "Get-Process failed"
    raw = (out or "").strip()
    if not raw:
        return [], None
    try:
        data = _json.loads(raw)
    except ValueError:
        return [], "bad Get-Process output"
    if isinstance(data, int):
        return [data], None
    if isinstance(data, list):
        return [int(x) for x in data if isinstance(x, int)], None
    return [], None


def _ps_apply(pids, volume, mute):
    applied = []
    set_vol = volume is not None
    set_mute = mute is not None
    for pid in pids:
        out, err, rc = _run_ps(
            _ps_apply_script(pid, set_vol, volume, set_mute, mute),
            timeout=20,
        )
        if rc != 0:
            applied.append({"pid": pid, "error": err.strip() or f"rc={rc}"})
            continue
        entry = {"pid": pid}
        try:
            data = _json.loads(out.strip()) if out.strip() else {}
        except ValueError:
            data = {}
        if isinstance(data, dict) and "applied" in data:
            entry["session_count"] = int(data["applied"])
        if set_vol:
            entry["volume"] = float(volume)
        if set_mute:
            entry["mute"] = bool(mute)
        applied.append(entry)
    return applied


def register_routes(app, state, require_auth):
    ps_exe = _find_powershell()
    ps_available = bool(ps_exe and os.path.isfile(ps_exe))
    backend = "pycaw" if _HAVE_PYCAW else ("powershell" if ps_available else "none")

    @app.route("/audio_mixer/sessions", methods=["GET", "POST"])
    @require_auth
    def route_audio_mixer_sessions():
        if os.name != "nt":
            return _windows_only()
        if _HAVE_PYCAW:
            try:
                sessions = _pycaw_list()
            except Exception as exc:
                _log(f"audio_mixer/sessions pycaw error: {exc}")
                return jsonify({"error": str(exc), "backend": "pycaw"}), 500
            return jsonify({
                "backend": "pycaw",
                "sessions": sessions,
                "count": len(sessions),
            })
        if not ps_available:
            return jsonify({
                "error": "no audio backend available (install pycaw or PowerShell)",
            }), 501
        sessions, err = _ps_list()
        if err:
            return jsonify({"error": err, "backend": "powershell"}), 500
        return jsonify({
            "backend": "powershell",
            "sessions": sessions or [],
            "count": len(sessions or []),
        })

    @app.route("/audio_mixer/set", methods=["POST"])
    @require_auth
    def route_audio_mixer_set():
        if os.name != "nt":
            return _windows_only()
        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        match_pid_raw = body.get("pid")
        match_name_raw = body.get("process") or body.get("name")
        volume = _clamp_volume(body.get("volume"))
        mute = _coerce_bool(body.get("mute"))

        if volume is None and mute is None:
            return jsonify({"error": "provide 'volume' and/or 'mute'"}), 400
        if match_pid_raw is None and not match_name_raw:
            return _missing_field("pid or process")

        match_pid = None
        if match_pid_raw is not None:
            try:
                match_pid = int(match_pid_raw)
                if match_pid < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": "invalid pid"}), 400

        match_name = None
        if match_name_raw:
            if not isinstance(match_name_raw, str) or not _PROCESS_NAME_RE.fullmatch(match_name_raw):
                return jsonify({"error": "invalid process name"}), 400
            match_name = match_name_raw

        if _HAVE_PYCAW:
            try:
                matched = _pycaw_set(match_pid, match_name, volume, mute)
            except Exception as exc:
                _log(f"audio_mixer/set pycaw error: {exc}")
                return jsonify({"error": str(exc), "backend": "pycaw"}), 500
            _log(f"audio_mixer/set backend=pycaw matched={len(matched)}")
            status = "ok" if matched else "no_match"
            code = 200 if matched else 404
            return jsonify({
                "backend": "pycaw",
                "status": status,
                "matched": matched,
                "count": len(matched),
            }), code

        if not ps_available:
            return jsonify({
                "error": "no audio backend available (install pycaw or PowerShell)",
            }), 501

        pids = []
        if match_pid is not None:
            pids.append(match_pid)
        if match_name and not pids:
            resolved, err = _ps_resolve_pids(match_name)
            if err:
                return jsonify({"error": err, "backend": "powershell"}), 500
            pids.extend(resolved)
        if not pids:
            return jsonify({
                "backend": "powershell",
                "status": "no_match",
                "matched": [],
                "count": 0,
            }), 404

        matched = _ps_apply(pids, volume, mute)
        touched = sum(1 for m in matched if m.get("session_count", 0) > 0)
        _log(f"audio_mixer/set backend=powershell pids={pids} touched={touched}")
        status = "ok" if touched else "no_match"
        code = 200 if touched else 404
        return jsonify({
            "backend": "powershell",
            "status": status,
            "matched": matched,
            "count": touched,
        }), code

    _log(f"routes_audio_mixer registered (backend={backend})")
