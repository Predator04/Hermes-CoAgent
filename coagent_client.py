"""CoAgent — Python client for Hermes CoAgent v7.0 REST API.

Usage: from coagent_client import CoAgent; c = CoAgent()
"""

import os, json, base64, time
from urllib.request import Request, urlopen
from urllib.error import URLError


class CoAgent:
    """Client for Hermes CoAgent v7.0 REST API."""

    def __init__(self, url=None, token=None):
        self.url = (url or os.environ.get("COAGENT_URL", "http://172.21.192.1:9123")).rstrip("/")
        self.token = token or os.environ.get("COAGENT_TOKEN", "") or os.environ.get("HERMES_COAGENT_TOKEN", "")
        self._headers = {}
        if self.token:
            self._headers["Authorization"] = f"Bearer {self.token}"

    def _req(self, method, path, data=None, timeout=10):
        body = json.dumps(data).encode() if data else None
        if data:
            self._headers["Content-Type"] = "application/json"
        req = Request(f"{self.url}{path}", data=body, headers=self._headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except URLError as e:
            try: err = e.read().decode(errors="replace")[:500]
            except: err = str(e)
            return {"error": str(e), "detail": err}
        except Exception as e:
            return {"error": str(e)}

    def _get(self, path, **kw): return self._req("GET", path, **kw)
    def _post(self, path, data, **kw): return self._req("POST", path, data, **kw)

    def ping(self): return self._get("/ping")
    def version(self): return self._get("/version")
    def cursor_pos(self): return self._get("/cursor/pos")
    def clipboard_get(self): return self._get("/clipboard/get")
    def describe(self): return self._get("/describe")
    def uia_tree(self): return self._get("/uia/tree")
    def som(self): return self._get("/som/screenshot")
    def list_windows(self): return self._get("/windows")
    def stats(self): return self._get("/stats")
    def emergency_stop(self): return self._post("/emergency/stop", {})
    def emergency_resume(self): return self._post("/emergency/resume", {})

    def screenshot(self, path=None):
        r = self._get("/screen/base64")
        if "data" in r:
            data = base64.b64decode(r["data"])
            if path:
                with open(path, "wb") as f: f.write(data)
            return data
        return None

    def ocr_find(self, text):
        return self._post("/ocr/find", {"text": text})

    def uia_find(self, name):
        return self._get(f"/uia/find/{name}")

    def point(self, x, y):
        return self._post("/som/point", {"x": x, "y": y})

    def move(self, x, y, background=True):
        return self._post("/mouse/move", {"x": x, "y": y, "background": background})

    def click(self, x, y, button="left", background=True):
        return self._post("/mouse/click", {"x": x, "y": y, "button": button, "background": background})

    def double_click(self, x, y, background=True):
        return self._post("/mouse/dblclick", {"x": x, "y": y, "background": background})

    def right_click(self, x, y, background=True):
        return self._post("/mouse/rclick", {"x": x, "y": y, "background": background})

    def drag(self, x1, y1, x2, y2, button="left", background=True):
        return self._post("/mouse/drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": button, "background": background})

    def scroll(self, clicks=-3):
        return self._post("/mouse/scroll", {"clicks": clicks})

    def type(self, text):
        return self._post("/key/type", {"text": text})

    def hotkey(self, keys):
        return self._post("/key/press", {"keys": keys})

    def chain(self, actions):
        return self._post("/chain", {"actions": actions})

    def activate_window(self, title):
        return self._post("/windows/activate", {"title": title})

    def file_list(self, path):
        return self._post("/file/list", {"path": path})

    def file_read(self, path):
        return self._post("/file/read", {"path": path})

    def launch(self, query):
        return self._post("/launch/ai", {"query": query})

    def clipboard_set(self, text):
        return self._post("/clipboard/set", {"text": text})

    def macro_list(self):
        return self._post("/macro/list", {})

    def macro_save(self, name, actions):
        return self._post("/macro/save", {"name": name, "actions": actions})

    def macro_run(self, name):
        return self._post("/macro/run", {"name": name})

    def search_files(self, pattern, path="C:/Users/Admin", limit=50):
        return self._post("/search/files", {"pattern": pattern, "path": path, "limit": limit})

    # ── High-level helpers ──

    def click_text(self, text):
        r = self.ocr_find(text)
        matches = r.get("matches", [])
        if not matches:
            return None
        m = matches[0]
        c = m.get("center", {})
        x, y = c.get("x"), c.get("y")
        if x and y: return self.click(x, y)
        return m

    def type_at(self, x, y, text, click_first=True):
        if click_first: self.click(x, y); time.sleep(0.2)
        return self.type(text)

    def copy_and_type(self, text):
        self.clipboard_set(text); time.sleep(0.1)
        return self.hotkey(["ctrl", "v"])

    def screenshot_and_describe(self, save_to=None):
        img = self.screenshot(save_to)
        return {"screenshot": img, "description": self.describe()}

    def open_telegram(self):
        self.launch("telegram"); time.sleep(4)

    def telegram_send(self, contact, message):
        self.open_telegram()
        self.hotkey(["ctrl", "k"]); time.sleep(0.5)
        self.type(contact); time.sleep(1.5)
        self.hotkey(["enter"]); time.sleep(1)
        self.type(message)
        return self.hotkey(["enter"])


if __name__ == "__main__":
    c = CoAgent()
    print(f"Ping: {c.ping()}")
    print(f"Cursor: {c.cursor_pos()}")
    print(f"Describe: {c.describe().get('description', '')[:200]}")
