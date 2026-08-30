"""Restart CoAgent by killing existing process and launching fresh via Scheduled Task.

Discovers the CoAgent PID dynamically (reads from PID file or finds by process name)
rather than using a hardcoded PID. Supports custom Python path and script path via env vars.
"""
import os
import getpass
import subprocess
import sys
import time

COAGENT_PID_FILE = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), ".coagent_pid")
COAGENT_SCRIPT = os.environ.get(
    "COAGENT_SCRIPT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes_coagent.py"),
)
PYTHON_EXE = os.environ.get("COAGENT_PYTHON", sys.executable)


def _ps_quote(value):
    """Quote a value for a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _pid_is_coagent(pid):
    """Return True if the given PID is a Python process running hermes_coagent."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, text=True, timeout=10,
        )
        return "hermes_coagent" in (result.stdout or "").lower()
    except (OSError, subprocess.SubprocessError):
        return False


def _find_coagent_pid():
    """Discover CoAgent PID from PID file or by scanning process list."""
    # 1. Try PID file first (verify the process is actually CoAgent, so a
    #    recycled PID pointing at an unrelated python.exe isn't killed).
    try:
        if os.path.isfile(COAGENT_PID_FILE):
            with open(COAGENT_PID_FILE) as f:
                pid = int(f.read().strip())
            if _pid_is_coagent(pid):
                return pid
    except (ValueError, OSError, subprocess.SubprocessError):
        pass

    # 2. Fall back: find python process running hermes_coagent via CommandLine
    #    (wmic is deprecated/removed on newer Windows 11 builds).
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "Where-Object { $_.CommandLine -like '*hermes_coagent*' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except (OSError, subprocess.SubprocessError):
        pass

    return None


def _kill_coagent(pid):
    """Kill the CoAgent process by PID, force-killing if it survives."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            capture_output=True, timeout=10,
        )
        time.sleep(2)
        # taskkill without /F doesn't raise on non-zero exit; a console
        # python.exe ignores WM_CLOSE, so force-kill if it's still alive.
        if _pid_is_coagent(pid):
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
            time.sleep(1)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        # Only drop the PID file once the process is actually gone. If the
        # kill failed, keeping it lets the next restart find the still-alive
        # process instead of spawning a duplicate.
        if not _pid_is_coagent(pid):
            try:
                os.remove(COAGENT_PID_FILE)
            except OSError:
                pass


def _launch_via_scheduled_task():
    """Launch CoAgent via a one-shot Scheduled Task (runs as admin desktop user)."""
    arg_string = f'"{COAGENT_SCRIPT}" --secure --allow-external'
    ps_cmd = (
        "$ErrorActionPreference='Stop';"
        "try {"
        f"$a=New-ScheduledTaskAction -Execute {_ps_quote(PYTHON_EXE)} "
        f"-Argument {_ps_quote(arg_string)} "
        f"-WorkingDirectory {_ps_quote(os.path.dirname(COAGENT_SCRIPT))};"
        "$t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(2);"
        f"$p=New-ScheduledTaskPrincipal -UserId {_ps_quote(getpass.getuser())} -LogonType Interactive -RunLevel Highest;"
        "Register-ScheduledTask -TaskName CoAgentLaunch -Action $a -Trigger $t -Principal $p -Force|Out-Null;"
        "Start-ScheduledTask -TaskName CoAgentLaunch"
        "} catch { Write-Error $_; exit 1 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        print(f"Failed to launch scheduled task: {result.stderr or result.stdout}", file=sys.stderr)
    return result.returncode == 0


def main():
    if sys.platform != "win32":
        print("CoAgent restart is Windows-only.", file=sys.stderr)
        sys.exit(1)
    pid = _find_coagent_pid()
    if pid:
        print(f"Found CoAgent PID: {pid}")
        _kill_coagent(pid)
    else:
        print("No running CoAgent found, launching fresh...")

    time.sleep(1)
    if not _launch_via_scheduled_task():
        print("Failed to launch CoAgent restart.", file=sys.stderr)
        sys.exit(1)
    print("CoAgent restart initiated.")


if __name__ == "__main__":
    main()
