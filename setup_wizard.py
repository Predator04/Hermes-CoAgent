#!/usr/bin/env python3
"""
Hermes CoAgent Setup Wizard
===========================
Interactive setup script — clones, configures, installs deps, sets up auth.
Run: python setup_wizard.py
"""

import os, sys, subprocess, json, getpass, textwrap, shutil, re, platform
from pathlib import Path

# ── Colors ──
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ── Config ──
COAGENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = COAGENT_DIR / "config.json"
TOKEN_FILE = COAGENT_DIR / ".token"

# ── Module definitions ──
MODULES = {
    "core": {
        "name": "Core Desktop Control",
        "deps": ["flask", "waitress", "pillow", "pyautogui", "pywinauto", "pygetwindow", "pyperclip", "pystray", "mss", "psutil"],
        "size": "~50MB",
        "desc": "Mouse/keyboard/screenshots/UIA/file ops/window management — the essentials",
        "default": True,
        "pip_cmd": "pip install flask waitress pillow pyautogui pywinauto pygetwindow pyperclip pystray mss psutil",
    },
    "ocr": {
        "name": "OCR (Text Recognition)",
        "deps": ["pytesseract"],
        "size": "~30MB (plus Tesseract engine)",
        "desc": "Read text from screenshots — requires Tesseract installed separately",
        "default": True,
        "pip_cmd": "pip install pytesseract",
        "extra": "Download Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki",
    },
    "gpu_screenshots": {
        "name": "GPU Screenshots (DXCam)",
        "deps": ["dxcam"],
        "size": "~2MB",
        "desc": "240fps GPU-accelerated screen capture (way faster than PIL)",
        "default": False,
        "pip_cmd": "pip install dxcam",
    },
    "browser": {
        "name": "Browser Automation (Playwright)",
        "deps": ["playwright"],
        "size": "~200MB (includes Chromium)",
        "desc": "Control Chrome/Edge via Playwright — navigate, click, fill forms",
        "default": False,
        "pip_cmd": "pip install playwright && playwright install chromium",
    },
    "google": {
        "name": "Google Workspace (Gmail + Calendar)",
        "deps": ["google-api-python-client", "google-auth-oauthlib"],
        "size": "~5MB",
        "desc": "Send emails, read Gmail, manage Calendar events",
        "default": False,
        "pip_cmd": "pip install google-api-python-client google-auth-oauthlib",
        "extra": "Requires a Google Cloud project with OAuth credentials",
    },
    "notifications": {
        "name": "Toast Notifications",
        "deps": ["win11toast"],
        "size": "~1MB",
        "desc": "Native Windows 10/11 toast popup notifications",
        "default": False,
        "pip_cmd": "pip install win11toast",
    },
    "agent_gateway": {
        "name": "Agent Gateway (Codex/Claude/Gemini)",
        "deps": [],
        "size": "0MB (uses existing CLI tools)",
        "desc": "Call Codex, Claude Code, Gemini CLI as HTTP endpoints. Requires those CLIs installed separately.",
        "default": True,
        "pip_cmd": "",
        "extra": "Install Codex: npm install -g @openai/codex\nInstall Claude: npm install -g @anthropic-ai/claude-code",
    },
    "encryption": {
        "name": "Encrypted Token Storage",
        "deps": ["cryptography"],
        "size": "~2MB",
        "desc": "Encrypts Google OAuth tokens with Fernet encryption",
        "default": False,
        "pip_cmd": "pip install cryptography",
    },
}

AUTOSTART_OPTIONS = {
    "none": "No autostart (manual launch only)",
    "scheduled_task": "Windows Scheduled Task (At logon, interactive session)",
    "startup_folder": "Startup folder shortcut (simpler, runs as current user)",
}

SECURITY_OPTIONS = {
    "random": {
        "name": "Random auto-generated token (recommended)",
        "desc": "Generates a secure 64-char hex token on first launch",
    },
    "password": {
        "name": "Password-derived token",
        "desc": "You set a password — token is derived from it via SHA256",
    },
    "custom": {
        "name": "Custom token",
        "desc": "You provide a specific token string",
    },
}


def print_header():
    os.system("cls" if os.name == "nt" else "clear")
    print(f"{BOLD}{CYAN}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║     Hermes CoAgent v7.8 Setup Wizard        ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════╝{RESET}")
    print()
    print(f"{YELLOW}This wizard will guide you through:{RESET}")
    print(f"  {CYAN}1.{RESET} Install Python dependencies")
    print(f"  {CYAN}2.{RESET} Configure authentication")
    print(f"  {CYAN}3.{RESET} Select which modules to enable")
    print(f"  {CYAN}4.{RESET} Set up autostart")
    print(f"  {CYAN}5.{RESET} Configure network binding")
    print(f"  {CYAN}6.{RESET} Launch CoAgent")
    print()
    print(f"{RED}Note: Requires Windows 10/11 and Python 3.8+{RESET}")
    print()


