"""Remote desktop page, MJPEG stream, and optional WebSocket frames."""

import base64
import time

from flask import Response, request, stream_with_context


REMOTE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Remote</title>
<style>
body{margin:0;background:#101216;color:#eef2f6;font:14px system-ui,Segoe UI,Arial,sans-serif}header{height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;background:#171b23;border-bottom:1px solid #303744}.wrap{height:calc(100vh - 48px);display:grid;place-items:center;padding:10px}img{max-width:100%;max-height:100%;background:#050608;border:1px solid #303744;border-radius:6px;cursor:crosshair}.muted{color:#9aa5b1}button{background:#2f7df6;color:white;border:0;border-radius:5px;padding:7px 10px}
</style>
</head>
<body>
<header><strong>Hermes Remote</strong><span class="muted" id="state">connecting</span><button id="shot">Frame</button></header>
<div class="wrap"><img id="screen" alt="remote desktop"></div>
<script>
const params=new URLSearchParams(location.search);const queryToken=params.get("token")||"";if(queryToken)localStorage.setItem("hermes_token",queryToken);const token=queryToken||localStorage.getItem("hermes_token")||"";
function headers(json=false){const h={};if(token)h.Authorization="Bearer "+token;if(json)h["Content-Type"]="application/json";return h}
async function frame(){const r=await fetch("/screen/jpeg?ts="+Date.now(),{headers:headers(false)});if(!r.ok)throw new Error("screen "+r.status);const b=await r.blob();const img=document.getElementById("screen");const old=img.src;img.src=URL.createObjectURL(b);if(old)URL.revokeObjectURL(old);document.getElementById("state").textContent="polling 172.21.192.1:9123"}
document.getElementById("shot").onclick=()=>frame().catch(e=>document.getElementById("state").textContent=e.message);
document.getElementById("screen").onclick=async ev=>{const img=ev.currentTarget;const rect=img.getBoundingClientRect();const sx=(img.naturalWidth||rect.width)/rect.width;const sy=(img.naturalHeight||rect.height)/rect.height;const x=Math.round((ev.clientX-rect.left)*sx);const y=Math.round((ev.clientY-rect.top)*sy);await fetch("/mouse/click",{method:"POST",headers:headers(true),body:JSON.stringify({x,y,retry:false})})};
frame().catch(e=>document.getElementById("state").textContent=e.message);setInterval(()=>frame().catch(()=>{}),250);
</script>
</body>
</html>"""


def _capture_frame(quality=70):
    from routes_ocr import _capture_jpeg
    return _capture_jpeg(force=True, quality=quality)


def _mjpeg_generator(interval=0.1, quality=70):
    while True:
        frame = _capture_frame(quality=quality)
        if frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n"
        time.sleep(interval)


def _sse_generator(interval=0.1, quality=70):
    while True:
        frame = _capture_frame(quality=quality)
        if frame:
            payload = base64.b64encode(frame).decode("ascii")
            yield f"event: frame\ndata: {payload}\n\n"
        else:
            yield "event: error\ndata: no_frame\n\n"
        time.sleep(interval)


def register_routes(app, state, require_auth):
    @app.route("/remote", methods=["GET"])
    @require_auth
    def route_remote():
        return Response(REMOTE_HTML, mimetype="text/html")

    @app.route("/remote/stream", methods=["GET"])
    @require_auth
    def route_remote_stream():
        try:
            fps = max(1, min(int(request.args.get("fps", 10)), 30))
        except (TypeError, ValueError):
            fps = 10
        try:
            quality = max(20, min(int(request.args.get("quality", 70)), 95))
        except (TypeError, ValueError):
            quality = 70
        return Response(
            stream_with_context(_mjpeg_generator(interval=1.0 / fps, quality=quality)),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.route("/remote/ws", methods=["GET"])
    @require_auth
    def route_remote_ws():
        try:
            quality = max(20, min(int(request.args.get("quality", 70)), 95))
        except (TypeError, ValueError):
            quality = 70
        return Response(
            stream_with_context(_sse_generator(interval=0.1, quality=quality)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
