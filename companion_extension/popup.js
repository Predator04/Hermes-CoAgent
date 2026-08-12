// CoAgent Companion popup: load/save config, ping status, show last command.

const DEFAULT_SERVER = "http://127.0.0.1:9123";

const $ = (id) => document.getElementById(id);

async function loadConfig() {
  const { serverUrl, token } = await chrome.storage.local.get(["serverUrl", "token"]);
  $("serverUrl").value = serverUrl || DEFAULT_SERVER;
  $("token").value = token || "";
}

async function saveConfig() {
  const serverUrl = $("serverUrl").value.trim().replace(/\/+$/, "") || DEFAULT_SERVER;
  const token = $("token").value.trim();
  await chrome.storage.local.set({ serverUrl, token });
  $("saveMsg").textContent = "Saved";
  setTimeout(() => { $("saveMsg").textContent = ""; }, 1500);
  // Ask the background SW to kick a poll immediately with the new config.
  try {
    await chrome.runtime.sendMessage({ type: "kick" });
  } catch (_) {
    // SW may be asleep; the next alarm will pick up the config.
  }
  await refreshStatus();
}

async function refreshStatus() {
  const { serverUrl, token } = await chrome.storage.local.get(["serverUrl", "token"]);
  const url = (serverUrl || DEFAULT_SERVER).replace(/\/+$/, "");
  $("serverInfo").textContent = url;
  $("connDot").className = "dot";
  $("connText").textContent = "checking…";

  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const resp = await fetch(url + "/browser/companion/status", {
      method: "GET",
      headers,
      signal: ctl.signal,
    });
    clearTimeout(timer);
    if (resp.ok) {
      let info = "";
      try {
        const body = await resp.json();
        if (body && typeof body === "object") {
          const bits = [];
          if (body.pending !== undefined) bits.push("pending=" + body.pending);
          if (body.paired !== undefined) bits.push("paired=" + body.paired);
          if (body.version !== undefined) bits.push("v" + body.version);
          if (bits.length) info = " (" + bits.join(", ") + ")";
        }
      } catch (_) { /* body parse optional */ }
      $("connDot").className = "dot ok";
      $("connText").textContent = "connected" + info;
    } else if (resp.status === 401 || resp.status === 403) {
      $("connDot").className = "dot err";
      $("connText").textContent = "auth failed (" + resp.status + ")";
    } else {
      $("connDot").className = "dot err";
      $("connText").textContent = "HTTP " + resp.status;
    }
  } catch (e) {
    clearTimeout(timer);
    $("connDot").className = "dot err";
    $("connText").textContent = "unreachable";
  }
}

async function refreshLastCmd() {
  const { lastStatus } = await chrome.storage.local.get(["lastStatus"]);
  if (!lastStatus) {
    $("lastCmd").textContent = "—";
    return;
  }
  const when = lastStatus.ts ? new Date(lastStatus.ts).toLocaleTimeString() : "";
  const tag = lastStatus.ok ? "OK" : "ERR";
  const type = lastStatus.type || "?";
  const detail = lastStatus.ok
    ? (lastStatus.summary || "")
    : (lastStatus.error || "");
  $("lastCmd").textContent = "[" + when + "] " + tag + " " + type + " — " + detail;
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadConfig();
  $("saveBtn").addEventListener("click", saveConfig);
  await refreshStatus();
  await refreshLastCmd();
  // Refresh periodically while popup is open.
  setInterval(refreshLastCmd, 1500);
  setInterval(refreshStatus, 5000);
});