def ask_yesno(question, default=True):
    default_str = "Y/n" if default else "y/N"
    while True:
        answer = input(f"  {question} [{default_str}] ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print(f"  {RED}Please answer y or n.{RESET}")


def ask_choice(question, options, default=None):
    print(f"\n  {question}")
    print()
    keys = list(options.keys())
    for i, key in enumerate(keys):
        marker = " →" if key == default else "  "
        print(f"    {marker} {i+1}. {options[key]}")
    print()
    while True:
        answer = input(f"  Enter number (1-{len(keys)}){f' or Enter for default [{default}]' if default else ''}: ").strip()
        if not answer and default:
            return default
        try:
            idx = int(answer) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(f"  {RED}Please enter a number 1-{len(keys)}.{RESET}")


def check_python_version():
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 8):
        print(f"{RED}[!] Python 3.8+ required (found {v.major}.{v.minor}){RESET}")
        return False
    print(f"{GREEN}[✓] Python {v.major}.{v.minor}.{v.micro}{RESET}")
    return True


def check_windows():
    if os.name != "nt":
        print(f"{YELLOW}[!] CoAgent is designed for Windows. Some features may not work on {platform.system()}.{RESET}")
        return ask_yesno("Continue anyway?", False)
    print(f"{GREEN}[✓] Windows detected{RESET}")
    return True


def check_git():
    git = shutil.which("git")
    if git:
        print(f"{GREEN}[✓] Git found at: {git}{RESET}")
        return True
    else:
        print(f"{YELLOW}[!] Git not found — needed for updates. Install from https://git-scm.com/{RESET}")
        return ask_yesno("Skip git check?", True)


def select_modules():
    print(f"\n{BOLD}Select Modules{RESET}")
    print(f"{YELLOW}CoAgent has optional modules. Select what you need.{RESET}")
    print()
    
    selected = {}
    for key, mod in MODULES.items():
        default = mod["default"]
        print(f"  {BOLD}{mod['name']}{RESET}")
        print(f"    {mod['desc']}")
        print(f"    {CYAN}Size: {mod['size']}  |  Deps: {', '.join(mod['deps']) if mod['deps'] else 'None'}{RESET}")
        if mod.get("extra"):
            print(f"    {YELLOW}Note: {mod['extra']}{RESET}")
        
        if ask_yesno(f"  Install {mod['name']}?", default):
            selected[key] = mod
        print()
    
    return selected


def configure_auth():
    print(f"\n{BOLD}Authentication{RESET}")
    print(f"{YELLOW}CoAgent requires a Bearer token for all API requests.{RESET}")
    print()
    
    method = ask_choice("Choose auth method:", {
        opt["name"]: f"{opt['name']} — {opt['desc']}"
        for opt in SECURITY_OPTIONS.values()
    }, default="random")
    
    # Find the key
    auth_key = None
    for key, opt in SECURITY_OPTIONS.items():
        if opt["name"] == method:
            auth_key = key
            break
    
    if auth_key == "random":
        import secrets
        token = secrets.token_hex(32)
        print(f"\n  {GREEN}Generated token: {token}{RESET}")
        TOKEN_FILE.write_text(token, encoding="utf-8")
        if os.name == "nt":
            try:
                os.chmod(TOKEN_FILE, 0o600)
            except:
                pass
        print(f"  {CYAN}Saved to {TOKEN_FILE}{RESET}")
        print(f"  {RED}Save this token — you'll need it for API calls:{RESET}")
        print(f"  {BOLD}{token}{RESET}")
        return token
    
    elif auth_key == "password":
        while True:
            pw = getpass.getpass("  Enter a password: ")
            if len(pw) < 4:
                print(f"  {RED}Password must be at least 4 characters.{RESET}")
                continue
            pw2 = getpass.getpass("  Confirm password: ")
            if pw != pw2:
                print(f"  {RED}Passwords don't match.{RESET}")
                continue
            break
        import hashlib, secrets
        salt = secrets.token_hex(16)
        token = hashlib.sha256(f"{salt}:{pw}".encode()).hexdigest()
        print(f"\n  {GREEN}Token generated from password.{RESET}")
        print(f"  {CYAN}Derived token: {token[:16]}...{token[-8:]}{RESET}")
        TOKEN_FILE.write_text(token, encoding="utf-8")
        return token
    
    else:  # custom
        token = input("  Enter your token: ").strip()
        if token:
            TOKEN_FILE.write_text(token, encoding="utf-8")
            print(f"  {GREEN}Token saved.{RESET}")
            return token
        else:
            print(f"  {YELLOW}No token provided — will generate random on first launch.{RESET}")
            return None


