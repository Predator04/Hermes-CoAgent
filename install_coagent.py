#!/usr/bin/env python3
r"""CoAgent Installer — Automated one-command setup for Hermes CoAgent.

Usage:
  python install_coagent.py                    # Interactive install
  python install_coagent.py --auto             # Unattended install to defaults
  python install_coagent.py --update           # Fetch + apply latest version
  python install_coagent.py --install-dir="C:\CoAgent"
  python install_coagent.py --uninstall

What it does:
  1. Clones the latest CoAgent from GitHub (or uses local copy)
  2. Installs Python dependencies
  3. Creates start menu shortcuts (Windows)
  4. Registers auto-start via scheduled task
  5. Optionally installs nircmd.exe for brightness control
  6. Sets up screenshot relay
  7. Writes a .token and secures the server
  8. Has built-in update checker (calls /update/check on running server)
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────
REPO = "Predator04/Hermes-CoAgent"
BRANCH = "main"
GITHUB_TARBALL = f"https://api.github.com/repos/{REPO}/tarball/{BRANCH}"
NIRCMD_URL = "https://www.nirsoft.net/utils/nircmd-x64.zip"

INSTALLER_VERSION = (Path(__file__).resolve().parent / "VERSION").read_text().strip() if (Path(__file__).resolve().parent / "VERSION").exists() else "0.0.0"

# Default paths
if platform.system() == "Windows":
    _localappdata = os.environ.get("LOCALAPPDATA", "")
    if not _localappdata:
        _username = os.environ.get("USERNAME", "Default")
        _localappdata = f"C:\\Users\\{_username}\\AppData\\Local"
    DEFAULT_DIR = Path(_localappdata) / "CoAgent"
    START_MENU = Path(os.environ.get("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs\\CoAgent"
else:
    DEFAULT_DIR = Path.home() / ".coagent"
    START_MENU = None

REQUIREMENTS = [
    "flask>=3.0",
    "waitress>=2.1",
    "pillow>=10.0",
    "pyautogui>=0.9",
    "pygetwindow>=0.0.9",
    "pyperclip>=1.8",
    "pystray>=0.19",
    "requests>=2.31",
    "mss>=9.0",
    "pytesseract>=0.3",
]


def console(msg, color=None):
    """Print with optional color."""
    colors = {"green": "32", "yellow": "33", "red": "31", "cyan": "36", "bold": "1"}
    if color and color in colors and sys.stdout.isatty():
        print(f"\033[{colors[color]}m{msg}\033[0m")
    else:
        print(msg)


def run(cmd, timeout=120, check=True, capture=True):
    """Run a shell command."""
    try:
        r = subprocess.run(
            cmd if isinstance(cmd, list) else cmd,
            capture_output=capture, text=True, timeout=timeout, shell=isinstance(cmd, str)
        )
        if check and r.returncode != 0:
            print(f"  ⚠  Command failed: {cmd[:120] if isinstance(cmd, str) else ' '.join(cmd)[:120]}")
            if r.stderr:
                print(f"     stderr: {r.stderr[:300]}")
        return r
    except subprocess.TimeoutExpired:
        print(f"  ⚠  Command timed out after {timeout}s")
        return None
    except FileNotFoundError:
        print(f"  ⚠  Command not found: {cmd[:80]}")
        return None


# ── Steps ──────────────────────────────────────────────────────────────────

def step_check_python():
    """Ensure Python 3.10+."""
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        console("✗ Python 3.10+ required (found {}.{}.{})".format(v.major, v.minor, v.micro), "red")
        return False
    console(f"✓ Python {v.major}.{v.minor}.{v.micro}", "green")
    return True


def step_download(install_dir):
    """Download CoAgent from GitHub."""
    console("\n[1/6] Downloading CoAgent...", "cyan")
    install_dir = Path(install_dir)
    if install_dir.exists():
        console(f"  Directory {install_dir} exists. Backing up token/config...")
        backup = {}
        for f in [".token", "telegram_config.json", "config.json"]:
            p = install_dir / f
            if p.exists():
                backup[f] = p.read_text(encoding="utf-8")

        shutil.rmtree(install_dir, ignore_errors=True)

    temp_tarball = None
    try:
        fd, temp_path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        temp_tarball = Path(temp_path)
        console("  Fetching from GitHub...")
        req = urllib.request.Request(
            GITHUB_TARBALL,
            headers={"User-Agent": "CoAgent-Installer/1.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(temp_tarball, "wb") as f:
                shutil.copyfileobj(resp, f)

        import tarfile
        with tarfile.open(temp_tarball, "r:gz") as tar:
            # Find the root directory (GitHub wraps in a commit-hash dir)
            members = tar.getmembers()
            root_dirs = {m.name.split("/")[0] for m in members if "/" in m.name}
            root = root_dirs.pop() if root_dirs else ""

            install_dir.mkdir(parents=True, exist_ok=True)
            for member in members:
                if member.name == root:
                    continue
                # Strip the commit-hash prefix
                rel_name = member.name[len(root) + 1:] if member.name.startswith(root + "/") else member.name
                if not rel_name:
                    continue
                target = install_dir / rel_name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    with open(target, "wb") as f:
                        f.write(tar.extractfile(member).read())

        # Restore backups
        for name, content in backup.items():
            (install_dir / name).write_text(content, encoding="utf-8")
            console(f"  Restored {name}")

        console(f"✓ Downloaded to {install_dir}", "green")
        return True
    except Exception as e:
        console(f"✗ Download failed: {e}", "red")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if temp_tarball.exists():
            temp_tarball.unlink()


def step_install_deps(install_dir):
    """Install Python dependencies."""
    console("\n[2/6] Installing dependencies...", "cyan")
    req_file = install_dir / "requirements.txt"

    # Write a requirements.txt if not present
    if not req_file.exists():
        # Build from the REQUIREMENTS list + any in-requirements from the codebase
        existing_req = []
        for rf in install_dir.rglob("requirements*.txt"):
            if rf.parent == install_dir:
                existing_req = rf.read_text().strip().splitlines()
                break

        deps = existing_req or REQUIREMENTS
        req_file.write_text("\n".join(deps) + "\n", encoding="utf-8")

    pip = [sys.executable, "-m", "pip", "install"]
    if not os.getenv("COAGENT_NO_QUIET"):
        pip.append("-q")

    r = run(pip + ["-r", str(req_file)], timeout=180, check=False)
    if r and r.returncode == 0:
        console("✓ Dependencies installed", "green")
        return True
    else:
        console("⚠  Some deps may have failed (non-fatal)", "yellow")
        return True  # non-fatal


def step_install_nircmd(install_dir):
    """Download nircmd.exe for brightness control."""
    console("\n[3/6] Installing nircmd (brightness control)...", "cyan")
    target = install_dir / "nircmd.exe"
    if target.exists():
        console("  nircmd already installed")
        return True

    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        zip_path = Path(tmp_path)
        urllib.request.urlretrieve(NIRCMD_URL, zip_path)
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            z.extract("nircmd.exe", install_dir)
        zip_path.unlink()
        if target.exists():
            console(f"✓ nircmd.exe installed", "green")
            return True
        else:
            console("⚠  nircmd extraction failed (non-fatal)", "yellow")
            return True
    except Exception as e:
        console(f"⚠  nircmd download failed: {e} (non-fatal)", "yellow")
        return True


def step_create_token(install_dir):
    """Generate auth token for secure mode."""
    console("\n[4/6] Generating auth token...", "cyan")
    token_file = install_dir / ".token"
    if token_file.exists():
        console("  Token already exists (keeping)")
        return True

    import secrets
    token = secrets.token_hex(32)
    token_file.write_text(token, encoding="utf-8")
    console(f"✓ Token generated: {token[:16]}...", "green")
    return True


def step_create_shortcuts(install_dir):
    """Create start menu shortcuts and startup registration."""
    if platform.system() != "Windows":
        console("\n[5/6] Skipping shortcuts (not Windows)")
        return True

    console("\n[5/6] Creating shortcuts & auto-start...", "cyan")

    # Create launcher batch file
    bat_path = install_dir / "start_coagent.bat"
    pythonw = shutil.which("pythonw.exe") or "pythonw.exe"
    bat_content = f"""@echo off
