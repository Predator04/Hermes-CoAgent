You are Claude Code auditing the Hermes CoAgent codebase after a Codex CLI security overhaul pass.

The repo is at `C:\Users\Admin\Desktop\Hermes CoAgent\`.

## Step 1: Read ALL Python files

Read every .py file in the repo. Build a complete mental model of the auth system, every route, and how auth is applied.

## Step 2: Verify Codex's Changes

Codex claims to have done the following. VERIFY each one by reading the actual files:

1. **Auth startup fix** — `hermes_coagent.py` should detect `--token=KEY` via `any(a.startswith("--token") for a in sys.argv)`, refuse `--allow-external` without auth, import `AUTH_ENABLED` from auth module
2. **Route protection** — Every route in routes_ocr.py, routes_uia.py, routes_file.py, routes_mouse.py, routes_media.py should have `@require_auth` where appropriate. Screenshot/OCR/UIA/SOM routes, power/emergency, clipbaord, scheduler, macro, cursor, recording, wait, stabilize endpoints
3. **TTS injection fix** — routes_media.py TTS route should use temp-file approach, not string interpolation in PowerShell
4. **Macro path traversal fix** — routes_media.py macro routes should have name validation regex + resolved path containment
5. **/auth/token/reset** — auth.py reset endpoint should be POST-only + require Bearer token
6. **routes_v63.py deleted** — should not exist
7. **.gitignore** — should have .token, .token_*, nul entries
8. **nul artifact** — check if nul still exists in repo dir

## Step 3: Find What Codex Missed

Codex can't run shell commands from its sandbox. Look for:

1. **Compile errors** — manually check for syntax errors in every modified .py file
2. **Missing routes** — any route that still doesn't have @require_auth
3. **Inconsistent auth** — some routes protected, similar ones not
4. **Auth exemption list** — check that /, /ping, /version, /health are exempt but nothing else dangerous
5. **Duplicate routes** — any routes registered twice (Flask will use the last one)
6. **Dead imports** — unused imports after Codex's changes
7. **Inconsistent error responses** — some routes return different error shapes

## Step 4: Check the Global Auth Gate

Codex claims it added a "global auth gate with explicit public exemptions" to hermes_coagent.py. Read that code carefully — it should be a `@app.before_request` handler that checks auth for ALL routes except an explicit allowlist. If it exists, is it correct?

## Step 5: Report

Write your findings to `CODEX_CLAUDE_REVIEW.md` in the repo directory with:
- **Verified Fixes** — what Codex got right
- **Issues Found** — what Codex missed or broke
- **Remaining Work** — things still needing fixes
- **Health Score** — A-F

Be specific: file paths, line numbers, code snippets. If Codex broke something, say so.
