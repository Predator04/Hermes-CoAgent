Audit and improve the setup_wizard.py at C:\Users\Admin\Desktop\Hermes CoAgent\setup_wizard.py

## Audit
Read setup_wizard.py thoroughly and find:
1. Any bugs, edge cases, or crashes
2. Missing error handling
3. Windows-specific issues (path quoting, encoding, permissions)
4. Any dead code or unused imports
5. Places where the wizard could fail silently

## Improvements to Add

### 1. Dependency scanning (detect what's already installed)
Add a function `scan_installed_deps()` that runs:
```python
pip list --format=json
```
Then parses the JSON to check which module deps are already installed. During module selection, show:
```
  ┌─────────────────────────────────────────────┐
  │  GPU Screenshots (DXCam)      Size: ~2MB    │
  │  Already installed ✓                        │
  │  240fps GPU-accelerated screen capture      │
  └─────────────────────────────────────────────┘
```

### 2. Auto-download missing packages
The install function should auto-install missing deps without asking "Install now?" — just do it.
Show progress with a spinner or dots.

### 3. Fix any issues found in the audit
Be thorough. Find and fix everything.

### 4. Add --auto mode
CLI flag `--auto` that skips all prompts and uses smart defaults:
- Detect Windows/Python
- Install all modules (skip ones that fail)
- Auto-generate random token
- localhost only
- No autostart
- Launch immediately

### 5. Improve error messages
If a pip install fails, show the actual error AND suggest next steps.

After making ALL changes, run:
```
python setup_wizard.py --help
```
to verify it doesn't crash, then run:
```
python -c "import py_compile; py_compile.compile('setup_wizard.py', doraise=True)"
```
to verify the file compiles.

Do NOT stop until all improvements are applied and verified.
