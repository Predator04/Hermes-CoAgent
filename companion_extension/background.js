// CoAgent Companion — MV3 background service worker.
//
// Polls the local Hermes CoAgent server for commands, executes them in the
// user's ACTIVE tab, and POSTs the result back. Because MV3 service workers
// are terminated after ~30s of idle, we use chrome.alarms to periodically
// re-kick the poll loop, and each "loop run" performs a bounded number of
// sequential long-polls before yielding so the SW can be suspended cleanly.

const DEFAULT_SERVER = "http://127.0.0.1:9123";
const DEFAULT_TOKEN = "";

// Long-poll timeout on the client side. The server holds requests ~20s, so
// we give the fetch a little more than that before aborting.
const POLL_TIMEOUT_MS = 25000;

// How many long-polls to chain per loop run before yielding to the alarm.
// Keeps the SW alive for at most ~1 minute per wake, then lets it suspend.
const POLLS_PER_RUN = 2;

// Back-off (ms) applied after a network error to avoid tight retry loops
// when the server is down. Doubles on repeated failure up to MAX_BACKOFF_MS.
const INITIAL_BACKOFF_MS = 2000;
const MAX_BACKOFF_MS = 30000;

// Navigation wait timeout for the "navigate" command.
const NAV_TIMEOUT_MS = 30000;

// Alarm name used to re-kick the poll loop.
const ALARM_NAME = "coagent_poll";

// Guard against multiple concurrent poll loops (e.g. alarm + startup racing).
let pollLoopRunning = false;
let currentBackoff = INITIAL_BACKOFF_MS;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

async function getConfig() {
  const { serverUrl, token } = await chrome.storage.local.get(["serverUrl", "token"]);
  return {
    serverUrl: (serverUrl || DEFAULT_SERVER).replace(/\/+$/, ""),
    token: token || DEFAULT_TOKEN,
  };
}

async function setLastStatus(status) {
  try {
    await chrome.storage.local.set({ lastStatus: { ...status, ts: Date.now() } });
  } catch (_) {
    // Storage errors here are not fatal — the popup just won't refresh.
  }
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function authHeaders(token) {
  const h = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = "Bearer " + token;
  return h;
}

async function fetchWithTimeout(url, opts, timeoutMs) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opts, signal: ctl.signal });
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Active tab helper
// ---------------------------------------------------------------------------

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || tabs.length === 0) throw new Error("no active tab");
  return tabs[0];
}

// ---------------------------------------------------------------------------
// Page-context helper functions (serialized and injected via executeScript).
// These must be self-contained — no closures over background scope.
// ---------------------------------------------------------------------------

function _pageClick(selector, index) {
  const els = document.querySelectorAll(selector);
  if (!els || els.length === 0) throw new Error("no element matches selector: " + selector);
  const i = index || 0;
  if (i >= els.length) throw new Error("index " + i + " out of range (" + els.length + " matches)");
  const el = els[i];
  el.scrollIntoView({ block: "center", inline: "center" });
  el.click();
  return { selector: selector, index: i, clicked: true };
}