def configure_network():
    print(f"\n{BOLD}Network Binding{RESET}")
    print(f"{YELLOW}CoAgent defaults to localhost only (127.0.0.1).{RESET}")
    print(f"{RED}WARNING: Binding to 0.0.0.0 exposes your desktop to your LAN!{RESET}")
    print()
    
    if ask_yesno("Allow LAN/external access? (bind 0.0.0.0)", False):
        return "0.0.0.0"
    return "127.0.0.1"


def configure_autostart():
    print(f"\n{BOLD}Autostart{RESET}")
    print(f"{YELLOW}CoAgent can start automatically when you log in.{RESET}")
    print()
    
    choice = ask_choice("Choose autostart method:", AUTOSTART_OPTIONS, default="none")
    
    if choice == "scheduled_task":
        print(f"\n  {CYAN}Will register a Windows Scheduled Task that starts CoAgent on logon.{RESET}")
        print(f"  {CYAN}Uses Interactive logon (Session 1) — required for UIA/desktop control.{RESET}")
        return "scheduled_task"
    elif choice == "startup_folder":
        print(f"\n  {CYAN}Will add a shortcut to the Windows Startup folder.{RESET}")
        return "startup_folder"
    return "none"


def install_deps(selected_modules):
    print(f"\n{BOLD}Installing Dependencies{RESET}")
    print()
    
    all_deps = set()
    pip_commands = set()
    extras = []
    
    for key, mod in selected_modules.items():
        all_deps.update(mod["deps"])
        if mod["pip_cmd"]:
            pip_commands.add(mod["pip_cmd"])
        if mod.get("extra"):
            extras.append(f"  {mod['name']}: {mod['extra']}")
    
    if not all_deps:
        print(f"  {YELLOW}No pip packages to install.{RESET}")
        return True
    
    print(f"  Packages to install: {', '.join(sorted(all_deps))}")
    print()
    
    if not ask_yesno("Install now?", True):
        print(f"  {YELLOW}Skipping installation. Install manually later:{RESET}")
        for cmd in sorted(pip_commands):
            print(f"    {cmd}")
        return True
    
    for cmd in sorted(pip_commands):
        print(f"\n  Running: {cmd}")
        print(f"  {YELLOW}This may take a few minutes...{RESET}")
        result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"  {GREEN}[✓] Done{RESET}")
        else:
            print(f"  {RED}[!] Failed:{RESET}")
            for line in result.stderr.splitlines()[-5:]:
                print(f"    {RED}{line}{RESET}")
            if not ask_yesno("Continue despite error?", False):
                return False
    
    if extras:
        print(f"\n  {YELLOW}Additional setup required:{RESET}")
        for extra in extras:
            print(extra)
        print()
        input("  Press Enter to continue...")
    
    return True


def setup_autostart(method, bind_host, token):
    if method == "none":
        print(f"  {YELLOW}No autostart configured. Run manually:{RESET}")
        print(f"    python hermes_coagent.py{RESET}")
        return True
    
    if method == "scheduled_task":
        ps_script = f'''
$taskName = "Hermes CoAgent"
$pythonw = "C:\\Program Files\\Python312\\pythonw.exe"
$script = "{COAGENT_DIR}\\hermes_coagent.py"
$action = New-ScheduledTaskAction -Execute "$pythonw" -Argument "`"$script`" --token=$token --bind=$bind_host"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$user = whoami
$principal = New-ScheduledTaskPrincipal -UserId "$user" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Hermes CoAgent Desktop Control" -Force
'''
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print(f"  {GREEN}[✓] Scheduled task created!{RESET}")
            print(f"  {CYAN}CoAgent will start on next logon.{RESET}")
            return True
        else:
            print(f"  {RED}[!] Failed: {r.stderr[:200]}{RESET}")
            return False
    
    if method == "startup_folder":
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup.exists():
            bat_path = startup / "Hermes CoAgent.bat"
            bat_content = f'''@echo off
cd /d "{COAGENT_DIR}"
start "" "pythonw.exe" hermes_coagent.py --token={token} --bind={bind_host}
'''
            bat_path.write_text(bat_content, encoding="ascii")
            print(f"  {GREEN}[✓] Startup shortcut created at: {bat_path}{RESET}")
            return True
        else:
            print(f"  {RED}[!] Startup folder not found{RESET}")
            return False
    
    return True