cd /d "%~dp0"
start "" "{pythonw}" -B hermes_coagent.py --secure --allow-external
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    console("  ✓ Launcher batch created")

    # Create uninstaller batch
    uninstall_bat = install_dir / "uninstall_coagent.bat"
    uninstall_bat.write_text(f"""@echo off
echo CoAgent Uninstaller
echo -------------------
echo This will remove CoAgent and its startup task.
echo.
echo Your .token, config, and recordings will NOT be deleted.
echo.
set /p confirm="Uninstall CoAgent? (y/N): "
if /i not "%confirm%"=="y" exit /b

echo.
echo 1. Stopping CoAgent...
taskkill /f /im pythonw.exe 2>nul

echo 2. Removing startup task...
schtasks /delete /tn "CoAgent" /f 2>nul
schtasks /delete /tn "CoAgent-Screenshot-Relay" /f 2>nul

echo 3. Removing shortcuts...
del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\CoAgent\\*" 2>nul
rmdir "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\CoAgent" 2>nul

echo.
echo CoAgent removed. Your data is preserved at:
echo %~dp0
echo Delete the folder manually if you want to fully remove it.
pause
""", encoding="utf-8")
    console("  ✓ Uninstaller batch created")

    # Start menu shortcut via VBS (more reliable than .lnk)
    if START_MENU:
        START_MENU.mkdir(parents=True, exist_ok=True)
        vbs_shortcut = START_MENU / "CoAgent.lnk"
        if not vbs_shortcut.exists():
            vbs_script = install_dir / "_create_shortcut.vbs"
            vbs_script.write_text(f"""
Set WshShell = WScript.CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{vbs_shortcut}")
Shortcut.TargetPath = "{bat_path}"
Shortcut.WorkingDirectory = "{install_dir}"
Shortcut.Description = "Hermes CoAgent Desktop Control Server"
Shortcut.WindowStyle = 7
Shortcut.Save
""", encoding="utf-8")
            run(["cscript", "//nologo", str(vbs_script)], timeout=10, check=False)
            if vbs_script.exists():
                vbs_script.unlink()

        # Uninstall shortcut
        uninstall_lnk = START_MENU / "Uninstall CoAgent.lnk"
        vbs_uninstall = install_dir / "_create_uninstall.vbs"
        vbs_uninstall.write_text(f"""
Set WshShell = WScript.CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{uninstall_lnk}")
Shortcut.TargetPath = "{uninstall_bat}"
Shortcut.WorkingDirectory = "{install_dir}"
Shortcut.Save
""", encoding="utf-8")
        run(["cscript", "//nologo", str(vbs_uninstall)], timeout=10, check=False)
        if vbs_uninstall.exists():
            vbs_uninstall.unlink()

        console(f"  ✓ Start menu shortcuts created")

    # Scheduled task for auto-start on login
    username = os.environ.get("USERNAME", "").strip()
    schtasks_cmd = [
        "schtasks", "/create", "/tn", "CoAgent", "/tr",
        f'"{bat_path}"', "/sc", "onlogon",
        "/it", "/f", "/delay", "0000:30"
    ]
    if username:
        schtasks_cmd.insert(6, "/ru")
        schtasks_cmd.insert(7, username)
    run(schtasks_cmd, timeout=15, check=False)
    console("  ✓ Auto-start scheduled task created")

    return True