function _pageType(selector, text) {
  const el = document.querySelector(selector);
  if (!el) throw new Error("no element matches selector: " + selector);
  el.focus();
  const proto = el.tagName === "TEXTAREA"
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value") && Object.getOwnPropertyDescriptor(proto, "value").set;
  if (setter) {
    setter.call(el, text);
  } else {
    el.value = text;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { selector: selector };
}

function _pageRead(selector) {
  let text;
  if (selector) {
    const el = document.querySelector(selector);
    if (!el) throw new Error("no element matches selector: " + selector);
    text = el.innerText || el.textContent || "";
  } else {
    text = document.body ? (document.body.innerText || "") : "";
  }
  return { text: text, url: location.href, title: document.title };
}

function _pageExtract(selector) {
  const root = selector ? document.querySelector(selector) : document.body;
  if (!root) throw new Error("no element matches selector: " + selector);
  const text = root.innerText || root.textContent || "";
  const links = Array.from(root.querySelectorAll("a[href]")).map(a => a.href);
  const images = Array.from(root.querySelectorAll("img[src]")).map(i => i.src);
  const forms = root.querySelectorAll("form").length;
  return {
    title: document.title,
    url: location.href,
    text: text,
    links: links,
    images: images,
    forms: forms,
  };
}

function _pageEvaluate(js) {
  // eslint-disable-next-line no-new-func
  const val = (new Function("return (" + js + ");"))();
  try {
    return { value: JSON.stringify(val) };
  } catch (_) {
    return { value: String(val) };
  }
}

function _pageScroll(amount) {
  window.scrollBy(0, amount);
  return { scrolled: amount };
}

// Wrapper that runs an injected function and returns the first frame's result,
// converting thrown page-side exceptions into rejected promises.
async function runInPage(tabId, func, args) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func,
    args: args || [],
    world: "MAIN",
  });
  if (!results || results.length === 0) throw new Error("executeScript returned no result");
  const r = results[0];
  if (r && r.error) throw new Error(String(r.error));
  return r.result;
}

// ---------------------------------------------------------------------------
// Command executors
// ---------------------------------------------------------------------------

async function execNavigate(cmd) {
  const url = cmd.url;
  if (!url) throw new Error("navigate requires 'url'");
  const tab = await getActiveTab();
  const tabId = tab.id;

  await chrome.tabs.update(tabId, { url });

  // Wait for the tab to finish loading (status === "complete"), with timeout.
  const finalTab = await new Promise((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("navigation timeout after " + NAV_TIMEOUT_MS + "ms"));
    }, NAV_TIMEOUT_MS);

    function listener(updatedTabId, changeInfo, updatedTab) {
      if (updatedTabId !== tabId) return;
      if (changeInfo.status === "complete") {
        if (done) return;
        done = true;
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(updatedTab);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });

  return { url: finalTab.url || url, title: finalTab.title || "" };
}

async function execClick(cmd) {
  if (!cmd.selector) throw new Error("click requires 'selector'");
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageClick, [cmd.selector, cmd.index || 0]);
}

async function execType(cmd) {
  if (!cmd.selector) throw new Error("type requires 'selector'");
  if (typeof cmd.text !== "string") throw new Error("type requires 'text'");
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageType, [cmd.selector, cmd.text]);
}

async function execRead(cmd) {
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageRead, [cmd.selector || ""]);
}

async function execExtract(cmd) {
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageExtract, [cmd.selector || ""]);
}

async function execEvaluate(cmd) {
  if (typeof cmd.js !== "string") throw new Error("evaluate requires 'js'");
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageEvaluate, [cmd.js]);
}

async function execScroll(cmd) {
  const amount = typeof cmd.amount === "number" ? cmd.amount : 500;
  const tab = await getActiveTab();
  return await runInPage(tab.id, _pageScroll, [amount]);
}

async function execScreenshot(_cmd) {
  const tab = await getActiveTab();
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "png",
    quality: 80,
  });
  return { dataUrl };
}

async function execTabs(_cmd) {
  const tabs = await chrome.tabs.query({});
  return {
    tabs: tabs.map(t => ({
      id: t.id,
      url: t.url,
      title: t.title,
      active: !!t.active,
    })),
  };
}

const COMMAND_EXECUTORS = {
  navigate: execNavigate,
  click: execClick,
  type: execType,
  read: execRead,
  extract: execExtract,
  evaluate: execEvaluate,
  scroll: execScroll,
  screenshot: execScreenshot,
  tabs: execTabs,
};

// ---------------------------------------------------------------------------
// Poll + dispatch + report
// ---------------------------------------------------------------------------

async function postResult(serverUrl, token, commandId, payload) {
  try {
    await fetchWithTimeout(
      serverUrl + "/browser/companion/result",
      {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ command_id: commandId, ...payload }),
      },
      10000,
    );
  } catch (e) {
    // If we can't report, log and drop — the server will time the command out.
    console.warn("[coagent] failed to post result:", e);
  }
}

