#!/usr/bin/env python3
"""
Hermes CoAgent Setup Wizard
===========================
Interactive and unattended setup for Hermes CoAgent.

Run:
  python setup_wizard.py
  python setup_wizard.py --auto
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


# Config
COAGENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = COAGENT_DIR / "config.json"
TOKEN_FILE = COAGENT_DIR / ".token"


# Module definitions
MODULES = {
    "core": {
        "name": "Core Desktop Control",
        "deps": [
            "flask",
            "waitress",
            "pillow",
            "pyautogui",
            "pywinauto",
            "pygetwindow",
            "pyperclip",
            "pystray",
            "mss",
            "psutil",
        ],
        "size": "~50MB",
        "desc": "Mouse/keyboard/screenshots/UIA/file ops/window management - the essentials",
        "default": True,
    },
    "ocr": {
        "name": "OCR (Text Recognition)",
        "deps": ["pytesseract"],
        "size": "~30MB (plus Tesseract engine)",
        "desc": "Read text from screenshots - requires Tesseract installed separately",
        "default": True,
        "extra": "Download Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki",
    },
    "gpu_screenshots": {
        "name": "GPU Screenshots (DXCam)",
        "deps": ["dxcam"],
        "size": "~2MB",
        "desc": "240fps GPU-accelerated screen capture (way faster than PIL)",
        "default": False,
    },
    "browser": {
        "name": "Browser Automation (Playwright)",
        "deps": ["playwright"],
        "size": "~200MB (includes Chromium)",
        "desc": "Control Chrome/Edge via Playwright - navigate, click, fill forms",
        "default": False,
        "post_install": [["playwright", "install", "chromium"]],
    },
    "google": {
        "name": "Google Workspace (Gmail + Calendar)",
        "deps": ["google-api-python-client", "google-auth-oauthlib"],
        "size": "~5MB",
        "desc": "Send emails, read Gmail, manage Calendar events",
        "default": False,
        "extra": "Requires a Google Cloud project with OAuth credentials",
    },
    "notifications": {
        "name": "Toast Notifications",
        "deps": ["win11toast"],
        "size": "~1MB",
        "desc": "Native Windows 10/11 toast popup notifications",
        "default": False,
    },
    "agent_gateway": {
        "name": "Agent Gateway (Codex/Claude/Gemini)",
        "deps": [],
        "size": "0MB (uses existing CLI tools)",
        "desc": "Call Codex, Claude Code, Gemini CLI as HTTP endpoints. Requires those CLIs installed separately.",
        "default": True,
        "extra": "Install Codex: npm install -g @openai/codex\nInstall Claude: npm install -g @anthropic-ai/claude-code",
    },
    "encryption": {
        "name": "Encrypted Token Storage",
        "deps": ["cryptography"],
        "size": "~2MB",
        "desc": "Encrypts Google OAuth tokens with Fernet encryption",
        "default": False,
    },
}

AUTOSTART_OPTIONS = {
    "none": "No autostart (manual launch only)",
    "scheduled_task": "Windows Scheduled Task (at logon, interactive session)",
    "startup_folder": "Startup folder launcher (simpler, runs as current user)",
}

SECURITY_OPTIONS = {
    "random": {
        "name": "Random auto-generated token (recommended)",
        "desc": "Generates a secure 64-char hex token now",
    },
    "password": {
        "name": "Password-derived token",
        "desc": "You set a password and the wizard stores a SHA256-derived token",
    },
    "custom": {
        "name": "Custom token",
        "desc": "You provide a specific token string",
    },
}


class SetupAbort(Exception):
    """Raised when setup cannot continue because the user declined a recovery step."""


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _supports_stdout(value: str) -> bool:
    encoding = sys.stdout.encoding or "utf-8"
    try:
        value.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


CHECK_MARK = "\u2713" if _supports_stdout("\u2713") else "OK"


def _normalize_dist_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _format_command(cmd: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    return " ".join(shlex_quote(part) for part in cmd)


def shlex_quote(value: str) -> str:
    if value and all(ch.isalnum() or ch in "@%_+=:,./-" for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _tail_text(text: str, max_lines: int = 35) -> str:
    lines = text.strip().splitlines()
    if len(lines) > max_lines:
        lines = ["... output truncated ..."] + lines[-max_lines:]
    return "\n".join(lines)


def _safe_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError as exc:
        raise SetupAbort("Input stream closed. Re-run with --auto for unattended setup.") from exc


def _run_with_dots(cmd: list[str], timeout: int = 300, cwd: Path | None = None) -> CommandResult:
    stdout_path = None
    stderr_path = None
    proc = None

    try:
        with tempfile.NamedTemporaryFile(delete=False) as stdout_file:
            stdout_path = Path(stdout_file.name)
        with tempfile.NamedTemporaryFile(delete=False) as stderr_file:
            stderr_path = Path(stderr_file.name)

        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creationflags,
            )

            started = time.monotonic()
            while proc.poll() is None:
                if timeout and (time.monotonic() - started) > timeout:
                    proc.kill()
                    proc.wait(timeout=10)
                    print(" timeout", flush=True)
                    stdout = stdout_path.read_bytes().decode("utf-8", errors="replace")
                    stderr = stderr_path.read_bytes().decode("utf-8", errors="replace")
                    return CommandResult(proc.returncode or 124, stdout, stderr, timed_out=True)
                print(".", end="", flush=True)
                time.sleep(1)

        print()
        stdout = stdout_path.read_bytes().decode("utf-8", errors="replace")
        stderr = stderr_path.read_bytes().decode("utf-8", errors="replace")
        return CommandResult(proc.returncode or 0, stdout, stderr)

    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except Exception as exc:
        if proc and proc.poll() is None:
            proc.kill()
        return CommandResult(1, "", str(exc))
    finally:
        for path in (stdout_path, stderr_path):
            if path:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass


def print_header(clear_screen: bool = True) -> None:
    if clear_screen:
        os.system("cls" if os.name == "nt" else "clear")

    print(f"{BOLD}{CYAN}+----------------------------------------------+{RESET}")
    print(f"{BOLD}{CYAN}|        Hermes CoAgent v7.8 Setup Wizard      |{RESET}")
    print(f"{BOLD}{CYAN}+----------------------------------------------+{RESET}")
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


def ask_yesno(question: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        answer = _safe_input(f"  {question} [{default_str}] ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print(f"  {RED}Please answer y or n.{RESET}")


def ask_choice(question: str, options: dict[str, str], default: str | None = None) -> str:
    print(f"\n  {question}")
    print()
    keys = list(options.keys())
    for i, key in enumerate(keys):
        marker = "*" if key == default else " "
        print(f"    {marker} {i + 1}. {options[key]}")
    print()

    while True:
        default_text = f" or Enter for default [{default}]" if default else ""
        answer = _safe_input(f"  Enter number (1-{len(keys)}){default_text}: ").strip()
        if not answer and default:
            return default
        try:
            idx = int(answer) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(f"  {RED}Please enter a number 1-{len(keys)}.{RESET}")


def check_python_version() -> bool:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 8):
        print(f"{RED}[!] Python 3.8+ required (found {v.major}.{v.minor}){RESET}")
        return False
    print(f"{GREEN}[{CHECK_MARK}] Python {v.major}.{v.minor}.{v.micro}{RESET}")
    return True


def check_windows(auto: bool = False) -> bool:
    if os.name != "nt":
        print(f"{YELLOW}[!] CoAgent is designed for Windows. Detected: {platform.system()}.{RESET}")
        if auto:
            print(f"{YELLOW}    Continuing because --auto cannot prompt.{RESET}")
            return True
        return ask_yesno("Continue anyway?", False)
    print(f"{GREEN}[{CHECK_MARK}] Windows detected{RESET}")
    return True


def check_git(auto: bool = False) -> bool:
    git = shutil.which("git")
    if git:
        print(f"{GREEN}[{CHECK_MARK}] Git found at: {git}{RESET}")
        return True

    print(f"{YELLOW}[!] Git not found - needed only for updates. Install from https://git-scm.com/{RESET}")
    if auto:
        print(f"{YELLOW}    Continuing because --auto cannot prompt.{RESET}")
        return True
    return ask_yesno("Skip git check?", True)


def scan_installed_deps() -> dict[str, str] | None:
    """Return installed pip distributions keyed by normalized package name."""
    cmd = [sys.executable, "-m", "pip", "list", "--format=json"]
    print(f"\n{BOLD}Scanning Installed Dependencies{RESET}")
    print(f"  Running: {_format_command(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        print(f"  {RED}[!] pip is not available: {exc}{RESET}")
        print("  Next step: reinstall Python with pip enabled, then rerun this wizard.")
        return None
    except subprocess.TimeoutExpired:
        print(f"  {RED}[!] pip list timed out after 60 seconds.{RESET}")
        print("  Next step: try running the same command manually to inspect pip health.")
        return None

    if result.returncode != 0:
        print(f"  {RED}[!] pip list failed with exit code {result.returncode}.{RESET}")
        if result.stderr.strip():
            print(f"  {RED}{_tail_text(result.stderr, 12)}{RESET}")
        print("  Next step: try `python -m pip install --upgrade pip setuptools wheel`.")
        return None

    try:
        packages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"  {RED}[!] Could not parse pip list JSON: {exc}{RESET}")
        print("  Next step: run `python -m pip list --format=json` and check for non-JSON output.")
        return None

    installed = {}
    for pkg in packages:
        name = str(pkg.get("name", "")).strip()
        if name:
            installed[_normalize_dist_name(name)] = str(pkg.get("version", ""))

    print(f"  {GREEN}[{CHECK_MARK}] Found {len(installed)} installed Python packages{RESET}")
    return installed


def _missing_deps(mod: dict, installed_deps: dict[str, str] | None) -> list[str]:
    deps = mod.get("deps", [])
    if installed_deps is None:
        return list(deps)
    return [dep for dep in deps if _normalize_dist_name(dep) not in installed_deps]


def _module_status(mod: dict, installed_deps: dict[str, str] | None) -> str:
    deps = mod.get("deps", [])
    if not deps:
        return "No Python packages required"
    if installed_deps is None:
        return "Install status unavailable"

    missing = _missing_deps(mod, installed_deps)
    if not missing:
        return f"Already installed {CHECK_MARK}"
    if len(missing) == len(deps):
        return "Missing: " + ", ".join(missing)
    return "Partially installed; missing: " + ", ".join(missing)


def _print_card_line(text: str, width: int) -> None:
    print(f"  | {text[:width].ljust(width)} |")


def print_module_card(mod: dict, installed_deps: dict[str, str] | None) -> None:
    width = 58
    print("  +" + "-" * (width + 2) + "+")
    _print_card_line(f"{mod['name']}  Size: {mod['size']}", width)
    _print_card_line(_module_status(mod, installed_deps), width)
    for line in textwrap.wrap(mod["desc"], width=width):
        _print_card_line(line, width)

    deps = mod.get("deps", [])
    dep_text = "Deps: " + (", ".join(deps) if deps else "None")
    for line in textwrap.wrap(dep_text, width=width):
        _print_card_line(line, width)

    if mod.get("extra"):
        for extra_line in str(mod["extra"]).splitlines():
            for line in textwrap.wrap("Note: " + extra_line, width=width):
                _print_card_line(line, width)
    print("  +" + "-" * (width + 2) + "+")


def select_modules(installed_deps: dict[str, str] | None) -> dict[str, dict]:
    print(f"\n{BOLD}Select Modules{RESET}")
    print(f"{YELLOW}CoAgent has optional modules. Select what you need.{RESET}")
    print()

    selected = {}
    for key, mod in MODULES.items():
        print_module_card(mod, installed_deps)
        if ask_yesno(f"Install {mod['name']}?", bool(mod["default"])):
            selected[key] = mod
        print()

    return selected


def save_token(token: str) -> None:
    try:
        TOKEN_FILE.write_text(token, encoding="utf-8")
        if os.name == "nt":
            try:
                os.chmod(TOKEN_FILE, 0o600)
            except OSError:
                pass
    except OSError as exc:
        raise SetupAbort(f"Could not write token file {TOKEN_FILE}: {exc}") from exc


def generate_random_token() -> str:
    token = secrets.token_hex(32)
    save_token(token)
    print(f"\n  {GREEN}Generated token: {token}{RESET}")
    print(f"  {CYAN}Saved to {TOKEN_FILE}{RESET}")
    print(f"  {RED}Save this token - you will need it for API calls:{RESET}")
    print(f"  {BOLD}{token}{RESET}")
    return token


def configure_auth(auto: bool = False) -> str:
    print(f"\n{BOLD}Authentication{RESET}")
    print(f"{YELLOW}CoAgent requires a Bearer token for all API requests.{RESET}")
    print()

    if auto:
        print(f"  {CYAN}--auto selected: generating a random token.{RESET}")
        return generate_random_token()

    method = ask_choice(
        "Choose auth method:",
        {key: f"{opt['name']} - {opt['desc']}" for key, opt in SECURITY_OPTIONS.items()},
        default="random",
    )

    if method == "random":
        return generate_random_token()

    if method == "password":
        import hashlib

        while True:
            pw = getpass.getpass("  Enter a password: ")
            if len(pw) < 4:
                print(f"  {RED}Password must be at least 4 characters.{RESET}")
                continue
            pw2 = getpass.getpass("  Confirm password: ")
            if pw != pw2:
                print(f"  {RED}Passwords do not match.{RESET}")
                continue
            break

        salt = secrets.token_hex(16)
        token = hashlib.sha256(f"{salt}:{pw}".encode("utf-8")).hexdigest()
        save_token(token)
        print(f"\n  {GREEN}Token generated from password.{RESET}")
        print(f"  {CYAN}Derived token: {token[:16]}...{token[-8:]}{RESET}")
        print(f"  {CYAN}Saved to {TOKEN_FILE}{RESET}")
        return token

    token = _safe_input("  Enter your token: ").strip()
    if not token:
        print(f"  {YELLOW}No custom token entered - generating a random token instead.{RESET}")
        return generate_random_token()
    save_token(token)
    print(f"  {GREEN}Token saved to {TOKEN_FILE}.{RESET}")
    return token


def configure_network(auto: bool = False) -> str:
    print(f"\n{BOLD}Network Binding{RESET}")
    print(f"{YELLOW}CoAgent defaults to localhost only (127.0.0.1).{RESET}")
    print(f"{RED}WARNING: Binding to 0.0.0.0 exposes desktop control to your LAN.{RESET}")
    print()

    if auto:
        print(f"  {CYAN}--auto selected: using localhost only.{RESET}")
        return "127.0.0.1"

    if ask_yesno("Allow LAN/external access? (bind 0.0.0.0)", False):
        return "0.0.0.0"
    return "127.0.0.1"


def configure_autostart(auto: bool = False) -> str:
    print(f"\n{BOLD}Autostart{RESET}")
    print(f"{YELLOW}CoAgent can start automatically when you log in.{RESET}")
    print()

    if auto:
        print(f"  {CYAN}--auto selected: autostart disabled.{RESET}")
        return "none"

    choice = ask_choice("Choose autostart method:", AUTOSTART_OPTIONS, default="none")

    if choice == "scheduled_task":
        print(f"\n  {CYAN}Will register a Windows Scheduled Task that starts CoAgent on logon.{RESET}")
        print(f"  {CYAN}Uses interactive logon - required for UIA/desktop control.{RESET}")
    elif choice == "startup_folder":
        print(f"\n  {CYAN}Will add a launcher to the Windows Startup folder.{RESET}")
    return choice


def _pip_install(packages: list[str]) -> tuple[list[str], CommandResult]:
    cmd = [sys.executable, "-m", "pip", "install", *packages]
    print(f"  Running: {_format_command(cmd)}")
    print("  Progress", end="", flush=True)
    return cmd, _run_with_dots(cmd, timeout=600, cwd=COAGENT_DIR)


def _run_post_install(step: list[str]) -> tuple[list[str], CommandResult]:
    cmd = [sys.executable, "-m", *step]
    print(f"  Running: {_format_command(cmd)}")
    print("  Progress", end="", flush=True)
    return cmd, _run_with_dots(cmd, timeout=900, cwd=COAGENT_DIR)


def _print_command_failure(cmd: list[str], result: CommandResult, package_context: str) -> None:
    print(f"  {RED}[!] {package_context} failed with exit code {result.returncode}.{RESET}")
    if result.timed_out:
        print(f"  {RED}[!] Command timed out before it completed.{RESET}")
    print(f"  Command: {_format_command(cmd)}")

    if result.stdout.strip():
        print(f"  {YELLOW}stdout:{RESET}")
        for line in _tail_text(result.stdout).splitlines():
            print(f"    {line}")
    if result.stderr.strip():
        print(f"  {YELLOW}stderr:{RESET}")
        for line in _tail_text(result.stderr).splitlines():
            print(f"    {line}")

    print("  Next steps:")
    print(f"    1. Retry manually: {_format_command(cmd)}")
    print(f"    2. Upgrade packaging tools: {_format_command([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'])}")
    print("    3. Check internet/proxy/SSL settings and whether the package supports this Python version.")


def install_deps(
    selected_modules: dict[str, dict],
    installed_deps: dict[str, str] | None,
    auto: bool = False,
) -> tuple[bool, list[dict[str, str]]]:
    print(f"\n{BOLD}Installing Dependencies{RESET}")
    print()

    if installed_deps is None:
        print(f"  {YELLOW}Installed-package scan failed, so selected dependencies will be treated as missing.{RESET}")
        installed_deps = {}

    failures: list[dict[str, str]] = []
    extras: list[str] = []

    for key, mod in selected_modules.items():
        if mod.get("extra"):
            extras.append(f"  {mod['name']}: {mod['extra']}")

        missing = _missing_deps(mod, installed_deps)
        if not missing:
            deps_label = ", ".join(mod.get("deps", [])) if mod.get("deps") else "no pip packages"
            print(f"  {GREEN}[{CHECK_MARK}] {mod['name']}: {deps_label} already installed{RESET}")
        else:
            print(f"\n  {BOLD}{mod['name']}{RESET}")
            print(f"  Missing packages: {', '.join(missing)}")
            cmd, result = _pip_install(missing)
            if result.returncode == 0:
                print(f"  {GREEN}[{CHECK_MARK}] Installed: {', '.join(missing)}{RESET}")
                for dep in missing:
                    installed_deps[_normalize_dist_name(dep)] = "installed"
            else:
                failures.append({"module": key, "name": mod["name"], "step": "pip install"})
                _print_command_failure(cmd, result, f"Installing {mod['name']}")
                if not auto and not ask_yesno("Continue despite this dependency error?", False):
                    return False, failures
                print(f"  {YELLOW}Continuing; {mod['name']} may not work until dependencies are installed.{RESET}")
                continue

        for step in mod.get("post_install", []):
            print(f"\n  {BOLD}{mod['name']} post-install step{RESET}")
            cmd, result = _run_post_install(step)
            if result.returncode == 0:
                print(f"  {GREEN}[{CHECK_MARK}] Post-install complete{RESET}")
            else:
                failures.append({"module": key, "name": mod["name"], "step": "post install"})
                _print_command_failure(cmd, result, f"Post-install for {mod['name']}")
                if not auto and not ask_yesno("Continue despite this post-install error?", False):
                    return False, failures
                print(f"  {YELLOW}Continuing; {mod['name']} browser runtime may need manual setup.{RESET}")

    if extras:
        print(f"\n  {YELLOW}Additional setup notes:{RESET}")
        for extra in extras:
            print(extra)
        print()
        if not auto:
            _safe_input("  Press Enter to continue...")

    if failures:
        print(f"\n  {YELLOW}Dependency setup completed with {len(failures)} failure(s).{RESET}")
    else:
        print(f"\n  {GREEN}[{CHECK_MARK}] Dependency setup complete{RESET}")

    return True, failures


def _python_launcher(prefer_windowless: bool = False) -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and prefer_windowless and exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def _coagent_command(bind_host: str, token: str, prefer_windowless: bool = False) -> list[str]:
    cmd = [_python_launcher(prefer_windowless), str(COAGENT_DIR / "hermes_coagent.py")]
    if token:
        cmd.append(f"--token={token}")
    else:
        cmd.append("--secure")
    if bind_host == "0.0.0.0":
        cmd.append("--allow-external")
    return cmd


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def setup_autostart(method: str, bind_host: str, token: str) -> bool:
    if method == "none":
        print(f"  {YELLOW}No autostart configured. Run manually:{RESET}")
        print(f"    {_format_command(_coagent_command(bind_host, token))}")
        return True

    if os.name != "nt":
        print(f"  {RED}[!] Autostart setup is only supported on Windows by this wizard.{RESET}")
        return False

    if method == "scheduled_task":
        cmd = _coagent_command(bind_host, token, prefer_windowless=True)
        executable = cmd[0]
        arguments = subprocess.list2cmdline(cmd[1:])
        ps_script = "\n".join(
            [
                "$taskName = 'Hermes CoAgent'",
                f"$pythonExe = {_ps_single_quote(executable)}",
                f"$arguments = {_ps_single_quote(arguments)}",
                f"$workdir = {_ps_single_quote(str(COAGENT_DIR))}",
                "$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $workdir",
                "$trigger = New-ScheduledTaskTrigger -AtLogOn",
                "$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
                "$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest",
                "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable",
                "Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Hermes CoAgent Desktop Control' -Force",
            ]
        )
        run_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
        result = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=45,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print(f"  {GREEN}[{CHECK_MARK}] Scheduled task created.{RESET}")
            print(f"  {CYAN}CoAgent will start on next logon.{RESET}")
            return True

        print(f"  {RED}[!] Failed to create scheduled task.{RESET}")
        if result.stderr.strip():
            print(f"  {RED}{_tail_text(result.stderr, 12)}{RESET}")
        print(f"  Retry manually with: {_format_command(run_cmd)}")
        return False

    if method == "startup_folder":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            print(f"  {RED}[!] APPDATA is not set; cannot find Startup folder.{RESET}")
            return False

        startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if not startup.exists():
            print(f"  {RED}[!] Startup folder not found: {startup}{RESET}")
            return False

        bat_path = startup / "Hermes CoAgent.bat"
        cmdline = subprocess.list2cmdline(_coagent_command(bind_host, token, prefer_windowless=True))
        bat_content = f'@echo off\r\ncd /d "{COAGENT_DIR}"\r\nstart "" {cmdline}\r\n'
        try:
            bat_path.write_text(bat_content, encoding="ascii", errors="replace")
        except OSError as exc:
            print(f"  {RED}[!] Could not write startup launcher: {exc}{RESET}")
            return False

        print(f"  {GREEN}[{CHECK_MARK}] Startup launcher created at: {bat_path}{RESET}")
        return True

    print(f"  {RED}[!] Unknown autostart method: {method}{RESET}")
    return False


def launch_coagent(bind_host: str, token: str, auto: bool = False) -> bool:
    print(f"\n{BOLD}Launch{RESET}")
    print()

    start_now = True if auto else ask_yesno("Start CoAgent now?", True)
    cmd = _coagent_command(bind_host, token, prefer_windowless=True)

    if start_now:
        try:
            subprocess.Popen(
                cmd,
                cwd=str(COAGENT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except OSError as exc:
            print(f"  {RED}[!] Could not launch CoAgent: {exc}{RESET}")
            print(f"  Retry manually: {_format_command(cmd)}")
            return False

        print(f"  {GREEN}[{CHECK_MARK}] CoAgent launched.{RESET}")
        print(f"  {CYAN}Running on http://{bind_host}:9123/{RESET}")
        if token:
            print(f"  {CYAN}Token: {token[:16]}...{token[-8:]}{RESET}")
        print(f"\n  {BOLD}Quick test:{RESET}")
        print("    curl http://127.0.0.1:9123/ping")
        print(f"    curl -H \"Authorization: Bearer {token[:8]}...\" http://127.0.0.1:9123/version")
        return True

    print(f"  {YELLOW}Run manually:{RESET}")
    print(f"    cd {COAGENT_DIR}")
    print(f"    {_format_command(cmd)}")
    return True


def save_config(
    selected_modules: dict[str, dict],
    auth_token: str,
    bind_host: str,
    autostart_method: str,
    dependency_failures: list[dict[str, str]],
) -> bool:
    config = {
        "version": "7.8",
        "setup_complete": True,
        "bind_host": bind_host,
        "autostart": autostart_method,
        "modules": list(selected_modules.keys()),
        "dependency_failures": dependency_failures,
        "setup_date": datetime.now().date().isoformat(),
        "token_file": str(TOKEN_FILE) if auth_token else "",
    }

    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"  {RED}[!] Could not save config to {CONFIG_FILE}: {exc}{RESET}")
        return False

    print(f"  {GREEN}[{CHECK_MARK}] Config saved to {CONFIG_FILE}{RESET}")
    return True


def print_summary(
    selected_modules: dict[str, dict],
    auth_token: str,
    bind_host: str,
    autostart_method: str,
    dependency_failures: list[dict[str, str]],
) -> None:
    failed_keys = {failure["module"] for failure in dependency_failures}

    print(f"\n{BOLD}{GREEN}+----------------------------------------------+{RESET}")
    print(f"{BOLD}{GREEN}|              Setup Complete                  |{RESET}")
    print(f"{BOLD}{GREEN}+----------------------------------------------+{RESET}")
    print()
    print(f"  {BOLD}Selected Modules:{RESET}")
    for key in selected_modules:
        marker = f"{YELLOW}[!]{RESET}" if key in failed_keys else f"{GREEN}[{CHECK_MARK}]{RESET}"
        suffix = " (dependency setup needs attention)" if key in failed_keys else ""
        print(f"    {marker} {MODULES[key]['name']}{suffix}")

    if dependency_failures:
        print()
        print(f"  {YELLOW}Dependency Failures:{RESET}")
        for failure in dependency_failures:
            print(f"    - {failure['name']}: {failure['step']}")

    print()
    print(f"  {BOLD}Auth:{RESET}")
    print(f"    Token: {auth_token[:16]}...{auth_token[-8:]}")
    print(f"    File:  {TOKEN_FILE}")
    print()
    print(f"  {BOLD}Network:{RESET} http://{bind_host}:9123/")
    print(f"  {BOLD}Autostart:{RESET} {autostart_method.replace('_', ' ').title()}")
    print()
    print(f"  {BOLD}For AI agents:{RESET}")
    print(f"    Read {CYAN}AGENTS.md{RESET} for the full API reference")
    print("    Dashboard: http://127.0.0.1:9123/")
    print("    Agent Gateway: POST /agent/exec -H \"Authorization: Bearer <token>\"")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure, install dependencies for, and optionally launch Hermes CoAgent.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Run unattended with smart defaults: install all modules, generate a random token, "
            "bind localhost only, skip autostart, and launch immediately."
        ),
    )
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal before the wizard starts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print_header(clear_screen=not args.no_clear and not args.auto)

    if args.auto:
        print(f"{CYAN}Running in --auto mode. No prompts will be shown.{RESET}")
        print()

    if not check_python_version():
        return 1
    if not check_windows(auto=args.auto):
        return 1
    check_git(auto=args.auto)

    installed_deps = scan_installed_deps()

    if args.auto:
        selected = dict(MODULES)
        print(f"\n{BOLD}Select Modules{RESET}")
        print(f"  {CYAN}--auto selected: all modules will be installed where possible.{RESET}")
        for mod in selected.values():
            print_module_card(mod, installed_deps)
    else:
        selected = select_modules(installed_deps)
        if not selected:
            print(f"\n{YELLOW}No modules selected - the server will not be useful with no modules.{RESET}")
            if not ask_yesno("Continue with no modules?", False):
                return 1

    token = configure_auth(auto=args.auto)
    bind_host = configure_network(auto=args.auto)
    autostart_method = configure_autostart(auto=args.auto)

    print(f"\n{BOLD}{CYAN}Ready to install:{RESET}")
    print(f"  Modules: {', '.join(selected.keys()) if selected else 'none'}")
    print("  Auth: Configured")
    print(f"  Network: {bind_host}")
    print(f"  Autostart: {autostart_method}")
    print()

    if not args.auto and not ask_yesno("Proceed with installation?", True):
        print(f"\n{YELLOW}Setup cancelled.{RESET}")
        return 0

    dep_ok, dependency_failures = install_deps(selected, installed_deps, auto=args.auto)
    if not dep_ok:
        return 1

    autostart_ok = setup_autostart(autostart_method, bind_host, token)
    if not autostart_ok and not args.auto:
        if not ask_yesno("Continue despite autostart setup failure?", True):
            return 1

    save_config(selected, token, bind_host, autostart_method, dependency_failures)
    launch_coagent(bind_host, token, auto=args.auto)
    print_summary(selected, token, bind_host, autostart_method, dependency_failures)

    print(f"  {BOLD}Need help?{RESET}")
    print(f"    Read: {CYAN}AGENTS.md{RESET}")
    print(f"    GitHub: {CYAN}https://github.com/Predator04/Hermes-CoAgent{RESET}")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Setup cancelled.{RESET}")
        raise SystemExit(0)
    except SetupAbort as exc:
        print(f"\n{YELLOW}{exc}{RESET}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n{RED}Error: {exc}{RESET}")
        raise SystemExit(1)