def launch_coagent(bind_host, token):
    print(f"\n{BOLD}Launch{RESET}")
    print()
    
    if ask_yesno("Start CoAgent now?", True):
        cmd = [
            sys.executable.replace("python.exe", "pythonw.exe")
            if sys.executable.endswith("python.exe") else sys.executable,
            str(COAGENT_DIR / "hermes_coagent.py"),
        ]
        if token:
            cmd.append(f"--token={token}")
        if bind_host == "0.0.0.0":
            cmd.append("--allow-external")
        
        if not cmd[0].endswith("pythonw.exe"):
            cmd[0] = cmd[0]  # use python if pythonw not available
        
        subprocess.Popen(
            cmd, cwd=str(COAGENT_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        print(f"  {GREEN}[✓] CoAgent launched!{RESET}")
        print(f"  {CYAN}Running on http://{bind_host}:9123/{RESET}")
        if token:
            print(f"  {CYAN}Token: {token[:16]}...{token[-8:]}{RESET}")
        print(f"\n  {BOLD}Quick test:{RESET}")
        print(f"    curl http://127.0.0.1:9123/ping")
        print(f"    curl -H 'Authorization: Bearer {token[:8]}...' http://127.0.0.1:9123/version")
    else:
        print(f"  {YELLOW}Run manually:{RESET}")
        print(f"    cd {COAGENT_DIR}")
        if bind_host == "0.0.0.0":
            print(f"    python hermes_coagent.py --token=<token> --allow-external")
        else:
            print(f"    python hermes_coagent.py --token=<token>")
    
    return True


def save_config(selected_modules, auth_token, bind_host, autostart_method):
    config = {
        "version": "7.8",
        "setup_complete": True,
        "bind_host": bind_host,
        "autostart": autostart_method,
        "modules": list(selected_modules.keys()),
        "setup_date": subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Date -Format yyyy-MM-dd"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip() or "",
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"  {GREEN}[✓] Config saved to {CONFIG_FILE}{RESET}")


def print_summary(selected_modules, auth_token, bind_host, autostart_method):
    print(f"\n{BOLD}{GREEN}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{GREEN}║         Setup Complete!                      ║{RESET}")
    print(f"{BOLD}{GREEN}╚══════════════════════════════════════════════╝{RESET}")
    print()
    print(f"  {BOLD}Installed Modules:{RESET}")
    for key in selected_modules:
        print(f"    {GREEN}[✓]{RESET} {MODULES[key]['name']}")
    print()
    print(f"  {BOLD}Auth:{RESET}")
    if auth_token:
        print(f"    Token: {auth_token[:16]}...{auth_token[-8:]}")
        print(f"    File:  {TOKEN_FILE}")
    else:
        print(f"    {YELLOW}No token — run with --secure{RESET}")
    print()
    print(f"  {BOLD}Network:{RESET} http://{bind_host}:9123/")
    print(f"  {BOLD}Autostart:{RESET} {autostart_method.replace('_', ' ').title()}")
    print()
    print(f"  {BOLD}For AI agents:{RESET}")
    print(f"    Read {CYAN}AGENTS.md{RESET} for the full API reference")
    print(f"    Dashboard: http://127.0.0.1:9123/")
    print(f"    Agent Gateway: POST /agent/exec -H 'Authorization: Bearer <token>'")
    print()


def main():
    print_header()
    
    # Checks
    if not check_python_version():
        sys.exit(1)
    if not check_windows():
        sys.exit(1)
    check_git()
    
    # Module selection
    selected = select_modules()
    if not selected:
        print(f"\n{YELLOW}No modules selected — the server won't be useful with no modules.{RESET}")
        if not ask_yesno("Continue with no modules?", False):
            sys.exit(1)
    
    # Auth
    token = configure_auth()
    
    # Network
    bind_host = configure_network()
    
    # Autostart
    autostart_method = configure_autostart()
    
    # Summary before install
    print(f"\n{BOLD}{CYAN}Ready to install:{RESET}")
    print(f"  Modules: {', '.join(selected.keys())}")
    print(f"  Auth: {'Configured' if token else 'Not configured'}")
    print(f"  Network: {bind_host}")
    print(f"  Autostart: {autostart_method}")
    print()
    
    if not ask_yesno("Proceed with installation?", True):
        print(f"\n{YELLOW}Setup cancelled.{RESET}")
        sys.exit(0)
    
    # Install deps
    dep_ok = install_deps(selected)
    
    # Autostart
    autostart_ok = setup_autostart(autostart_method, bind_host, token)
    
    # Save config
    save_config(selected, token, bind_host, autostart_method)
    
    # Launch
    launch_coagent(bind_host, token)
    
    # Summary
    print_summary(selected, token, bind_host, autostart_method)
    
    print(f"  {BOLD}Need help?{RESET}")
    print(f"    Read: {CYAN}AGENTS.md{RESET}")
    print(f"    GitHub: {CYAN}https://github.com/Predator04/Hermes-CoAgent{RESET}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Setup cancelled.{RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")
        sys.exit(1)
