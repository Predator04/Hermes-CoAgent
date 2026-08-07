"""CoAgent syntax smoke test — ensures all .py files parse cleanly."""
import ast, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # scripts/ → repo root
errors = []

# Check root .py files
for f in sorted(ROOT.glob("*.py")):
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"FAIL: {f.name}: {e}")
        errors.append(f)

# Check scripts/ .py files
for f in sorted((ROOT / "scripts").glob("*.py")):
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"FAIL: scripts/{f.name}: {e}")
        errors.append(f)

# Check tests/ .py files
for f in sorted((ROOT / "tests").glob("*.py")):
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"FAIL: tests/{f.name}: {e}")
        errors.append(f)

if errors:
    print(f"\n{len(errors)} file(s) failed syntax check.")
    sys.exit(1)

total = len(list(ROOT.glob("*.py"))) + len(list((ROOT / "scripts").glob("*.py"))) + len(list((ROOT / "tests").glob("*.py")))
print(f"ALL OK — {total} files parsed cleanly.")
