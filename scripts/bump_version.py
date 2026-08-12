#!/usr/bin/env python3
"""Bump the CoAgent version number across the entire project.

Usage:
  python bump_version.py [major|minor|patch]
  python bump_version.py 8.51          # set exact version
  python bump_version.py               # show current version
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # scripts/ → repo root
VERSION_FILE = ROOT / "VERSION"

FILES_TO_CHECK = [
    "README.md",
    "AGENTS.md",
    "routes_help.py",
    "telemetry.py",
    "coagent_installer.nsi",
    "dashboard.html",
]


def get_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return "0.0.0"


def bump_version(current: str, part: str) -> str:
    # Strip prerelease/build metadata (e.g. "8.53.11-beta.1" → "8.53.11")
    clean = current.split("-")[0].split("+")[0]
    try:
        parts = [int(x) for x in clean.split(".")]
    except ValueError:
        print(f"ERROR: VERSION file contains non-numeric version: '{current}'", file=sys.stderr)
        raise SystemExit(1)
    # Normalize to 3-part semver
    while len(parts) < 3:
        parts.append(0)
    if part == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif part == "minor":
        parts[1] += 1
        parts[2] = 0
    elif part == "patch":
        parts[2] += 1
    else:
        return part  # exact version string
    return ".".join(str(p) for p in parts)


def main():
    current = get_version()
    
    if len(sys.argv) < 2:
        print(f"Current version: {current}")
        print(f"Usage: {sys.argv[0]} [major|minor|patch|X.Y.Z]")
        return
    
    new_version = bump_version(current, sys.argv[1])
    
    if new_version == current:
        print(f"Version unchanged: {current}")
        return
    
    # Write new version
    VERSION_FILE.write_text(new_version + "\n")
    print(f"Bumped: {current} → {new_version}")
    print(f"Updated: {VERSION_FILE}")
    
    # Check for stale references in other files
    print("\nFiles with hardcoded version references (may need manual update):")
    for fname in FILES_TO_CHECK:
        fpath = ROOT / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8", errors="replace")
            if current in content:
                print(f"  {fname} — contains '{current}'")
    
    print("\nDone. Commit the VERSION file change.")


if __name__ == "__main__":
    main()
