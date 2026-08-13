"""Agent Skills loader — progressive-disclosure skill package endpoints.

Reads Anthropic-style skill packages from ``COAGENT_DIR / "skills"``. A skill
package is a directory (or a standalone ``SKILL.md``) whose ``SKILL.md`` starts
with a YAML frontmatter block (``---`` delimited) declaring at least ``name``
and ``description``.

Endpoints (all ``@require_auth``):

* ``GET  /skills/list``        — metadata-only listing (progressive disclosure)
* ``GET  /skills/<name>``      — full skill body + bundled file listing
* ``POST /skills/reload``      — clear cache and rescan
* ``GET  /skills/search?q=..`` — substring search (name/description/body)

Exposes ``state.skills`` = {"list", "render", "get"} for prompt injection.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from flask import jsonify, request

from shared import COAGENT_DIR, _log


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DESC_LIST_TRUNC = 200            # short description shown in /skills/list
_DESC_MAX = 500                   # hard cap on stored description length
_BUNDLE_DIRS = ("scripts", "references", "assets")
_GENERIC_DIR_NAMES = {"skill", "skills", "."}
_MAX_BUNDLE_FILES = 500           # sanity cap when walking a package
_FRONTMATTER_RE = re.compile(
    r"^\s*---\s*(?:\r?\n)(.*?)(?:\r?\n)---\s*(?:\r?\n)?(.*)$",
    re.DOTALL,
)
# key: value  (value optional so we don't choke on empty lines)
_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*?)\s*$")


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Return (frontmatter_dict, body). Empty dict if no frontmatter."""
    if not text:
        return {}, ""
    # Normalise BOM
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2) or ""
    fm: Dict[str, str] = {}
    current_key: Optional[str] = None
    for raw_line in fm_raw.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            current_key = None
            continue
        kv = _KV_RE.match(line)
        if kv:
            key = kv.group(1).lower()
            val = _strip_quotes(kv.group(2))
            fm[key] = val
            current_key = key
        elif current_key and (raw_line.startswith(" ") or raw_line.startswith("\t")):
            # Folded continuation of previous key
            fm[current_key] = (fm[current_key] + " " + line.strip()).strip()
    return fm, body


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------

def _skills_root() -> Path:
    return Path(COAGENT_DIR) / "skills"


def _safe_relative(base: Path, target: Path) -> Optional[str]:
    """Return POSIX-style path of ``target`` relative to ``base``, or None if
    the target escapes the base (path traversal guard)."""
    try:
        base_r = base.resolve()
        target_r = target.resolve()
        rel = target_r.relative_to(base_r)
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def _list_bundle_files(skill_dir: Path) -> Dict[str, List[str]]:
    """List files under ``scripts/``, ``references/``, ``assets/`` (relative
    paths only). Silently skips traversal attempts and unreadable entries."""
    out: Dict[str, List[str]] = {d: [] for d in _BUNDLE_DIRS}
    if not skill_dir.is_dir():
        return out
    remaining = _MAX_BUNDLE_FILES
    capped = False
    for sub in _BUNDLE_DIRS:
        sub_path = skill_dir / sub
        if not sub_path.is_dir() or sub_path.is_symlink():
            continue
        for root, _dirs, files in os.walk(sub_path, followlinks=False):
            for f in files:
                p = Path(root) / f
                rel = _safe_relative(skill_dir, p)
                if rel is None:
                    continue
                out[sub].append(rel)
                remaining -= 1
                if remaining <= 0:
                    capped = True
                    break
            if capped:
                break
        if capped:
            break
    for k in out:
        out[k].sort()
    return out


def _derive_name(skill_md: Path, fm: Dict[str, str]) -> Optional[str]:
    """Pick a stable skill name. Prefers the directory name unless it is
    generic, in which case the frontmatter ``name`` wins."""
    dir_name = skill_md.parent.name.strip()
    fm_name = (fm.get("name") or "").strip()
    if dir_name and dir_name.lower() not in _GENERIC_DIR_NAMES:
        return dir_name
    if fm_name:
        return fm_name
    if dir_name:
        return dir_name
    return None


