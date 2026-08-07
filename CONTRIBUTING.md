# Contributing to Hermes CoAgent

## Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/Predator04/Hermes-CoAgent.git
   cd Hermes-CoAgent
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch for development**
   ```bash
   python hermes_coagent.py --secure --allow-external
   ```

## Architecture

```
hermes_coagent.py    # Main entry point — registers all route modules
shared.py            # Shared utilities (VERSION loader, helpers, SSE)
auth.py              # Bearer auth + CSRF protection
uia_engine.py        # Windows UI Automation engine
routes_*.py          # Modular route handlers
routes_auto_*.py     # Auto-generated Windows CLI tool wrappers
tests/               # Test suite
VERSION              # Single source of truth for version number
```

Each `routes_*.py` module exports a `register_routes(app, state, require_auth)` function.

### Adding a New Feature

1. Create `routes_yourfeature.py` with a `register_routes()` function
2. Import and register it in `hermes_coagent.py`
3. Add tests in `tests/`
4. Run `python test_compile.py` to verify syntax

## Versioning

Version is stored in `VERSION` file. All modules read it at runtime via `shared.py`.

**Bumping the version:**
```bash
python bump_version.py patch   # 8.50 → 8.51
python bump_version.py minor   # 8.50 → 9.0
python bump_version.py major   # 8.50 → 9.0.0
```

Never hardcode version strings in source files.

## Code Style

- **Python**: PEP 8, 4-space indentation
- **Flask**: Lean route handlers — business logic in helper functions
- **Error handling**: All routes return JSON errors, never HTML
- **Auth**: All routes protected with `@require_auth` (when `--secure` is active)
- **Logging**: Use `_console()` and `_log()` from `shared.py`
- **Imports**: Minimize imports. Avoid adding new dependencies without discussion

## Testing

```bash
# Syntax check (fast)
python test_compile.py

# Full test suite
pytest tests/ -v

# Single test file
pytest tests/test_agent.py -v
```

Manual smoke test:
```bash
python hermes_coagent.py --secure --allow-external &
curl http://localhost:9123/ping
curl -H "Authorization: Bearer $(cat .token)" http://localhost:9123/version
```

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Run `python test_compile.py` to verify no syntax errors
4. Run relevant tests with `pytest`
5. Update `AGENTS.md` if adding/changing endpoints
6. Bump version with `python bump_version.py patch`
7. Submit PR with description of changes

## Security

- Never commit `.token`, `.env`, or `telegram_config.json`
- Use `_sanitize_path()` and `_sanitize_cmd()` for user input
- All new endpoints need auth protection
- Report vulnerabilities via [SECURITY.md](SECURITY.md)