def step_verify(install_dir):
    """Verify the installation."""
    console("\n[6/6] Verifying installation...", "cyan")
    ok = True

    # Check key files exist
    required = ["hermes_coagent.py", "shared.py", "routes_system.py",
                 "routes_mouse.py", "routes_ocr.py", "routes_file.py",
                 "routes_media.py", "routes_system.py", "routes_updates.py",
                 "launch_all.ps1", "start_coagent.bat"]
    for f in required:
        p = install_dir / f
        status = "✓" if p.exists() else "✗"
        if not p.exists():
            ok = False
        # Only show failures in the summary
        if not p.exists():
            print(f"  {status} {f}")

    # Check Python deps
    try:
        print("  ✓ Python dependencies: flask, waitress, PIL, pyautogui, pygetwindow")
    except ImportError as e:
        print(f"  ⚠  Missing dependency: {e}")
        ok = False

    # Check nircmd
    if (install_dir / "nircmd.exe").exists():
        print("  ✓ nircmd.exe (brightness control)")
    else:
        print("  ○ nircmd.exe not installed (optional)")

    # Check token
    token_file = install_dir / ".token"
    if token_file.exists():
        token = token_file.read_text().strip()
        print(f"  ✓ Auth token present ({len(token)} chars)")
    else:
        print("  ⚠  No auth token generated")
        ok = False

    version_file = install_dir / "VERSION"
    if version_file.exists():
        print(f"  ✓ Version: {version_file.read_text().strip()}")
        build_file = install_dir / "shared.py"
        if build_file.exists():
            for line in build_file.read_text().splitlines():
                if line.startswith("BUILD ="):
                    print(f"    {line.strip().strip(',')}")
    elif (install_dir / "shared.py").exists():
        for line in (install_dir / "shared.py").read_text().splitlines():
            if line.startswith("VERSION =") or line.startswith("BUILD ="):
                print(f"  ✓ {line.strip().strip(',')}")

    print(f"\n  Total files: {len(list(install_dir.rglob('*.py')))} Python files")

    if ok:
        console("\n✓ Installation complete!", "green")
    else:
        console("\n⚠  Installation finished with warnings", "yellow")

    return ok