def _load_one(skill_md: Path) -> Optional[Dict[str, Any]]:
    """Parse a single SKILL.md file. Returns None on malformed input."""
    # Reject paths that escape the skills root (symlinked SKILL.md or a
    # symlinked directory in the scan path). resolve() follows symlinks.
    try:
        skill_md.resolve().relative_to(_skills_root().resolve())
    except (ValueError, OSError):
        _log(f"skills: path escapes skills root, skipping {skill_md}")
        return None
    try:
        raw = skill_md.read_text(encoding="utf-8", errors="replace")
        mtime = skill_md.stat().st_mtime
    except OSError as e:
        _log(f"skills: cannot read {skill_md}: {e}")
        return None
    fm, body = _parse_frontmatter(raw)
    if not fm:
        _log(f"skills: no frontmatter in {skill_md}, skipping")
        return None
    name = _derive_name(skill_md, fm)
    if not name:
        _log(f"skills: cannot determine name for {skill_md}, skipping")
        return None
    description = (fm.get("description") or "").strip()
    if len(description) > _DESC_MAX:
        description = description[:_DESC_MAX].rstrip() + "..."
    skill_dir = skill_md.parent
    bundle = _list_bundle_files(skill_dir)
    file_count = sum(len(v) for v in bundle.values())
    try:
        rel_path = str(skill_md.resolve().relative_to(Path(COAGENT_DIR).resolve()))
    except (ValueError, OSError):
        # Should be unreachable after the escape guard above; never leak an
        # absolute path into API responses.
        rel_path = skill_md.name
    return {
        "name": name,
        "description": description,
        "body": body.strip("\n"),
        "path": rel_path.replace("\\", "/"),
        "dir": str(skill_dir),
        "mtime": mtime,
        "bundle": bundle,
        "has_scripts": bool(bundle["scripts"]),
        "has_references": bool(bundle["references"]),
        "has_assets": bool(bundle["assets"]),
        "file_count": file_count,
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _SkillCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _scan_locked(self) -> None:
        root = _skills_root()
        if not root.is_dir():
            self._by_name.clear()
            self._loaded = True
            return
        seen: List[Path] = []
        try:
            # os.walk(followlinks=False) — don't descend into symlinked dirs.
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                if "SKILL.md" in filenames:
                    seen.append(Path(dirpath) / "SKILL.md")
        except OSError as e:
            _log(f"skills: scan error under {root}: {e}")
            self._loaded = False
            return
        # Build into a local dict and swap only on success — a transient scan
        # error (or a malformed entry) must not wipe the existing cache.
        built: Dict[str, Dict[str, Any]] = {}
        for skill_md in seen:
            entry = _load_one(skill_md)
            if entry is None:
                continue
            # last-write-wins on duplicate names
            built[entry["name"]] = entry
        self._by_name = built
        self._loaded = True

    def _refresh_stale_locked(self) -> None:
        """Cheap mtime check: reload any SKILL.md whose mtime changed."""
        for name, entry in list(self._by_name.items()):
            path = Path(entry["dir"]) / "SKILL.md"
            try:
                mtime = path.stat().st_mtime
            except OSError:
                # File vanished — drop it
                self._by_name.pop(name, None)
                continue
            if mtime != entry.get("mtime"):
                fresh = _load_one(path)
                if fresh is None:
                    self._by_name.pop(name, None)
                else:
                    self._by_name[fresh["name"]] = fresh

    def ensure_loaded(self) -> None:
        with self._lock:
            if not self._loaded:
                self._scan_locked()
            else:
                self._refresh_stale_locked()

    def reload(self) -> int:
        with self._lock:
            self._scan_locked()
            return len(self._by_name)

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.ensure_loaded()
            return [dict(v) for v in self._by_name.values()]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.ensure_loaded()
            entry = self._by_name.get(name)
            return dict(entry) if entry else None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _metadata(entry: Dict[str, Any], *, short_desc: bool) -> Dict[str, Any]:
    desc = entry.get("description", "") or ""
    if short_desc and len(desc) > _DESC_LIST_TRUNC:
        desc = desc[:_DESC_LIST_TRUNC].rstrip() + "..."
    return {
        "name": entry["name"],
        "description": desc,
        "path": entry.get("path"),
        "has_scripts": entry.get("has_scripts", False),
        "has_references": entry.get("has_references", False),
        "has_assets": entry.get("has_assets", False),
        "file_count": entry.get("file_count", 0),
    }


def _full(entry: Dict[str, Any], *, include_body: bool) -> Dict[str, Any]:
    out = _metadata(entry, short_desc=False)
    out["bundle"] = entry.get("bundle", {d: [] for d in _BUNDLE_DIRS})
    if include_body:
        out["body"] = entry.get("body", "")
    return out


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):
    cache = _SkillCache()

    @app.route("/skills/list", methods=["GET"])
    @require_auth
    def route_skills_list():
        try:
            entries = cache.all()
        except Exception as e:  # noqa: BLE001
            _log(f"skills.list: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500
        skills = [_metadata(e, short_desc=True) for e in entries]
        skills.sort(key=lambda s: s["name"].lower())
        return jsonify({"ok": True, "count": len(skills), "skills": skills})

    @app.route("/skills/<path:name>", methods=["GET"])
    @require_auth
    def route_skills_get(name: str):
        include_body = request.args.get("body", "true").lower() not in ("0", "false", "no")
        entry = cache.get(name)
        if not entry:
            return jsonify({"ok": False, "error": "skill not found", "name": name}), 404
        return jsonify({"ok": True, "skill": _full(entry, include_body=include_body)})

    @app.route("/skills/reload", methods=["POST"])
    @require_auth
    def route_skills_reload():
        try:
            count = cache.reload()
        except Exception as e:  # noqa: BLE001
            _log(f"skills.reload: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "count": count})

    @app.route("/skills/search", methods=["GET"])
    @require_auth
    def route_skills_search():
        q = (request.args.get("q") or "").strip().lower()
        if not q:
            return jsonify({"ok": False, "error": "missing q"}), 400
        entries = cache.all()
        hits: List[Dict[str, Any]] = []
        for e in entries:
            haystack = " ".join([
                e.get("name", ""),
                e.get("description", ""),
                e.get("body", ""),
            ]).lower()
            if q in haystack:
                hits.append(_metadata(e, short_desc=True))
        hits.sort(key=lambda s: s["name"].lower())
        return jsonify({"ok": True, "count": len(hits), "query": q, "skills": hits})

    # ------------------------------------------------------------------
    # Progressive-disclosure prompt-injection helpers on ``state``.
    # ------------------------------------------------------------------

    def _list_metadata() -> List[Dict[str, Any]]:
        return [_metadata(e, short_desc=True) for e in cache.all()]

    def _get_full(name: str) -> Optional[Dict[str, Any]]:
        entry = cache.get(name)
        return _full(entry, include_body=True) if entry else None

    def _render_prompt(prompt: str, skill_names: Iterable[str]) -> str:
        base = prompt or ""
        if not skill_names:
            return base
        parts: List[str] = [base]
        seen: set = set()
        for name in skill_names:
            if not name or name in seen:
                continue
            seen.add(name)
            entry = cache.get(name)
            if not entry:
                continue
            body = (entry.get("body") or "").strip()
            desc = (entry.get("description") or "").strip()
            section = f"\n\n## Skill: {entry['name']}\n{desc}\n\n{body}".rstrip() + "\n"
            parts.append(section)
        return "".join(parts)

    state.skills = {
        "list": _list_metadata,
        "render": _render_prompt,
        "get": _get_full,
        "reload": cache.reload,
    }
