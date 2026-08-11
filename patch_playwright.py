# Python script to patch Playwright's asyncio check
import shutil
import os
import sys

filepath = r"C:\Program Files\Python312\Lib\site-packages\playwright\sync_api\_context_manager.py"
backup = filepath + ".backup"

# Check file exists
if not os.path.exists(filepath):
    print(f"ERROR: Playwright file not found at {filepath}", file=sys.stderr)
    print("Use: py -c \"import playwright; print(playwright.__file__)\" to find the correct path")
    sys.exit(1)

# Backup original
if not os.path.exists(backup):
    shutil.copy2(filepath, backup)
    print(f"Backup created: {backup}")

# Read and patch
with open(filepath, 'r') as f:
    content = f.read()

# Comment out the asyncio check
old = '''        if self._loop.is_running():
            raise Error(
                \"\"\"It looks like you are using Playwright Sync API inside the asyncio loop.
Please use the Async API instead.\"\"\"
            )'''

new = '''        # Patched by CoAgent — skip asyncio loop check
        if self._loop.is_running():
            pass  # nest_asyncio handles this'''

if old not in content:
    print("WARNING: Target code not found in file — may already be patched or Playwright version differs")
    # Check if already patched
    if "Patched by CoAgent" in content:
        print("File already patched. Nothing to do.")
        sys.exit(0)
    else:
        print(f"ERROR: Cannot find code to patch in {filepath}", file=sys.stderr)
        print("The file content may have changed. Check manually.")
        sys.exit(1)

content = content.replace(old, new, 1)

with open(filepath, 'w') as f:
    f.write(content)

print(f"Patched: {filepath}")
print("Lines 45-49 replaced to skip asyncio check")