async function pollOnce(serverUrl, token) {
  let resp;
  try {
    resp = await fetchWithTimeout(
      serverUrl + "/browser/companion/poll",
      { method: "GET", headers: authHeaders(token) },
      POLL_TIMEOUT_MS,
    );
  } catch (e) {
    throw new Error("poll fetch failed: " + (e && e.message ? e.message : e));
  }

  if (!resp.ok) {
    throw new Error("poll HTTP " + resp.status);
  }

  let body;
  try {
    body = await resp.json();
  } catch (e) {
    throw new Error("poll bad JSON: " + e.message);
  }

  const cmd = body && body.command;
  const commandId = body && body.command_id;
  if (!cmd || !commandId) {
    return { idle: true };
  }

  const type = cmd.type;
  const exec = COMMAND_EXECUTORS[type];
  if (!exec) {
    await postResult(serverUrl, token, commandId, {
      ok: false,
      error: "unknown command type: " + type,
    });
    await setLastStatus({ ok: false, type, error: "unknown command type" });
    return { idle: false };
  }

  try {
    const data = await exec(cmd);
    await postResult(serverUrl, token, commandId, { ok: true, data });
    await setLastStatus({ ok: true, type, summary: summarize(type, data) });
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    await postResult(serverUrl, token, commandId, { ok: false, error: msg });
    await setLastStatus({ ok: false, type, error: msg });
  }
  return { idle: false };
}

function summarize(type, data) {
  if (!data) return "";
  if (type === "navigate") return data.url || "";
  if (type === "read") return (data.text || "").slice(0, 80);
  if (type === "extract") return (data.title || "") + " (" + (data.links ? data.links.length : 0) + " links)";
  if (type === "screenshot") return "png " + (data.dataUrl ? data.dataUrl.length : 0) + " bytes";
  if (type === "tabs") return (data.tabs ? data.tabs.length : 0) + " tabs";
  return "ok";
}

async function pollLoop() {
  if (pollLoopRunning) return;
  pollLoopRunning = true;
  try {
    for (let i = 0; i < POLLS_PER_RUN; i++) {
      const { serverUrl, token } = await getConfig();
      try {
        await pollOnce(serverUrl, token);
        currentBackoff = INITIAL_BACKOFF_MS; // reset back-off on success
      } catch (e) {
        console.warn("[coagent] poll error:", e && e.message ? e.message : e);
        await setLastStatus({ ok: false, type: "poll", error: String(e && e.message ? e.message : e) });
        // Sleep with back-off before retrying, then break out of this run so
        // the alarm can wake us again later (avoids a hot retry loop).
        await new Promise(r => setTimeout(r, currentBackoff));
        currentBackoff = Math.min(currentBackoff * 2, MAX_BACKOFF_MS);
        break;
      }
    }
  } finally {
    pollLoopRunning = false;
  }
}

// ---------------------------------------------------------------------------
// Lifecycle: install, startup, alarms
// ---------------------------------------------------------------------------

function ensureAlarm() {
  chrome.alarms.get(ALARM_NAME, (a) => {
    if (!a) {
      // Fire roughly every 30s. Each fire triggers a poll run that itself may
      // take up to ~50s (POLLS_PER_RUN * POLL_TIMEOUT_MS). Overlaps are guarded
      // by pollLoopRunning.
      chrome.alarms.create(ALARM_NAME, { periodInMinutes: 0.5 });
    }
  });
}

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
  pollLoop();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
  pollLoop();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) pollLoop();
});

// Allow the popup to force an immediate poll (e.g. after saving config).
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "kick") {
    ensureAlarm();
    pollLoop();
    sendResponse({ ok: true });
    return true;
  }
  return false;
});

// Kick immediately on SW startup as well (covers manual reloads).
ensureAlarm();
pollLoop();
