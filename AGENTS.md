# Hermes CoAgent

Full Windows desktop control server. See README.md for complete documentation.

## Files

- hermes_coagent.py — Main HTTP server. Flask app with all REST APIs, input engine, screenshot capture, OCR, macros, tunnel, TTS, clipboard, file ops.
- computer_use_mcp.py — MCP protocol server (26 tools). Routes through CoAgent HTTP server for desktop actions.
- uia_engine.py — Windows UIA (accessibility) tree engine. Element finding, SOM overlays, background input.
- coagent_tray.py — System tray application (runs via pythonw.exe).
- auth.py — Bearer token authentication module.

## Quick Reference

```bash
# Start server (localhost only, no auth)
python hermes_coagent.py

# Start server with auth + external access
python hermes_coagent.py --secure --allow-external

# Run self-test
python hermes_coagent.py --test

# MCP server self-test
python computer_use_mcp.py --test
```

## Common Tasks

### File Transfer (>50MB for Telegram)
```powershell
powershell -File "send_telegram_file.ps1" -FilePath "C:\path\to\file.apk"
```
Then use MCP tools to navigate Telegram Desktop file picker and send.

### One-Shot Launch
```powershell
powershell -File "launch_all.ps1"
```

## Security Notes

- Default: binds to 127.0.0.1 (local only), no auth
- --secure: generates random Bearer token
- --allow-external: binds to 0.0.0.0
- Emergency stop: Ctrl+Alt+Shift kills all input
