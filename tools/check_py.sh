#!/usr/bin/env bash
# Hermes CoAgent syntax check — PostToolUse hook (fires on every Edit/Write).
# v2.1.148 notes: $CLAUDE_FILE_PATHS is not set, so detect .py edits via git status.
# py_compile is syntax-only (matches scripts/test_compile.py's guarantee); the real
# runtime check is booting on a spare port (see AGENTS.md pitfalls).
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-/mnt/c/Users/Admin/Desktop/Hermes CoAgent}" 2>/dev/null || exit 0
files="$(git status --porcelain 2>/dev/null | awk '{print $2}' | grep -E '\.py$' || true)"
if [ -z "$files" ]; then
  exit 0
fi
bad=0
for f in $files; do
  if [ -f "$f" ]; then
    if ! python3 -m py_compile "$f" 2>/tmp/coagent_pyc.err; then
      echo "SYNTAX ERROR in $f:" >&2
      cat /tmp/coagent_pyc.err >&2
      bad=1
    fi
  fi
done
exit $bad
