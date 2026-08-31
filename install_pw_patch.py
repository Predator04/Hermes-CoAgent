"""CoAgent Playwright asyncio patch installer.

Fixes: "Playwright Sync API inside the asyncio loop" error by
patching playwright.sync_api._context_manager to skip the check.

Usage: python install_pw_patch.py
        or: python install_pw_patch.py --revert (undo the patch)
"""
import shutil
import os
import re
import sys
import site


def find_context_manager():
    """Find playwright's _context_manager.py across all site-packages dirs."""
    for sp in site.getsitepackages():
        path = os.path.join(sp, "playwright", "sync_api", "_context_manager.py")
        if os.path.exists(path):
            return path
    # Fallback: check common locations
    try:
        import playwright
    except ImportError as e:
        raise FileNotFoundError("Playwright is not installed") from e
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

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "Patched by CoAgent" in content:
        print("  Already patched.")
        return

    if PATCH_OLD in content:
        content = content.replace(PATCH_OLD, PATCH_NEW)
    else:
        print("  WARNING: Expected code not found. Playwright may have changed.")
        print("  Trying alternative pattern...")
        # Match the WHOLE `raise Error(...)` statement (whatever the message),
        # anchored to the `if self._loop.is_running():` guard so we can never
        # match an unrelated `raise Error(...)` elsewhere in the file. Replace
        # the guard body with `pass` so we never leave a dangling string
        # literal or closing paren behind (which previously produced a
        # SyntaxError).
        alt_re = re.compile(
            r"(if self\._loop\.is_running\(\):\s*)raise Error\(.*?\)\n",
            re.DOTALL,
        )
        if alt_re.search(content):
            content = alt_re.sub(r"\1pass  # Patched by CoAgent\n", content, count=1)
        else:
            print("  Could not patch. Please manually edit:")
            print(f"  {filepath}")
            return

    tmp_path = filepath + ".coagent_tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)
    except PermissionError:
        print("  ERROR: permission denied - re-run as administrator or from the correct venv.")
        print(f"  {filepath}")
        sys.exit(1)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
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
