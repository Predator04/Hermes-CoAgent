"""
Build the Hermes CoAgent tray icon as a standalone Windows EXE.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_EXE = ROOT / "dist" / "CoAgentTray.exe"
DESKTOP_EXE = Path.home() / "Desktop" / "CoAgentTray.exe"
BUILD_DIR = ROOT / "build" / "CoAgentTray"
SPEC_FILE = ROOT / "CoAgentTray.spec"


def _run(cmd: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def _stop_existing_tray() -> None:
    subprocess.run(
        ["taskkill", "/IM", "CoAgentTray.exe", "/F"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    time.sleep(1)


def main() -> int:
    _stop_existing_tray()
    _run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "pyinstaller",
        "pystray",
        "pillow",
    ])

    _run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "CoAgentTray",
        "--icon",
        "NONE",
        "--noconfirm",
        "tray_icon.py",
    ])

    if not DIST_EXE.exists():
        raise FileNotFoundError(f"Expected build output not found: {DIST_EXE}")

    _stop_existing_tray()
    DESKTOP_EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DIST_EXE, DESKTOP_EXE)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()
    parent_build = BUILD_DIR.parent
    if parent_build.exists() and not any(parent_build.iterdir()):
        parent_build.rmdir()
    print(f"Built: {DIST_EXE}")
    print(f"Copied: {DESKTOP_EXE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
