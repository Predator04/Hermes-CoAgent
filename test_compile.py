"""CoAgent syntax smoke test — ensures all .py files parse cleanly."""
import ast, sys
from pathlib import Path

files = sorted(Path(".").glob("*.py"))
errors = []

for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"FAIL: {f}: {e}")
        errors.append(f)

if errors:
    print(f"\n{len(errors)} file(s) failed syntax check.")
    sys.exit(1)

print(f"ALL OK — {len(files)} files parsed cleanly.")
