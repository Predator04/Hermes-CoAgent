"""Transparent stdio bridge for cua-driver MCP from WSL/Hermes.

Launches the Windows cua-driver MCP server without --no-daemon-relaunch and
copies stdin/stdout/stderr as bytes. This keeps MCP stdout clean while avoiding
PowerShell/batch script stdin handling quirks.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
from pathlib import Path


DEFAULT_CUA_EXE = Path(
    os.environ.get("USERPROFILE") or os.environ.get("HOME") or "C:\\Users\\Default",
    "AppData/Local/Programs/Cua/cua-driver/bin/cua-driver.exe",
)


def resolve_cua_exe(configured: str | None) -> str:
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
        raise FileNotFoundError(f"configured cua-driver.exe not found: {path}")

    if DEFAULT_CUA_EXE.is_file():
        return str(DEFAULT_CUA_EXE)

    found = shutil.which("cua-driver.exe") or shutil.which("cua-driver")
    if found:
        return found

    raise FileNotFoundError(
        f"cua-driver.exe not found at {DEFAULT_CUA_EXE} or on PATH"
    )


def copy_stream(src, dst, *, close_dst: bool = False) -> None:
    try:
        while True:
            chunk = src.readline()
            if not chunk:
                break
            dst.write(chunk)
            dst.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        if close_dst:
            try:
                dst.close()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge Hermes stdio to cua-driver MCP")
    parser.add_argument("--cua-exe", help="Absolute path to cua-driver.exe")
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="Enable cua-driver's cursor overlay. The default disables it.",
    )
    args = parser.parse_args()

    try:
        cua_exe = resolve_cua_exe(args.cua_exe)
    except FileNotFoundError as exc:
        print(f"cua_mcp_bridge: {exc}", file=sys.stderr, flush=True)
        return 127

    cmd = [cua_exe, "mcp"]
    if not args.overlay:
        cmd.append("--no-overlay")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    threads = [
        threading.Thread(
            target=copy_stream,
            args=(sys.stdin.buffer, proc.stdin),
            kwargs={"close_dst": True},
            daemon=True,
        ),
        threading.Thread(
            target=copy_stream,
            args=(proc.stdout, sys.stdout.buffer),
            daemon=True,
        ),
        threading.Thread(
            target=copy_stream,
            args=(proc.stderr, sys.stderr.buffer),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
