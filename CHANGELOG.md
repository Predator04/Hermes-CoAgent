# Changelog

All notable changes to Hermes CoAgent are documented here. Versions follow
`MAJOR.MINOR.PATCH`; every published change bumps `VERSION` (read at runtime by
all modules and surfaced at the `/version` endpoint).

## [8.52.0] - 2026-08-07

### Added — 5 new capability modules (issues #5, #9, #13, #2, #8)

- **Capability discovery (#5)** — `GET /discover` and `/capabilities` return a
  machine-readable manifest of every route family, its endpoints, and whether
  the Python deps / external CLI tools it needs are present, so an orchestrator
  can plan around what's installed instead of hitting mid-task 404s.
  (`routes_discover.py`)
- **Humanized mouse movement (#9)** — `POST /mouse/humanized_move` drives the
  cursor along a randomized cubic-Bezier arc with an eased, jittered velocity
  profile instead of teleporting. Deterministic with a seed; returns the
  computed path as a dry run on headless hosts. (`routes_humanize.py`)
- **Human-in-the-loop approval gate (#13)** — an API-level, tunnel-friendly
  approval queue: `POST /approvals/request`, `GET /approvals/pending`,
  `POST /approvals/<id>/approve|reject`, `GET /approvals/<id>`, plus
  `require_approval()` to block a programmatic action until a human decides
  (fail-closed on timeout). Complements the existing win32 HUD overlay.
  (`routes_approvals.py`)
- **Natural-language macro builder (#2)** — `POST /macro/build` parses plain
  step text (`click X,Y`, `type ...`, `press ctrl+s`, `wait 250ms`,
  `scroll down 3`, ...) into a structured macro for the recorder/replay engine.
  (`routes_macro_builder.py`)
- **Semantic discover-then-act UIA (#8)** — `POST /uia/act` targets an element
  by role + name, ranks candidates by match score, and acts on the best one
  instead of using raw coordinates; returns ranked candidates as a dry run when
  no live UIA tree is available. (`routes_uia_semantic.py`)

Each module ships with unit tests (`tests/test_new_features.py`, 10 tests). Also
fixed a latent `_missing_field` misuse on the netsh empty-command path.

## [8.51.15] - 2026-08-07

### Fixed

- **`--port` now honored across all internal self-calls.** The WSGI server always
  bound the requested `--port`, but healer, finder, copilot, mobile, recipes,
  screen-vision, recovery-daemon, hybrid-agent and the tray subprocess hardcoded
  `127.0.0.1:9123`, so running on a non-default port broke self-health checks and
  the tray tunnel. `start_server` now exports `COAGENT_PORT` (and syncs
  `shared.SERVER_PORT`); `shared._self_port()` reads it with a 9123 fallback, and
  every self-caller builds its URL from it. Resolves the "Healer hardcodes port
  9123" and "--port flag ignored" issues.

## [8.51.14] - 2026-08-07

Launch-readiness pass: full compile check of all 134 Python modules, the pytest
suite (now 71 passing / 6 skipped), and a security-focused review of the server,
auth, agent routes, and the `routes_auto_*` tool wrappers.

### Fixed

- **11 POST endpoints were non-functional** across `routes_auto_gsudo`,
  `routes_auto_imagemagick`, `routes_auto_nmap`, `routes_auto_rufus`,
  `routes_auto_trippy`, and `routes_auto_ventoy`. They called
  `_json_body(request)`, but `shared._json_body()` treats its first positional
  argument as a payload to serialize — so it tried to `jsonify()` the Flask
  request proxy and raised, meaning the request body was never read and each
  endpoint's core action was unreachable (HTTP 400/500). Now called as
  `_json_body()`, which reads the request internally.
- **`netsh` read-only bypass (security).** The `/auto/netsh/command` guard only
  restricted subcommands when the context appeared in `READONLY_CONTEXTS`. The
  allowed `ras` context has no entry there, so state-changing subcommands
  (`set`/`add`/`delete`) skipped the guard. The check is now default-deny: any
  context without a read-only allowlist is rejected.
- **`_log()` called with two arguments** in `routes_auto_gsudo` (error path) and
  `routes_auto_nmap` (three scan-logging calls). `shared._log()` takes a single
  message, so these raised `TypeError` — in gsudo's case masking the original
  error. Collapsed to single-argument calls.
- **`--port` could crash startup.** `int(sys.argv[idx + 1])` raised
  `IndexError`/`ValueError` on a missing or non-numeric value. Now bounds-checked
  and range-validated (1–65535) with a clear fatal message.
- **Stale tray test.** `tests/test_tray.py` mocked `pystray.Menu` without a
  `SEPARATOR` attribute and asserted an outdated 6-item menu, so it failed
  against the current 13-item tray menu. Mock and expectations updated; added
  separator filtering.

### Added

- `tests/test_netsh_readonly.py` — regression coverage proving the `ras` context
  cannot run state-changing subcommands and that non-read-only subcommands are
  rejected for every context.
- This changelog.

### Known issues

- **Playwright sync objects are created and closed on different Waitress worker
  threads** (`browser_automation.py`). The sync API binds objects to their
  creating thread, so `/browser/undetectable/<id>/close` and shutdown can raise
  and leak the Chromium process. A correct fix marshals each session's
  create/navigate/close onto a dedicated per-session thread; deferred and tracked
  as a GitHub issue because it is a structural change that needs a Windows +
  patchright runtime to validate.

[8.51.14]: https://github.com/Predator04/Hermes-CoAgent/releases/tag/v8.51.14
