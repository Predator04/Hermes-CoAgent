"""Real-time HTML dashboard route."""

from flask import Response


CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"

TOKEN_PLACEHOLDER = "__HERMES_TOKEN_PLACEHOLDER__"

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'">
<title>Hermes CoAgent Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#111318;--panel:#181c24;--panel2:#202632;--text:#f2f5f8;--muted:#9aa5b1;--ok:#42d392;--bad:#ff6b6b;--line:#303846}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--line);background:#0f1217;position:sticky;top:0;z-index:2}
h1{font-size:18px;margin:0;font-weight:650}.status{display:flex;gap:10px;align-items:center;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;background:var(--bad)}.dot.ok{background:var(--ok)}
main{display:grid;grid-template-columns:minmax(360px,1.35fr) minmax(320px,.9fr);gap:14px;padding:14px;max-width:1500px;margin:0 auto}
section{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-width:0}section h2{font-size:13px;text-transform:uppercase;letter-spacing:0;margin:0;padding:10px 12px;border-bottom:1px solid var(--line);color:var(--muted)}
.body{padding:12px}.screen{width:100%;aspect-ratio:16/9;object-fit:contain;background:#050608;border:1px solid var(--line);border-radius:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}.card{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:10px;min-height:62px}.card strong{display:block;font-size:13px}.card span{color:var(--muted);font-size:12px}
.health-row{display:grid;grid-template-columns:minmax(130px,1fr) 70px;gap:8px;align-items:center;margin:7px 0}.bar{height:8px;background:#333b48;border-radius:99px;overflow:hidden}.fill{height:100%;background:var(--ok);width:0}.fill.bad{background:var(--bad)}
.log-tools{display:flex;gap:8px;margin-bottom:8px}.log-tools input{flex:1;background:#0d1016;color:var(--text);border:1px solid var(--line);border-radius:5px;padding:8px}
button{background:#2f7df6;color:white;border:0;border-radius:5px;padding:8px 10px;cursor:pointer}button:disabled{opacity:.5}
pre{white-space:pre-wrap;overflow:auto;max-height:390px;margin:0;background:#090b10;border:1px solid var(--line);border-radius:6px;padding:10px;color:#d7dde5}
.wide{grid-column:1/-1}.error{color:var(--bad)}@media(max-width:850px){main{grid-template-columns:1fr}.wide{grid-column:auto}}
</style>
</head>
<body>
<header><h1>Hermes CoAgent</h1><div class="status"><span id="dot" class="dot"></span><span id="summary">connecting</span></div></header>
<main>
<section><h2>Screen</h2><div class="body"><img id="screen" class="screen" alt="screen preview"></div></section>
<section><h2>Runtime</h2><div class="body"><div id="modules" class="grid"></div></div></section>
<section class="wide"><h2>Endpoint Health</h2><div class="body" id="health"></div></section>
<section class="wide"><h2>Logs</h2><div class="body"><div class="log-tools"><input id="filter" placeholder="Search logs"><button id="refresh">Refresh</button></div><pre id="logs"></pre></div></section>
</main>
<!-- sessionStorage keeps URL-provided tokens scoped to the current tab. -->
<script>
const params=new URLSearchParams(location.search);const queryToken=params.get("token")||"";if(queryToken){sessionStorage.setItem("hermes_token",queryToken);params.delete("token");const cleanUrl=location.pathname+(params.toString()?"?"+params.toString():"")+location.hash;history.replaceState(null,document.title,cleanUrl)}const token="__HERMES_TOKEN_PLACEHOLDER__"||queryToken||sessionStorage.getItem("hermes_token")||"";
function headers(json=false){const h={};if(token)h.Authorization="Bearer "+token;if(json)h["Content-Type"]="application/json";return h}
async function getJson(path){const r=await fetch(path,{headers:headers(false)});if(!r.ok)throw new Error(path+" "+r.status);return await r.json()}
function setSummary(ok,text){document.getElementById("dot").className="dot"+(ok?" ok":"");document.getElementById("summary").textContent=text}
async function loadVersion(){const v=await getJson("/version");document.title="Hermes "+v.version;const el=document.getElementById("modules");el.innerHTML="";(v.modules||[]).forEach(m=>{const d=document.createElement("div");d.className="card";d.innerHTML="<strong>"+m+"</strong><span>loaded</span>";el.appendChild(d)});setSummary(true,"v"+v.version+" ready")}
async function loadScreen(){const r=await fetch("/screen/jpeg?ts="+Date.now(),{headers:headers(false)});if(!r.ok)throw new Error("screen "+r.status);const blob=await r.blob();const url=URL.createObjectURL(blob);const img=document.getElementById("screen");const old=img.src;img.src=url;if(old)URL.revokeObjectURL(old)}
async function loadHealth(){const h=await getJson("/health/endpoints");const host=document.getElementById("health");const rows=Object.entries(h.endpoints||{}).sort((a,b)=>String(a[0]).localeCompare(String(b[0])));if(!rows.length){host.textContent="No endpoint samples yet";return}host.innerHTML="";rows.forEach(([path,row])=>{const safePath=path.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const rate=Number(row.last_5min_success_rate_pct??row.success_rate_pct??100);const wrap=document.createElement("div");wrap.className="health-row";wrap.innerHTML="<div><div>"+safePath+"</div><div class='bar'><div class='fill "+(rate<80?"bad":"")+"' style='width:"+Math.max(0,Math.min(100,rate))+"%'></div></div></div><div>"+rate+"%</div>";host.appendChild(wrap)})}
async function loadLogs(){const data=await getJson("/logs?format=json&lines=250");const q=document.getElementById("filter").value.toLowerCase();const lines=(data.lines||[]).filter(l=>!q||l.toLowerCase().includes(q));document.getElementById("logs").textContent=lines.join("\n")}
async function tick(){try{await Promise.allSettled([loadVersion(),loadScreen(),loadHealth(),loadLogs()])}catch(e){setSummary(false,e.message)}}
document.getElementById("refresh").onclick=tick;document.getElementById("filter").oninput=loadLogs;tick();setInterval(()=>Promise.allSettled([loadScreen(),loadHealth()]),3000);setInterval(loadLogs,5000);
</script>
</body>
</html>"""


def register_routes(app, state, require_auth):
    @app.route("/dashboard", methods=["GET"])
    @require_auth
    def route_dashboard():
        # Inject Bearer token into the HTML so the JS can use it directly
        import json as _json
        import auth
        token = auth.AUTH_TOKEN or ""
        escaped_token = _json.dumps(token)[1:-1].replace("<", "\\u003c")
        html = DASHBOARD_HTML.replace(TOKEN_PLACEHOLDER, escaped_token)
        response = Response(html, mimetype="text/html")
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
