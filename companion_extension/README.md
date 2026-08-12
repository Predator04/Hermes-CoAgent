# CoAgent Companion — Browser Extension (MV3)

Drive the user's **real** browser (with real logged-in sessions) from CoAgent.

## Why

CoAgent's stealth/Playwright browser spins up a fresh profile, so it can't reuse the
user's actual session cookies (e.g. Gmail, dashboards, ticketing tools). This extension
runs *inside* the user's normal Chrome/Brave/Edge profile and lets CoAgent navigate,
click, type, read DOM, extract content, scroll, and screenshot the real browser.

## How it works

The extension is a **polling client** over HTTP to the CoAgent server (no WebSocket):

1. Agent → `POST /browser/companion/command` (CoAgent queues the command, blocks up to `timeout`).
2. Extension → `GET /browser/companion/poll` (long-poll ~20s) to fetch the next command.
3. Extension executes it in the active tab.
4. Extension → `POST /browser/companion/result` with the outcome.
5. The blocked `/command` call wakes and returns the result to the agent.

## Install (Brave/Chrome/Edge)

1. Open `brave://extensions` (or `chrome://extensions`, `edge://extensions`).
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select this `companion_extension/` folder.
4. Click the extension icon → set the **Server URL** (default `http://127.0.0.1:9123`)
   and paste the **Bearer token** (from `Hermes CoAgent\.token`).
5. Click **Save & Reconnect** — the status dot turns green when connected.

## Command types

| type | payload | result |
|------|---------|--------|
| `navigate` | `{url}` | `{url, title}` |
| `click` | `{selector, index?}` | `{selector, index, clicked}` |
| `type` | `{selector, text}` | `{selector}` |
| `read` | `{selector?}` | `{text, url, title}` |
| `extract` | `{selector?}` | `{title, url, text, links[], images[], forms}` |
| `evaluate` | `{js}` | `{value}` |
| `scroll` | `{amount}` | `{scrolled}` |
| `screenshot` | `{}` | `{dataUrl}` (PNG, quality 80) |
| `tabs` | `{}` | `{tabs[]}` |

## Example (agent → CoAgent)

```bash
curl -s http://127.0.0.1:9123/browser/companion/command \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"type":"extract","timeout":30}'
```

## Server endpoints

- `POST /browser/companion/command` — enqueue + wait for result
- `GET  /browser/companion/poll`   — long-poll (extension)
- `POST /browser/companion/result` — report result (extension)
- `GET  /browser/companion/status` — connection status

## Security

- All endpoints require the CoAgent Bearer token (`@require_auth`).
- The extension sends the token from `chrome.storage.local` on every request.
- `screenshot` uses `chrome.tabs.captureVisibleTab` (requires `activeTab` + `<all_urls>`).
- The `evaluate` command runs arbitrary JS in page context — treat as the user's own
  browser automation tool, same trust level as the CoAgent server itself.
