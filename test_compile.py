import ast, sys
from pathlib import Path

files = [str(p) for p in sorted(Path(".").glob("*.py"))]

for f in files:
    try:
        ast.parse(Path(f).read_text(encoding="utf-8"))
        print(f"{f}: OK")
    except SyntaxError as e:
        print(f"{f}: SYNTAX ERROR: {e}")
        sys.exit(1)

print("ALL OK")
