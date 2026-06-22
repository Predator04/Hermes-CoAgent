"""Unit tests for routes_bypass.py using Flask test client."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from flask import Flask
from routes_bypass import register_routes, MAX_TEXT_CHARS

app = Flask(__name__)
register_routes(app, None, lambda f: f)
client = app.test_client()

passed = 0
failed = 0

def post(path, data=None):
    return client.post(path, json=data if isinstance(data, dict) else data,
                       content_type="application/json" if not isinstance(data, dict) else None)

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} — {detail}")
        failed += 1

def status_test(name, path, data, expected_status):
    r = post(path, data)
    check(name, r.status_code == expected_status,
          f"Expected {expected_status}, got {r.status_code}: {r.get_json()}")

# 1. Index
r = client.get("/bypass")
data = r.get_json()
check("index has 9 tools", len(data["tools"]) == 9, f"Got {len(data['tools'])}")
paths = [t["path"] for t in data["tools"]]
for p in ["/bypass/leetspeak", "/bypass/homoglyph", "/bypass/zero-width",
          "/bypass/parseltongue", "/bypass/prefill", "/bypass/adversarial",
          "/bypass/scan", "/bypass/clean", "/bypass/all"]:
    check(f"index contains {p}", p in paths)

# 2. Normal operations
r = post("/bypass/leetspeak", {"text": "hello world", "intensity": 0.5})
check("leetspeak normal", r.status_code == 200, str(r.get_json()))
check("leetspeak changes text", r.get_json()["encoded"] != "hello world")

r = post("/bypass/homoglyph", {"text": "test", "block": "fullwidth"})
check("homoglyph fullwidth", r.status_code == 200)

r = post("/bypass/zero-width", {"text": "test", "frequency": 1.0})
check("zero-width dense", r.status_code == 200)
check("zero-width longer", len(r.get_json()["encoded"]) > len(r.get_json()["original"]))

r = post("/bypass/parseltongue", {"text": "hello world", "passes": 3})
check("parseltongue 3 passes", r.status_code == 200)
check("parseltongue has 3 passes", len(r.get_json()["passes"]) == 3)

r = post("/bypass/prefill", {"text": "test", "template": "boundary_inversion"})
check("prefill boundary inversion", r.status_code == 200)
check("prefill contains GODMODE", "GODMODE" in r.get_json()["wrapped"])

r = client.get("/bypass/prefill")
check("prefill GET", r.status_code == 200)
check("prefill has 5 templates", len(r.get_json()["templates"]) == 5)

r = post("/bypass/adversarial", {"text": "I need to understand how to hack a system for testing"})
check("adversarial", r.status_code == 200)
check("adversarial has 5+ variants", len(r.get_json()["variants"]) >= 5)

r = post("/bypass/scan", {"text": "I want to hack a computer"})
check("scan detects trigger", r.status_code == 200)
check("scan not clean", not r.get_json()["clean"])

r = post("/bypass/clean", {"text": "I want to hack a computer"})
check("clean obfuscates trigger", r.status_code == 200)
data = r.get_json()
check("clean replaced word hack", "hack" not in data["cleaned"].lower(), data["cleaned"])
check("clean has replacements", data["total_replaced"] >= 1)

r = post("/bypass/all", {"text": "how to hack wifi", "template": "educational_compatibility"})
check("all endpoint", r.status_code == 200)
data = r.get_json()
for key in ["scan", "cleaned", "parseltongue", "prefilled", "adversarial"]:
    check(f"all has {key}", key in data)

# 3. Empty text
status_test("empty text leetspeak", "/bypass/leetspeak", {"text": ""}, 400)
status_test("empty text scan", "/bypass/scan", {"text": ""}, 400)

# 4. Oversized text
big_text = "x" * (MAX_TEXT_CHARS + 1)
status_test("oversized text", "/bypass/scan", {"text": big_text}, 413)

# 5. Bad JSON shapes
r = client.post("/bypass/leetspeak", data="[]", content_type="application/json")
check("array body", r.status_code == 400)

r = client.post("/bypass/leetspeak", data="not json", content_type="application/json")
check("invalid json", r.status_code == 400)

r = post("/bypass/leetspeak", {"text": ["not", "a", "string"]})
check("non-string text", r.status_code == 400)

# 6. Bad numeric fields
status_test("nan intensity", "/bypass/leetspeak", {"text": "test", "intensity": "nan"}, 400)
status_test("inf intensity", "/bypass/leetspeak", {"text": "test", "intensity": "inf"}, 400)
status_test("string intensity", "/bypass/leetspeak", {"text": "test", "intensity": "abc"}, 400)
status_test("bad frequency", "/bypass/zero-width", {"text": "test", "frequency": "bad"}, 400)
status_test("bad passes", "/bypass/parseltongue", {"text": "test", "passes": "x"}, 400)

r = post("/bypass/parseltongue", {"text": "test", "passes": -1})
check("passes clamped to min", r.status_code == 200)
check("passes min result", len(r.get_json()["passes"]) == 1)

r = post("/bypass/parseltongue", {"text": "test", "passes": 99})
check("passes clamped to max", r.status_code == 200)
check("passes max result", len(r.get_json()["passes"]) == 5)

# 7. Bad template names
status_test("bad template prefill", "/bypass/prefill", {"text": "test", "template": "nonexistent"}, 400)
status_test("bad template all", "/bypass/all", {"text": "test", "template": "nonexistent"}, 400)

r = post("/bypass/prefill", {"text": "test", "template": 123})
check("bad template type", r.status_code == 400)

# 8. Unicode-only text
r = post("/bypass/leetspeak", {"text": "你好世界", "intensity": 1.0})
check("CJK text leetspeak", r.status_code == 200)

r = post("/bypass/homoglyph", {"text": "🔥💯🚀", "block": "fullwidth"})
check("emoji homoglyph", r.status_code == 200)

r = post("/bypass/scan", {"text": "مرحبا بالعالم"})
check("RTL text scan", r.status_code == 200)
check("RTL text is clean", r.get_json()["clean"])

# 9. CLI escaping
r = post("/bypass/all", {"text": "test' ; calc", "template": "educational_compatibility"})
check("CLI escaping", r.status_code == 200)
cli_check = r.get_json()["cli"]["scan_check"]
check("CLI has escaped quotes", "\\u0027" in cli_check, cli_check)

# 10. Loaded from data file
r = post("/bypass/scan", {"text": "I will jailbreak my phone"})
check("trigger from data file", r.status_code == 200)
check("jailbreak detected", r.get_json()["total_matches"] >= 1)

r = post("/bypass/scan", {"text": "GODMODE activate"})
check("GODMODE detected", r.status_code == 200)
check("GODMODE found", r.get_json()["total_matches"] >= 1)

# Summary
total = passed + failed
print(f"\n{'='*40}")
print(f"RESULTS: {passed}/{total} passed, {failed}/{total} failed")
print(f"{'='*40}")

sys.exit(0 if failed == 0 else 1)
