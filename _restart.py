"""Restart CoAgent by killing existing process and launching fresh via Scheduled Task.

Discovers the CoAgent PID dynamically (reads from PID file or finds by process name)
rather than using a hardcoded PID. Supports custom Python path and script path via env vars.
"""
import os
import subprocess
import sys
import time

COAGENT_PID_FILE = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), ".coagent_pid")
COAGENT_SCRIPT = os.environ.get(
    "COAGENT_SCRIPT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes_coagent.py"),
)
PYTHON_EXE = os.environ.get("COAGENT_PYTHON", sys.executable)


def _find_coagent_pid():
    """Discover CoAgent PID from PID file or by scanning process list."""
    # 1. Try PID file first
    try:
        if os.path.isfile(COAGENT_PID_FILE):
            with open(COAGENT_PID_FILE) as f:
                pid = int(f.read().strip())
            # Verify the process still exists
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if "python" in result.stdout.lower() or "coagent" in result.stdout.lower():
                return pid
    except (ValueError, OSError, subprocess.SubprocessError):
        pass

    # 2. Fall back: find python process running hermes_coagent
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='pythonw.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "hermes_coagent" in line:
                parts = line.strip().split(",")
                pid_str = parts[-1].strip()
                if pid_str.isdigit():
                    return int(pid_str)
    except (OSError, subprocess.SubprocessError):
        pass

    return None


def _kill_coagent(pid):
    """Gracefully kill the CoAgent process by PID."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            capture_output=True, timeout=10,
        )
        time.sleep(2)
    except subprocess.SubprocessError:
        # Force kill if graceful fails
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, timeout=10,
        )
        time.sleep(1)


def _launch_via_scheduled_task():
    """Launch CoAgent via a one-shot Scheduled Task (runs as admin desktop user)."""
    ps_cmd = (
        f"$a=New-ScheduledTaskAction -Execute '{PYTHON_EXE}' "
        f"-Argument '{COAGENT_SCRIPT} --secure --allow-external' "
        f"-WorkingDirectory '{os.path.dirname(COAGENT_SCRIPT)}';"
        "$t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(2);"
        "$p=New-ScheduledTaskPrincipal -UserId 'Admin' -LogonType Interactive -RunLevel Highest;"
        "Register-ScheduledTask -TaskName CoAgentLaunch -Action $a -Trigger $t -Principal $p -Force|Out-Null;"
        "Start-ScheduledTask -TaskName CoAgentLaunch"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, timeout=15,
    )


def main():
    pid = _find_coagent_pid()
    if pid:
        print(f"Found CoAgent PID: {pid}")
        _kill_coagent(pid)
    else:
        print("No running CoAgent found, launching fresh...")

    time.sleep(1)
    _launch_via_scheduled_task()
    print("CoAgent restart initiated.")


if __name__ == "__main__":
    main()
