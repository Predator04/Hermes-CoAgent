"""CoAgent Playwright asyncio patch installer.

Fixes: "Playwright Sync API inside the asyncio loop" error by
patching playwright.sync_api._context_manager to skip the check.

Usage: python install_pw_patch.py
        or: python install_pw_patch.py --revert (undo the patch)
"""
import shutil
import os
import sys
import site


def find_context_manager():
    """Find playwright's _context_manager.py across all site-packages dirs."""
    for sp in site.getsitepackages():
        path = os.path.join(sp, "playwright", "sync_api", "_context_manager.py")
        if os.path.exists(path):
            return path
    # Fallback: check common locations
    import playwright
    base = os.path.dirname(playwright.__file__)
    path = os.path.join(base, "sync_api", "_context_manager.py")
    if os.path.exists(path):
        return path
    raise FileNotFoundError("Could not find playwright _context_manager.py")


PATCH_OLD = """        if self._loop.is_running():
            raise Error(
                \"\"\"It looks like you are using Playwright Sync API inside the asyncio loop.
Please use the Async API instead.\"\"\"
            )"""

PATCH_NEW = """        # Patched by CoAgent — skip asyncio loop check
        if self._loop.is_running():
            pass  # nest_asyncio handles this"""


def apply_patch(filepath):
    backup = filepath + ".coagent_backup"
    if not os.path.exists(backup):
        shutil.copy2(filepath, backup)
        print(f"  Backup: {backup}")

    with open(filepath, "r") as f:
        content = f.read()

    if "Patched by CoAgent" in content:
        print("  Already patched.")
        return

    if PATCH_OLD not in content:
        print("  WARNING: Expected code not found. Playwright may have changed.")
        print("  Trying alternative pattern...")
        # Try a simpler match using a triple-quoted string with real newlines
        alt_old = """        if self._loop.is_running():
            raise Error("""
        if alt_old in content:
            print("  Found alternative pattern, attempting replacement...")
            alt_new = """        if self._loop.is_running():
            pass  # Patched by CoAgent"""
            content = content.replace(alt_old, alt_new)
        else:
            print("  Could not patch. Please manually edit:")
            print(f"  {filepath}")
            return

    content = content.replace(PATCH_OLD, PATCH_NEW)
    with open(filepath, "w") as f:
        f.write(content)
    print("  Patched successfully.")


def revert_patch(filepath):
    backup = filepath + ".coagent_backup"
    if not os.path.exists(backup):
        print("  No backup found. Nothing to revert.")
        return
    shutil.copy2(backup, filepath)
    print(f"  Reverted from {backup}")


def main():
    revert = "--revert" in sys.argv

    try:
        path = find_context_manager()
        print(f"Found: {path}")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if revert:
        revert_patch(path)
    else:
        apply_patch(path)


if __name__ == "__main__":
    main()
