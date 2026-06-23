# CoAgent v7.11 — Build 4 New Features

C:\Users\Admin\Desktop\Hermes CoAgent\

Build these 4 features as standalone route modules. Each gets its own file.

## Feature 1: GIF Session Recorder — routes_recorder_gif.py

Record desktop sessions as animated GIFs.

- `POST /recorder/gif/start` — starts recording. Takes optional {fps: 5, max_seconds: 30, region: {x,y,w,h}}  
  Returns {recording_id, status: "recording"}
- `POST /recorder/gif/stop` — stops recording. Returns {recording_id, frames: N, gif_path: "...", gif_size_bytes: N}
- `GET /recorder/gif/status` — returns {is_recording: bool, recording_id, frames_captured, elapsed_seconds}
- `GET /recorder/gif/latest` — returns the last recorded GIF file as image/gif content type (binary response)

How it works:
- Uses PIL.ImageGrab.grab() for screenshots (already available in the project)
- Uses PIL.Image for GIF assembly: image.save(path, save_all=True, append_images=[...], loop=0, duration=1000/fps)
- Runs capture in a background thread (threading.Thread, daemon=True)
- Stores frames in memory list (PIL Image objects) during recording
- Saves to COAGENT_DIR / "recordings" / "rec_{id}.gif" 
- Cleanup: max 5 recordings, delete oldest when exceeded
- Use shared._console for logging

Include import from shared: COAGENT_DIR, _console
Blueprint: "recorder_gif", prefix none
Auth: all routes require auth

Registration: def register_routes(app, state, require_auth):

## Feature 2: Natural Language Undo — routes_undo.py

Track actions and allow undoing them.

- Stores an action history: list of {action_type, params, timestamp, screenshot_before, screenshot_after}
- `POST /undo/track` — called by other routes to record an action (mouse click, type, etc).
  Body: {action_type: "click", params: {x:100, y:200, button:"left"}, screenshot_path: "..."}
- `POST /undo/last` — undo the last action. For mouse clicks: click at the same position again if it was a simple click.
  For types: copy previous text and paste over. For drags: reverse the drag.
  Returns {undone: "click", at: {x:100, y:200}}
- `GET /undo/history?limit=10` — returns last N actions with timestamps
- `POST /undo/clear` — clear history

The undo logic should be simple but practical:
- mouse/click, mouse/dblclick -> click same position again (toggles)
- key/type -> copies the text that was typed back to the field (reverses the type)
- mouse/drag -> reverse drag (x1,y1 to x2,y2 becomes x2,y2 to x1,y1)
- scroll -> reverse scroll (clicks=-3 becomes clicks=3)
- for anything else -> return {error: "cannot undo this action type"}

Store history as list in memory, max 100 entries. Thread-safe with a lock.

Use shared._json_body, _console, COAGENT_DIR
Blueprint: "undo", prefix none
Auth: all routes require auth

Registration: def register_routes(app, state, require_auth):

## Feature 3: Before/After Diff — routes_diff.py

Compare screenshots and detect what changed.

- `POST /diff/capture` — captures a screenshot and stores it as a "baseline" snapshot
  Body: {label: "before_action"} (optional, defaults to timestamp)
  Returns: {snapshot_id, label, timestamp, path}
- `POST /diff/compare` — captures a new screenshot and compares it to the last baseline
  Body: {baseline_id: "optional_id"} (if omitted, uses the most recent)
  Returns: {changed: bool, changed_pixels: N, percent_changed: N, diff_image_path: "...", regions: [{x,y,w,h}]}
- `GET /diff/results?limit=5` — returns recent comparison results
- `GET /diff/image/{diff_id}` — returns the diff image as PNG binary

How it works:
- Uses PIL.ImageChops.difference() or direct pixel comparison
- Takes two PIL images, converts to RGB, subtracts them
- Non-zero pixels = changes
- Find bounding boxes of changed regions (find contiguous non-zero rectangles)
- Save diff image: white background, red pixels where changed
- Store in COAGENT_DIR / "diffs" / "diff_{id}.png"
- Store results in memory list, max 50 entries, with lock

Use PIL as lazy import (import inside the function, not at module top) for startup speed
Blueprint: "diff", prefix none
Auth: all routes require auth

Registration: def register_routes(app, state, require_auth):

## Feature 4: Smart Element Finder — routes_finder.py

Find UI elements on screen by description using OCR.

- `POST /finder/find` — takes a description and finds matching elements on screen
  Body: {description: "the search box at the top", screenshot: "optional base64 or omit to capture fresh"}
  Returns: {matches: [{text, x, y, w, h, confidence}], count: N}
- `POST /finder/click` — finds an element by description and clicks it
  Body: {description: "submit button", click_offset: {x:0, y:0}}
  Returns: {found: true, at: {x, y}, text: "Submit", action: "clicked"}
- `POST /finder/type` — finds a text field, clicks it, types text
  Body: {description: "username field", text: "myuser", clear_first: true}
  Returns: {found: true, at: {x, y}, text_field: "Username", action: "typed"}

How it works:
- Takes a fresh screenshot using PIL ImageGrab.grab()
- Uses OCR (reuse routes_ocr logic or call the existing /ocr/find endpoint internally via urllib to localhost)
  Actually simpler: call `http://127.0.0.1:9123/ocr/find` with the description via urllib
  OR import from routes_ocr if available
- For click: call the /mouse/click endpoint internally
- For type: call /key/type endpoint internally
- Use the token from COAGENT_DIR / ".token" for internal API calls
- All calls go to 127.0.0.1:9123 (localhost)

This is essentially an AI-powered wrapper around existing OCR + mouse endpoints.

Internal client helper:
```python
def _coagent_post(path, data):
    import urllib.request, json
    token_file = COAGENT_DIR / ".token"
    token = token_file.read_text().strip() if token_file.exists() else ""
    req = urllib.request.Request(f"http://127.0.0.1:9123{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())
```

Blueprint: "finder", prefix none
Auth: all routes require auth

Registration: def register_routes(app, state, require_auth):

## Integration: Update hermes_coagent.py

After all 4 files exist, add to hermes_coagent.py around line 590:
```python
try:
    from routes_recorder_gif import register_routes as reg_recorder_gif
    RECORDER_GIF_AVAILABLE = True
except ImportError:
    RECORDER_GIF_AVAILABLE = False

try:
    from routes_undo import register_routes as reg_undo
    UNDO_AVAILABLE = True
except ImportError:
    UNDO_AVAILABLE = False

try:
    from routes_diff import register_routes as reg_diff
    DIFF_AVAILABLE = True
except ImportError:
    DIFF_AVAILABLE = False

try:
    from routes_finder import register_routes as reg_finder
    FINDER_AVAILABLE = True
except ImportError:
    FINDER_AVAILABLE = False
```

And registration around line 660:
```python
    if RECORDER_GIF_AVAILABLE:
        reg_recorder_gif(app, state, require_auth)
        features["recorder_gif"] = True
    if UNDO_AVAILABLE:
        reg_undo(app, state, require_auth)
        features["undo"] = True
    if DIFF_AVAILABLE:
        reg_diff(app, state, require_auth)
        features["diff"] = True
    if FINDER_AVAILABLE:
        reg_finder(app, state, require_auth)
        features["finder"] = True
```

## Final Verification
1. python -m compileall -q . — must pass
2. All 4 modules load without errors
