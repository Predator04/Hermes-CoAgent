#!/usr/bin/env python
"""
Hermes CoAgent Installer — set up autostart via Windows Scheduled Task.
Run once: python coagent_install.py install
Remove:   python coagent_install.py uninstall
Status:   python coagent_install.py status

Sets up a scheduled task that launches CoAgent on user logon
with full interactive desktop access (UIA works, SOM finds windows).
"""
import sys, os, subprocess, getpass

COAGENT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(COAGENT_DIR, "hermes_coagent.py")
PYTHON = sys.executable
TASK_NAME = "Hermes CoAgent"
TASK_DESC = "Launches Hermes CoAgent desktop control server on user logon with UIA/SOM support"
USERNAME = getpass.getuser()

def run_powershell(script, timeout=15):
    """Run PowerShell command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

def install():
    """Create scheduled task for CoAgent autostart on logon."""
    print(f"[*] Installing Hermes CoAgent as scheduled task: {TASK_NAME}")
    
    # Build the command — use pythonw.exe for hidden window
    pythonw = PYTHON.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = PYTHON  # fallback
        print(f"[WARN] pythonw.exe not found at {pythonw}, using python.exe")
    
    # Create the scheduled task
    ps_script = f'''
$action = New-ScheduledTaskAction -Execute "{pythonw}" -Argument "`"{SCRIPT}`" --secure"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "{USERNAME}" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "{TASK_DESC}" -Force
'''
    
    rc, out, err = run_powershell(ps_script, timeout=30)
    if rc == 0:
        print(f"[+] Scheduled task '{TASK_NAME}' created successfully!")
        print(f"[+] CoAgent will start automatically on next logon.")
        print(f"[+] Running with --secure — auth token required for all requests")
        print(f"[+] UIA will have full desktop tree (Session 1)")
        print()
        # Verify
        rc2, out2, _ = run_powershell(f"Get-ScheduledTask -TaskName '{TASK_NAME}' | Format-List TaskName,State,TaskPath")
        if out2:
            print(out2)
    else:
        print(f"[!] Failed to create scheduled task:")
        print(f"    {err or out}")
        return False
    
    # Also start it now so user doesn't have to log off
    print("[*] Starting CoAgent now (no need to log off)...")
    rc3, _, err3 = run_powershell(f"Start-ScheduledTask -TaskName '{TASK_NAME}'")
    if rc3 == 0:
        print("[+] CoAgent started!")
    else:
        print(f"[!] Could not start now ({err3}). Will start on next logon.")
    
    return True

def uninstall():
    """Remove the scheduled task."""
    print(f"[*] Removing scheduled task: {TASK_NAME}")
    
    # Stop task first
    run_powershell(f"Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue")
    
    # Unregister
    rc, out, err = run_powershell(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false")
    
    if rc == 0:
        print(f"[+] Scheduled task '{TASK_NAME}' removed.")
    else:
        print(f"[!] Could not remove task: {err or out}")
        return False
    return True

def status():
    """Show current task status."""
    print(f"[*] Checking scheduled task: {TASK_NAME}")
    
    rc, out, err = run_powershell(f"Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue | Format-List TaskName,State,TaskPath,Description")
    
    if rc != 0 or not out:
        print(f"[!] Task '{TASK_NAME}' not found.")
        print(f"    Use 'install' to create it.")
    else:
        print(out)
        
        # Show last result
        rc2, out2, _ = run_powershell(f"""
$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($task) {{
    $result = $task.State
    Write-Output "State: $result"
    # Get last run time from task history
    $lastRun = (Get-ScheduledTask -TaskName '{TASK_NAME}').LastRunTime
    Write-Output "Last run: $(if ($lastRun -eq [datetime]::MinValue) {{ 'Never' }} else {{ $lastRun }})"
}}
""")
        if out2:
            print(out2)

def main():
    if len(sys.argv) < 2:
        print("Usage: python coagent_install.py [install|uninstall|status]")
        return
    
    cmd = sys.argv[1].lower()
    
    if cmd == "install":
        install()
    elif cmd in ("uninstall", "remove"):
        uninstall()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python coagent_install.py [install|uninstall|status]")

if __name__ == "__main__":
    main()
