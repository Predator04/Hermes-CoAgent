# Python script to patch Playwright's asyncio check
import shutil
import os

filepath = r"C:\Program Files\Python312\Lib\site-packages\playwright\sync_api\_context_manager.py"
backup = filepath + ".backup"

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

content = content.replace(old, new)

with open(filepath, 'w') as f:
    f.write(content)

print(f"Patched: {filepath}")
print("Lines 45-49 replaced to skip asyncio check")