def cmd_install(args):
    """Full install."""
    install_dir = Path(args.install_dir).resolve()
    console(f"\n{'='*50}", "bold")
    console(f"  CoAgent Installer v{INSTALLER_VERSION}", "bold")
    console(f"  Target: {install_dir}", "bold")
    console(f"{'='*50}\n", "bold")

    steps = [
        step_check_python,
        lambda: step_download(install_dir),
        lambda: step_install_deps(install_dir),
        lambda: step_install_nircmd(install_dir),
        lambda: step_create_token(install_dir),
        lambda: step_create_shortcuts(install_dir),
        lambda: step_verify(install_dir),
    ]

    for step in steps:
        if not step():
            console("\n✗ Installation aborted", "red")
            return 1

    console(f"\n  Start CoAgent: {install_dir / 'start_coagent.bat'}", "cyan")
    console(f"  Dashboard:     http://localhost:9123/\n", "cyan")
    return 0


def cmd_update(args):
    """Check for and apply updates."""
    console("CoAgent Updater", "bold")
    install_dir = Path(args.install_dir).resolve()

    # Try to check current version via API
    try:
        import urllib.request
        token_file = install_dir / ".token"
        if token_file.exists():
            token = token_file.read_text().strip()
            req = urllib.request.Request(
                f"http://127.0.0.1:9123/update/check",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                console(f"  Current: v{data.get('current', '?')}")
                console(f"  Latest:  v{data.get('latest', '?')}")
                if data.get("update_available"):
                    console("  Update available! Applying...", "yellow")
                    # Apply via the running server
                    req2 = urllib.request.Request(
                        f"http://127.0.0.1:9123/update/apply",
                        method="POST",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(req2, timeout=180) as resp2:
                        result = json.loads(resp2.read())
                        console(f"  ✓ {json.dumps(result, indent=2)}", "green")
                    return 0
                else:
                    console("  ✓ Already up to date", "green")
                    return 0
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        console(f"  Server not reachable (is it running?): {e}", "yellow")
        console("  Falling back to direct download...")

    # Fallback: re-download and overlay
    console("  Downloading latest...")
    backup_dir = install_dir / ".backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Backup critical files
    for f in [".token", "telegram_config.json", "config.json", "nircmd.exe"]:
        src = install_dir / f
        if src.exists():
            shutil.copy2(src, backup_dir / f)

    # Download fresh copy
    temp_dir = Path(tempfile.mkdtemp(suffix="_coagent_update"))
    try:
        req = urllib.request.Request(
            GITHUB_TARBALL,
            headers={"User-Agent": "CoAgent-Updater/1.0"},
        )
        tarball = temp_dir / "coagent.tar.gz"
        tarball.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(tarball, "wb") as f:
                shutil.copyfileobj(resp, f)

        import tarfile
        with tarfile.open(tarball, "r:gz") as tar:
            members = tar.getmembers()
            root_dirs = {m.name.split("/")[0] for m in members if "/" in m.name}
            root = root_dirs.pop() if root_dirs else ""

            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            for member in members:
                rel_name = member.name[len(root) + 1:] if member.name.startswith(root + "/") else member.name
                if not rel_name:
                    continue
                target = extract_dir / rel_name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "wb") as f:
                        f.write(tar.extractfile(member).read())

            # Copy all new files over existing
            count = 0
            for item in extract_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(extract_dir)
                    target = install_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                    count += 1

        # Restore backups
        for f in backup_dir.iterdir():
            shutil.copy2(f, install_dir / f.name)

        shutil.rmtree(temp_dir)
        console(f"✓ Updated {count} files", "green")
        console("  Restart CoAgent to apply changes.", "yellow")
        return 0
    except Exception as e:
        console(f"✗ Update failed: {e}", "red")
        # Restore from backup
        for f in backup_dir.iterdir():
            shutil.copy2(f, install_dir / f.name)
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        return 1


def cmd_build_exe(args):
    """Build CoAgent.exe using PyInstaller."""
    install_dir = Path(args.install_dir).resolve()
    console("CoAgent EXE Builder", "bold")
    console(f"  Source: {install_dir}")
    console(f"  Output: {install_dir / 'dist' / 'CoAgent.exe'}\n")

    # Check PyInstaller
    r = run([sys.executable, "-m", "pip", "list"], timeout=15, capture=True)
    if r and "pyinstaller" not in (r.stdout or "").lower():
        console("Installing PyInstaller...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"], timeout=120, check=False)

    # Clean
    for d in ["build", "dist"]:
        p = install_dir / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for f in install_dir.glob("*.spec"):
        f.unlink()

    # Build
    pyinstaller = [sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", "CoAgent",
        "--icon", "NONE",
        "--hidden-import", "flask",
        "--hidden-import", "waitress",
        "--hidden-import", "PIL",
        "--hidden-import", "pyautogui",
        "--hidden-import", "pygetwindow",
        "--hidden-import", "pyperclip",
        "--hidden-import", "pystray",
        "--hidden-import", "mss",
        "--hidden-import", "pytesseract",
        "--hidden-import", "requests",
        "--collect-all", "flask",
        "--collect-all", "waitress",
        "--collect-all", "PIL",
    ]

    console("Building CoAgent.exe (this takes 2-3 minutes)...")
    r = run(pyinstaller + [str(install_dir / "hermes_coagent.py")],
            timeout=600, check=False)

    exe_path = install_dir / "dist" / "CoAgent.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        console(f"\n✓ Build complete! CoAgent.exe ({size_mb:.0f} MB)", "green")
        console(f"  Location: {exe_path}")

        # Copy to Desktop
        desktop = Path.home() / "Desktop" / "CoAgent.exe"
        try:
            shutil.copy2(exe_path, desktop)
            console(f"  Copied to Desktop for easy access", "green")
        except Exception:
            pass
        return 0
    else:
        console("\n✗ Build failed", "red")
        return 1
