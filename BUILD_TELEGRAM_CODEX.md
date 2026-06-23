# Wire Codex output to Telegram via CoAgent

C:\Users\Admin\Desktop\Hermes CoAgent\routes_telegram.py already exists with:
- POST /telegram/configure (set bot token)
- POST /telegram/send (send message)
- POST /telegram/config (get current config)

## What needs to happen:

### 1. Add a new endpoint: POST /agent/exec-and-stream
This endpoint:
- Takes a prompt (just like /agent/exec)
- Runs Codex via routes_agent._run_agent() or the existing agent execution
- But instead of waiting for completion, streams output via SSE and ALSO forwards it to Telegram

Actually, a simpler approach:

### Add SSE streaming to /agent/exec
Modify routes_agent.py to add a new endpoint: POST /agent/exec-stream
Same as /agent/exec but:
- Uses SSE (text/event-stream) to stream results in real-time
- Returns events: "finding", "log", "error", "done"
- Each event carries the output chunk

### Add Telegram forwarding to the existing /agent/exec endpoint
After Codex finishes, auto-send the output to Telegram via routes_telegram's send capability.

### Alternative (simpler) — Add a POST /agent/exec-to-telegram endpoint
1. Runs the agent
2. Collects all stdout
3. Sends it to the configured Telegram chat
4. Returns {"status": "sent", "length": N}

## What I actually want:

Add to routes_telegram.py:

### POST /agent/exec-to-telegram
Body: {prompt: "string", target: "optional chat id"}
1. Read telegram_config.json to get bot token and chat_id
2. Call the agent execution (same as routes_agent._run_agent or the /agent/exec logic)
3. Stream the output as it comes back
4. For each chunk, send a Telegram message (or batch and send at end)
5. Return: {status: "ok", lines_sent: N, telegram_message_id: "..."}

Keep it simple: run the agent, collect output, send as one Telegram message at the end.

Import from routes_agent: import whatever is needed to run agents
Import from shared: _console for logging

Make sure to handle:
- If telegram_config.json doesn't exist -> return error
- If agent execution fails -> send error to Telegram
- If Telegram send fails -> log warning, don't crash

The key function signature:
```python
def route_agent_exec_to_telegram():
    body = _json_body()
    prompt = body.get("prompt", "")
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    
    # Run agent
    result = _run_agent_task("telegram-relay", prompt, timeout=600)
    stdout = result.get("stdout", "")
    
    # Send to Telegram
    try:
        with open(TELEGRAM_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        bot_token = cfg.get("bot_token", "")
        chat_id = cfg.get("chat_id", "")
        if bot_token and chat_id:
            _send_telegram_message(bot_token, chat_id, 
                f"🤖 *Codex Output*\n\n```\n{stdout[:3500]}\n```")
    except Exception as e:
        _console(f"[telegram] Failed to send: {e}")
    
    return jsonify({"status": "ok", "output_length": len(stdout)})
```

Also add a helper: `_send_telegram_message(bot_token, chat_id, text)` that uses urllib.request to POST to telegram API.

Don't rewrite routes_telegram.py — just add the new route and helpers at the end of the file, before `register_routes`.

After all changes:
- python -m compileall -q . must pass
