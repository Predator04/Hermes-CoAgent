"""Mobile remote-control page and touch translation routes."""

import json
import urllib.error
import urllib.request

from flask import Blueprint, Response, jsonify, request

from shared import _json_body


mobile_bp = Blueprint("mobile", __name__)

DEFAULT_WIDTH = 2560
DEFAULT_HEIGHT = 1440


MOBILE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>Hermes Mobile</title>
<style>
:root{color-scheme:dark;--bg:#070a0d;--panel:#10161d;--panel2:#151e27;--line:#25313d;--text:#ecf4fb;--muted:#91a2b2;--accent:#2dd4bf;--warn:#f59e0b;--danger:#ef4444}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--text);font:15px system-ui,Segoe UI,Arial,sans-serif;letter-spacing:0}
button,input{font:inherit}
button{min-height:44px;border:1px solid var(--line);border-radius:8px;background:#182331;color:var(--text);padding:8px 11px}
button:active{transform:translateY(1px);background:#213044}
input{min-height:44px;border:1px solid var(--line);border-radius:8px;background:#0c1218;color:var(--text);padding:8px 10px;min-width:0}
.app{height:100%;display:grid;grid-template-rows:auto 1fr auto;background:var(--bg)}
.top{display:flex;align-items:center;gap:8px;padding:8px 10px calc(8px + env(safe-area-inset-top));background:linear-gradient(135deg,#111a23,#10161d 58%,#142820);border-bottom:1px solid var(--line)}
.brand{font-weight:700;white-space:nowrap}.status{margin-left:auto;color:var(--muted);font-size:13px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warn);margin-right:5px}.dot.ok{background:#22c55e}.dot.bad{background:var(--danger)}
.viewer{position:relative;overflow:hidden;touch-action:none;background:#020405;display:grid;place-items:center}
#screen{max-width:100%;max-height:100%;width:100%;height:100%;object-fit:contain;transform-origin:center center;will-change:transform;user-select:none}
.toast{position:absolute;left:12px;right:12px;bottom:12px;min-height:38px;padding:9px 10px;border:1px solid rgba(37,49,61,.85);border-radius:8px;background:rgba(7,10,13,.86);color:var(--muted);font-size:13px;opacity:0;transition:opacity .18s}
.toast.show{opacity:1}
.kbd{display:grid;grid-template-columns:1fr auto;gap:8px;padding:8px 10px calc(8px + env(safe-area-inset-bottom));background:var(--panel);border-top:1px solid var(--line)}
.keys{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.auth{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(7,10,13,.88);padding:18px}
.auth.show{display:flex}.authbox{width:min(460px,100%);border:1px solid var(--line);border-radius:10px;background:var(--panel2);padding:14px;display:grid;gap:10px}
.authbox h1{font-size:17px;margin:0}.authbox p{margin:0;color:var(--muted);font-size:13px}
@media (orientation:landscape){.kbd{grid-template-columns:1fr auto auto auto auto}.keys{grid-column:auto;display:flex}.top{padding-top:6px;padding-bottom:6px}.kbd{padding-top:6px;padding-bottom:calc(6px + env(safe-area-inset-bottom))}}
</style>
</head>
<body>
<div class="app">
  <header class="top">
    <div class="brand">Hermes Mobile</div>
    <button id="fitBtn">Fit</button>
    <button id="refreshBtn">Frame</button>
    <div class="status"><span id="dot" class="dot"></span><span id="status">connecting</span></div>
  </header>
  <main id="viewer" class="viewer">
    <img id="screen" alt="Desktop">
    <div id="toast" class="toast"></div>
    <div id="auth" class="auth">
      <div class="authbox">
        <h1>Token</h1>
        <p>Paste the CoAgent bearer token for control actions on this device.</p>
        <input id="tokenInput" type="password" autocomplete="off" placeholder="Bearer token">
        <button id="tokenSave">Save</button>
      </div>
    </div>
  </main>
  <footer class="kbd">
    <input id="textInput" type="text" autocomplete="off" placeholder="Type text">
    <button id="sendText">Send</button>
    <div class="keys">
      <button data-key="enter">Enter</button>
      <button data-key="tab">Tab</button>
      <button data-key="escape">Esc</button>
      <button data-key="ctrl+v">Ctrl+V</button>
    </div>
  </footer>
</div>
<script>
(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  const queryToken = (params.get("token") || "").replace(/^Bearer\s+/i, "");
  if (queryToken) {
    sessionStorage.setItem("hermes_token", queryToken);
    params.delete("token");
    history.replaceState(null, document.title, location.pathname + (params.toString() ? "?" + params.toString() : ""));
  }
  let token = (queryToken || sessionStorage.getItem("hermes_token") || "").replace(/^Bearer\s+/i, "");
  const $ = (id) => document.getElementById(id);
  const screen = $("screen");
  const viewer = $("viewer");
  const state = {scale:1,start:null,pinch:false,pinchDistance:0,timer:null};
  function headers(json){const h={}; if(token) h.Authorization = "Bearer " + token; if(json) h["Content-Type"]="application/json"; return h}
  function status(text, kind){$("status").textContent=text; $("dot").className = "dot " + (kind || "")}
  function toast(text){const el=$("toast"); el.textContent=text; el.classList.add("show"); clearTimeout(state.toastTimer); state.toastTimer=setTimeout(()=>el.classList.remove("show"),1500)}
  function needAuth(){if(!token){$("auth").classList.add("show"); return true} return false}
  async function api(path, body){if(needAuth()) throw new Error("token required"); const r=await fetch(path,{method:"POST",headers:headers(true),body:JSON.stringify(body||{})}); const data=await r.json().catch(()=>({})); if(!r.ok) throw new Error(data.error||("HTTP "+r.status)); return data}
  function refresh(){screen.src="/mobile/view?ts="+Date.now(); status("refreshing","")}
  screen.onload=()=>status("connected","ok");
  screen.onerror=()=>status("view error","bad");
  function displayedRect(){
    const rect=screen.getBoundingClientRect();
    const nw=screen.naturalWidth||rect.width, nh=screen.naturalHeight||rect.height;
    const imgRatio=nw/nh, boxRatio=rect.width/rect.height;
    let w=rect.width,h=rect.height,left=rect.left,top=rect.top;
    if(boxRatio>imgRatio){w=rect.height*imgRatio; left=rect.left+(rect.width-w)/2}
    else{h=rect.width/imgRatio; top=rect.top+(rect.height-h)/2}
    return {left,top,width:w,height:h};
  }
  function pctFromPoint(x,y){
    const r=displayedRect();
    return {
      x:Math.max(0,Math.min(100,((x-r.left)/r.width)*100)),
      y:Math.max(0,Math.min(100,((y-r.top)/r.height)*100))
    };
  }
  function distance(a,b){const dx=a.clientX-b.clientX,dy=a.clientY-b.clientY; return Math.sqrt(dx*dx+dy*dy)}
  viewer.addEventListener("touchstart",(ev)=>{
    if(ev.touches.length===2){state.pinch=true; state.pinchDistance=distance(ev.touches[0],ev.touches[1]); return}
    const t=ev.touches[0]; state.start={x:t.clientX,y:t.clientY,time:Date.now()};
  },{passive:false});
  viewer.addEventListener("touchmove",(ev)=>{
    ev.preventDefault();
    if(ev.touches.length===2){const d=distance(ev.touches[0],ev.touches[1]); if(state.pinchDistance){state.scale=Math.max(1,Math.min(4,state.scale*(d/state.pinchDistance))); screen.style.transform="scale("+state.scale.toFixed(2)+")"} state.pinchDistance=d}
  },{passive:false});
  viewer.addEventListener("touchend",async(ev)=>{
    ev.preventDefault();
    if(state.pinch){if(ev.touches.length===0) state.pinch=false; return}
    if(!state.start || !ev.changedTouches.length) return;
    const t=ev.changedTouches[0], dx=t.clientX-state.start.x, dy=t.clientY-state.start.y;
    const moved=Math.sqrt(dx*dx+dy*dy);
    try{
      if(moved>24){const a=pctFromPoint(state.start.x,state.start.y), b=pctFromPoint(t.clientX,t.clientY); await api("/mobile/swipe",{x1:a.x,y1:a.y,x2:b.x,y2:b.y}); toast("swiped")}
      else{const p=pctFromPoint(t.clientX,t.clientY); await api("/mobile/tap",p); toast("tapped")}
    }catch(e){toast(e.message)}
    state.start=null;
  },{passive:false});
  viewer.addEventListener("click",async(ev)=>{
    if(ev.pointerType==="touch") return;
    try{const p=pctFromPoint(ev.clientX,ev.clientY); await api("/mobile/tap",p); toast("clicked")}catch(e){toast(e.message)}
  });
  $("sendText").onclick=async()=>{const text=$("textInput").value; if(!text)return; try{await api("/mobile/type",{text}); $("textInput").value=""; toast("typed")}catch(e){toast(e.message)}};
  document.querySelectorAll("[data-key]").forEach(btn=>btn.onclick=async()=>{try{await api("/mobile/key",{key:btn.dataset.key}); toast(btn.dataset.key)}catch(e){toast(e.message)}});
  $("fitBtn").onclick=()=>{state.scale=1; screen.style.transform="scale(1)"; toast("fit")};
  $("refreshBtn").onclick=refresh;
  $("tokenSave").onclick=()=>{token=$("tokenInput").value.trim().replace(/^Bearer\s+/i,""); if(token){sessionStorage.setItem("hermes_token",token); $("auth").classList.remove("show"); toast("token saved")}};
  if(!token) $("auth").classList.add("show");
  refresh(); state.timer=setInterval(refresh,500);
})();
</script>
</body>
</html>"""


def _auth_header():
    header = request.headers.get("Authorization", "")
    if header:
        return header
    token = request.args.get("token") or (_json_body().get("token") if request.method == "POST" else "")
    if token:
        token = str(token).strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return "Bearer " + token
    return ""


def _coagent_post(path, data):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = _auth_header()
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:9123{path}",
        data=json.dumps(data or {}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw or str(exc)}
        payload.setdefault("error", payload.get("error") or f"HTTP {exc.code}")
        payload["status_code"] = exc.code
        return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "status_code": 0}


def _screen_bounds():
    try:
        from routes_ocr import _monitor_bounds
        monitor = _monitor_bounds(0)
        return {
            "left": int(monitor.get("left", 0)),
            "top": int(monitor.get("top", 0)),
            "width": int(monitor.get("width", DEFAULT_WIDTH)) or DEFAULT_WIDTH,
            "height": int(monitor.get("height", DEFAULT_HEIGHT)) or DEFAULT_HEIGHT,
        }
    except Exception:
        return {"left": 0, "top": 0, "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT}


def _percent_to_desktop(x, y):
    bounds = _screen_bounds()
    px = max(0.0, min(100.0, float(x)))
    py = max(0.0, min(100.0, float(y)))
    return {
        "x": int(bounds["left"] + bounds["width"] * px / 100.0),
        "y": int(bounds["top"] + bounds["height"] * py / 100.0),
        "bounds": bounds,
    }


def _result_or_error(result, success_payload):
    if isinstance(result, dict) and result.get("error"):
        return jsonify({"error": result.get("error"), "details": result}), 502
    return jsonify({**success_payload, "result": result})


@mobile_bp.route("/mobile", methods=["GET"])
def route_mobile_page():
    return Response(MOBILE_HTML, mimetype="text/html")


@mobile_bp.route("/mobile/view", methods=["GET"])
def route_mobile_view():
    try:
        from routes_ocr import _capture_jpeg
        data = _capture_jpeg(force=True, quality=65, monitor_index=0)
    except Exception:
        data = b""
    if not data:
        return jsonify({"error": "No screenshot"}), 500
    bounds = _screen_bounds()
    return Response(
        data,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Screen-Width": str(bounds["width"]),
            "X-Screen-Height": str(bounds["height"]),
            "X-Screen-Left": str(bounds["left"]),
            "X-Screen-Top": str(bounds["top"]),
        },
    )


@mobile_bp.route("/mobile/tap", methods=["POST"])
def route_mobile_tap():
    data = _json_body()
    point = _percent_to_desktop(data.get("x", 0), data.get("y", 0))
    result = _coagent_post("/mouse/click", {"x": point["x"], "y": point["y"], "retry": False})
    return _result_or_error(result, {"status": "clicked", "desktop_x": point["x"], "desktop_y": point["y"]})


@mobile_bp.route("/mobile/swipe", methods=["POST"])
def route_mobile_swipe():
    data = _json_body()
    start = _percent_to_desktop(data.get("x1", 0), data.get("y1", 0))
    end = _percent_to_desktop(data.get("x2", 0), data.get("y2", 0))
    result = _coagent_post(
        "/mouse/drag",
        {"x1": start["x"], "y1": start["y"], "x2": end["x"], "y2": end["y"], "background": False},
    )
    return _result_or_error(
        result,
        {
            "status": "swiped",
            "desktop_start": {"x": start["x"], "y": start["y"]},
            "desktop_end": {"x": end["x"], "y": end["y"]},
        },
    )


@mobile_bp.route("/mobile/type", methods=["POST"])
def route_mobile_type():
    data = _json_body()
    result = _coagent_post("/key/type", {"text": str(data.get("text", ""))})
    return _result_or_error(result, {"status": "typed"})


@mobile_bp.route("/mobile/key", methods=["POST"])
def route_mobile_key():
    data = _json_body()
    key = str(data.get("key", "")).strip()
    if not key:
        return jsonify({"error": "key is required"}), 400
    keys = [part for part in key.replace("+", " ").split() if part]
    result = _coagent_post("/key/press", {"keys": keys})
    return _result_or_error(result, {"status": "pressed", "key": key})


def register_routes(app, state, require_auth):
    for endpoint, view_func in list(mobile_bp.view_functions.items()):
        if endpoint.endswith("route_mobile_page"):
            continue
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        mobile_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(mobile_bp)
    state.mobile_remote = {"default_width": DEFAULT_WIDTH, "default_height": DEFAULT_HEIGHT}
