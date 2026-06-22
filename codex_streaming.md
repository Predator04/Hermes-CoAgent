Add real-time streaming output to the Agent Gateway. Codex and Claude Code can take 5-10 minutes on big tasks, and waiting for the full output at the end is painful.

## What to build

### 1. GET /agent/exec/stream/:log_id
New endpoint that streams the output of a completed or in-progress agent execution in real-time using Server-Sent Events (SSE).

**How it works:**
- When `POST /agent/exec` runs, it writes output to `agent_logs/STDOUT_PID.tmp` and `agent_logs/STDERR_PID.tmp`
- The log_id is returned immediately in the POST response
- `GET /agent/exec/stream/:log_id` tails those temp files and streams new lines via SSE
- Format: `data: {"type": "stdout", "text": "line\n"}\n\n`
- Format: `data: {"type": "stderr", "text": "error line\n"}\n\n`
- Format: `data: {"type": "complete", "exit_code": 0, "duration": 45.2}\n\n`
- Format: `data: {"type": "files_modified", "files": ["file1.py"]}\n\n`
- Client connects with `EventSource` or `curl -N` and sees output in real-time

### 2. Modify _run_command to pipe output line-by-line
Currently it writes to temp files and reads them at the end. Change it to:
- Use `subprocess.PIPE` for stdout and stderr
- Read line by line in a thread
- Write each line to BOTH the temp file (for logging) AND a shared deque (for SSE)
- Store the deque in a dict keyed by a unique run ID
- Clean up deques after 5 minutes of no SSE connections

### 3. Add /agent/exec-stream endpoint
A POST endpoint that accepts the same payload as /agent/exec but:
- Returns immediately with `{"log_id": "20260622_143022", "stream_url": "/agent/exec/stream/20260622_143022"}`
- Starts the agent in a background thread
- The stream endpoint delivers output in real-time

### 4. Modify existing /agent/exec to also support ?stream=true
When `?stream=true` is appended to the POST URL, the response should be SSE instead of JSON. This lets you do `curl -N -X POST /agent/exec?stream=true` and see output as it happens.

## Implementation Pattern
```python
from flask import Response, stream_with_context

# Store active streams
_ACTIVE_STREAMS = {}  # log_id -> deque of lines
_STREAM_LOCK = threading.Lock()

def _write_line(log_id, line_type, text):
    with _STREAM_LOCK:
        if log_id not in _ACTIVE_STREAMS:
            _ACTIVE_STREAMS[log_id] = deque(maxlen=10000)
        _ACTIVE_STREAMS[log_id].append(json.dumps({"type": line_type, "text": text}))

def _close_stream(log_id, exit_code, duration):
    with _STREAM_LOCK:
        if log_id in _ACTIVE_STREAMS:
            _ACTIVE_STREAMS[log_id].append(json.dumps({"type": "complete", "exit_code": exit_code, "duration": duration}))

def stream_agent_output(log_id):
    def generate():
        # Send backlog first
        with _STREAM_LOCK:
            backlog = list(_ACTIVE_STREAMS.get(log_id, []))
        for entry in backlog:
            yield f"data: {entry}\n\n"
        
        # Poll for new entries
        last_count = len(backlog)
        while True:
            with _STREAM_LOCK:
                current = list(_ACTIVE_STREAMS.get(log_id, []))
            
            for entry in current[last_count:]:
                yield f"data: {entry}\n\n"
                parsed = json.loads(entry)
                if parsed.get("type") == "complete":
                    return
            last_count = len(current)
            time.sleep(0.1)
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")
```

## Requirements
- Use `stream_with_context` from Flask
- Clean up stream deques 5 minutes after the agent finishes
- Lock everything properly (thread safety)
- Log all streaming output to the JSON log file as well
- The existing POST /agent/exec should NOT break — only add new behavior

## Verification
After implementing, run:
1. curl -N http://127.0.0.1:9123/agent/exec-stream -H "Authorization: Bearer *** -H "Content-Type: application/json" -d '{"prompt":"say hello one per line 5 times","timeout":30}'
2. Should see one "hello" per line as they come in
3. Then a final "complete" event