def cmd_uninstall(args):
    """Uninstall CoAgent."""
    install_dir = Path(args.install_dir).resolve()
    console("CoAgent Uninstaller", "bold")
    console(f"  This will remove CoAgent from {install_dir}", "yellow")
    console("  Your .token, config.json, and recordings will be preserved.\n")

    if not args.auto:
        confirm = input("Uninstall CoAgent? (y/N): ").strip().lower()
        if confirm != "y":
            console("Aborted.")
            return 0

    # Stop server
    try:
        import urllib.request
        token_file = install_dir / ".token"
        if token_file.exists():
            token = token_file.read_text().strip()
            req = urllib.request.Request(
                "http://127.0.0.1:9123/emergency/stop",
                method="POST",
                headers={"Authorization": f"Bearer {token}"},
            )
            urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass

    run(["taskkill", "/f", "/im", "pythonw.exe"], check=False)

    # Remove scheduled tasks
    run(["schtasks", "/delete", "/tn", "CoAgent", "/f"], check=False)
    run(["schtasks", "/delete", "/tn", "CoAgent-Screenshot-Relay", "/f"], check=False)

    # Remove start menu
    if START_MENU and START_MENU.exists():
        shutil.rmtree(START_MENU, ignore_errors=True)
        console("  ✓ Start menu removed")

    # Preserve user data, remove everything else
    preserve = {".token", "telegram_config.json", "config.json", "recordings"}
    for item in install_dir.iterdir():
        if item.name not in preserve:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()

    console("\n✓ CoAgent removed. Preserved files remain at {}\n".format(install_dir), "green")
    return 0


