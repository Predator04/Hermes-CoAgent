You have full access to the CoAgent codebase at `C:\Users\Admin\Desktop\Hermes CoAgent\`. Perform a comprehensive security fix pass based on the findings in `CODEX_AUDIT_REPORT.md`. Do NOT modify `CODEX_AUDIT_REPORT.md` itself. Fix the actual source files.

## Priority Order

### P0: Fix auth startup (hermes_coagent.py)
- `--token=KEY` detection currently uses `"--token" in sys.argv` which never matches `--token=KEY`. Fix to use `any(a.startswith("--token") for a in sys.argv)`
- `--allow-external` without `--secure` or `--token=KEY` must refuse to start
- Import `AUTH_ENABLED` from auth module to verify auth is actually active
- Call `_init_auth()` even when no flags passed (to show the warning message)

### P0: Protect all sensitive routes
Read every route file and add `@require_auth` where missing:
- **routes_ocr.py**: `/screen`, `/screen/jpeg`, `/screen/base64`, `/screen/fresh`, `/screen/diag`, `/visual/find`, `/crop`, `/describe`, `/ocr/find`
- **routes_uia.py**: `/uia/tree`, `/uia/find/*`, `/uia/click`, `/uia/find/name/*`, `/uia/element/*`, `/som/*` (all SOM routes)
- **routes_media.py**: `/clipboard/get`, `/clipboard/set`, `/windows/activate`, `/wallpaper/set`, `/wallpaper/random`, `/scheduler/*`, `/macro/*`, `/voice/*`, `/launch/ai`, `/search/files`, `/cursor/*`, `/recording/*`, `/wait/*`, `/stabilize`
- **routes_file.py**: `/power/*` (all power routes sleep/restart/shutdown/hibernate)
- **routes_mouse.py**: `/emergency/stop`, `/emergency/resume`
- **hermes_coagent.py**: `/logs` (already done — just verify)

Keep the auth exemptions minimal: only routes at `AUTH_EXEMPT_PREFIXES` and `AUTH_EXEMPT_PATHS` in hermes_coagent.py. Read those lists first to avoid breaking exemptions.

### P1: Fix TTS command injection (routes_media.py)
The TTS route builds a PowerShell script with user text interpolated into a string. Replace with a temp-file approach: write text to a temp file, have the PowerShell script read from the file instead.

### P1: Fix macro path traversal (routes_media.py)
Macro names can contain `../` to escape MACROS_DIR. Add a regex check `^[A-Za-z0-9_.-]{1,80}$` and resolve/verify the final path is under MACROS_DIR.

### P2: .gitignore & cleanup
- Add `.token`, `.token_*`, and `nul` to `.gitignore`
- The `nul` file in the repo directory is a PS redirect artifact — delete it

### P2: Wire or remove routes_v63.py
Either register it properly or absorb its routes into routes_media.py and delete routes_v63.py.

## Rules
1. Fix files in-place — read the file, make changes, write back
2. After each change, verify the file still compiles with `python -c "import py_compile; py_compile.compile('...', doraise=True)"`
3. Do NOT break existing functionality — only add guards, don't refactor logic
4. Do NOT change CODEX_AUDIT_REPORT.md
5. At the end, run `git diff` in the repo dir to show all changes made
