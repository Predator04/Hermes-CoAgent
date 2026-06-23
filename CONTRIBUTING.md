# Contributing to Hermes CoAgent

## Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/Predator04/Hermes-CoAgent.git
   cd Hermes-CoAgent
   ```

2. **Run setup wizard** (recommended for new users)
   ```bash
   python setup_wizard.py
   ```

3. **Manual launch for development**
   ```bash
   python hermes_coagent.py --secure --allow-external
   ```

## Architecture

Hermes CoAgent uses a modular route architecture:

```
hermes_coagent.py    # Main entry point - registers all route modules
shared.py            # Shared utilities (VERSION, COAGENT_DIR, helpers)
auth.py              # Authentication + CSRF protection
routes_*.py          # Each feature is a route module
```

Each `routes_*.py` module exports a `register_routes(app, state, require_auth)` function.

To add a new feature:
1. Create `routes_yourfeature.py` with a `register_routes()` function
2. Import and register it in `hermes_coagent.py`
3. Re-run the server

## Code Style

- **Python**: Follow PEP 8. Use 4-space indentation.
- **Flask**: Keep route handlers lean — business logic in helper functions.
- **Error handling**: All routes should return JSON errors, never HTML.
- **Auth**: All routes should be protected with `@require_auth`.
- **Logging**: Use `_console()` and `_log()` from `shared.py`.
- **Imports**: Minimize imports. Avoid adding new dependencies.

## Testing

```bash
python -m compileall -q .
```

Manual testing:
```bash
# Start server
python hermes_coagent.py --secure --allow-external

# Test endpoints
curl http://localhost:9123/ping
curl -H "Authorization: Bearer TOKEN" http://localhost:9123/version
```

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Run `python -m compileall -q .` to verify no syntax errors
4. Update AGENTS.md if adding/changing endpoints
5. Submit PR with description of changes

## Security

- Never commit `.token`, `.env`, or `telegram_config.json`
- Add config files to `.gitignore`
- Use `_sanitize_path()` and `_sanitize_cmd()` for user input
- All new endpoints need auth protection