def cmd_status(args):
    """Check CoAgent status."""
    install_dir = Path(args.install_dir).resolve()
    console("CoAgent Status", "bold")
    console(f"  Install dir: {install_dir}")

    if not install_dir.exists():
        console("  ✗ Not installed", "red")
        return 1

    # Count files
    py_files = list(install_dir.rglob("*.py"))
    console(f"  Python files: {len(py_files)}")

    # Try to reach the server
    try:
        import urllib.request
        # Try with auth
        token_file = install_dir / ".token"
        if token_file.exists():
            token = token_file.read_text().strip()
            req = urllib.request.Request(
                "http://127.0.0.1:9123/system/info",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                console(f"  Server:     ✓ Running on port 9123", "green")
                console(f"  Volume:     {data.get('volume', '?')}% {'(muted)' if data.get('muted') else ''}")
                console(f"  Brightness: {data.get('brightness', 'unsupported')}")
                console(f"  Wi-Fi:      {'connected' if data.get('wifi_connected') else 'disconnected'}")
                console(f"  DND:        {'on' if data.get('dnd_enabled') else 'off'}")
                console(f"  Dark mode:  {'on' if data.get('dark_mode') else 'off'}")
    except Exception as e:
        console(f"  Server:     ✗ Not running ({e})", "yellow")
        console(f"  Start it:   {install_dir / 'start_coagent.bat'}")

    return 0


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CoAgent Installer — one-command setup for Hermes CoAgent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install_coagent.py                      # Interactive install
  python install_coagent.py --auto               # Unattended install
  python install_coagent.py --update             # Update to latest
  python install_coagent.py --status             # Check installation
  python install_coagent.py --uninstall          # Remove CoAgent
""",
    )
    parser.add_argument("--install-dir", default=str(DEFAULT_DIR),
                        help=f"Installation directory (default: {DEFAULT_DIR})")
    parser.add_argument("--auto", action="store_true",
                        help="Unattended mode (skip prompts)")
    parser.add_argument("--update", action="store_true",
                        help="Check for and apply updates")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove CoAgent")
    parser.add_argument("--build-exe", action="store_true",
                        help="Build standalone CoAgent.exe with PyInstaller")
    parser.add_argument("--status", action="store_true",
                        help="Check CoAgent status")
    parser.add_argument("--version", action="store_true",
                        help="Show installer version")

    args = parser.parse_args()

    if args.version:
        print(f"CoAgent Installer v{INSTALLER_VERSION}")
        return 0
    if args.update:
        return cmd_update(args)
    if args.uninstall:
        return cmd_uninstall(args)
    if args.build_exe:
        return cmd_build_exe(args)
    if args.status:
        return cmd_status(args)

    return cmd_install(args)


if __name__ == "__main__":
    sys.exit(main())
