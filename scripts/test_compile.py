"""CoAgent syntax smoke test — ensures all .py files parse cleanly."""
import ast, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # scripts/ → repo root
errors = []

# Directories that must never be descended into during the recursive scan.
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _iter_py_files():
    """Yield every .py file under ROOT, skipping excluded directories."""
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDE_DIRS for part in parts):
            continue
        yield path


checked = 0
for f in _iter_py_files():
    checked += 1
    try:
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    except (SyntaxError, ValueError, OSError) as e:
        print(f"FAIL: {f.relative_to(ROOT)}: {e}")
        errors.append(f)

if errors:
    print(f"\n{len(errors)} file(s) failed syntax check.")
    sys.exit(1)

print(f"ALL OK — {checked} files parsed cleanly.")
