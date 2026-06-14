#!/usr/bin/env python3
"""Hermes CoAgent v3 — One-Click Installer for Windows
Usage: python install.py
"""
import sys, os, subprocess, platform, urllib.request, shutil, ctypes, json

COAGENT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "Hermes CoAgent")
PORT = 9123

DEPS = ["pyautogui", "pillow", "pynput", "mss", "flask", "pygetwindow",
        "pyperclip", "pytesseract", "opencv-python", "edge-tts", "psutil"]

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

def print_banner():
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     Hermes CoAgent v3 Installer          ║")
    print("  ║  Ultimate Desktop Co-Pilot for Windows   ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

def check_python():
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required: python.org/downloads")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")

def install_deps():
    print("\n[1/3] Installing dependencies...")
    for dep in DEPS:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", dep], capture_output=True)
    print("✅ Dependencies installed")

def setup_files():
    print("\n[2/3] Setting up files...")
    os.makedirs(COAGENT_DIR, exist_ok=True)
    os.makedirs(os.path.join(COAGENT_DIR, "macros"), exist_ok=True)
    os.makedirs(os.path.join(COAGENT_DIR, "screenshots"), exist_ok=True)

    # Create start.bat
    with open(os.path.join(COAGENT_DIR, "start.bat"), "w") as f:
        f.write(f"""@echo off
title Hermes CoAgent v3
cd /d "%~dp0"
echo ========================================
echo   Hermes CoAgent v3 - Desktop Co-Pilot
echo ========================================
echo.
start http://localhost:{PORT}
python hermes_coagent.py {PORT}
pause
""")

    # Create VBS for hidden start
    with open(os.path.join(COAGENT_DIR, "start_hidden.vbs"), "w") as f:
        f.write(f"""
CreateObject("Wscript.Shell").Run "cmd /c cd /d `"{COAGENT_DIR}`" ^&^& python hermes_coagent.py {PORT}", 0, False
""")

    print(f"✅ Files set up in: {COAGENT_DIR}")

def start_server():
    print("\n[3/3] Starting server...")
    server_path = os.path.join(COAGENT_DIR, "hermes_coagent.py")
    if not os.path.exists(server_path):
        print("❌ Server file missing. Place hermes_coagent.py in the folder first.")
        return False

    # Kill existing
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "Get-Process -Name python* -ErrorAction SilentlyContinue | "
         "Stop-Process -Force -ErrorAction SilentlyContinue"],
        capture_output=True, timeout=10
    )

    # Start
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.Popen(
        [sys.executable, server_path, str(PORT)],
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    print(f"✅ Server started on http://localhost:{PORT}/")
    return True

def print_usage():
    print()
    print("  ──────────────────────────────────────────")
    print("   Hermes CoAgent v3 is RUNNING")
    print("  ──────────────────────────────────────────")
    print()
    print("  📍 Dashboard:  http://localhost:9123/")
    print("  📸 Screen:     http://localhost:9123/screen")
    print("  🔍 OCR:        POST /ocr/find")
    print("  🎯 Macros:     POST /macro/record + F9 to stop")
    print("  🛑 Emergency:  POST /emergency/stop")
    print("            or  Ctrl+Alt+Shift (keyboard shortcut)")
    print("  🌐 Tunnel:     POST /tunnel/start (requires cloudflared)")
    print("  🖱  CoPilot:   150ms cooldown, fire-and-forget")
    print()
    print("  Files: Desktop\\Hermes CoAgent\\")
    print("  Run start.bat anytime to restart.")
    print()

if __name__ == "__main__":
    if platform.system() != "Windows":
        print("Windows only.")
        sys.exit(1)
    print_banner()
    check_python()
    install_deps()
    setup_files()
    started = start_server()
    if started:
        print_usage()
    else:
        os.startfile(COAGENT_DIR)
