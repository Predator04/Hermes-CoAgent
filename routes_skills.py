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
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

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
        mtime = skill_md.stat().st_mtime
        raw = skill_md.read_text(encoding="utf-8", errors="replace")
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
# Import: scan third-party tool skill folders and copy SKILL.md packages
# into the CoAgent skills registry.
# ---------------------------------------------------------------------------

_IMPORT_MAX_DEPTH = 6
_IMPORT_MAX_SKILL_MD = 500        # hard cap on SKILL.md files scanned per request
_IMPORT_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def _known_source_paths() -> List[Tuple[str, Path]]:
    """Well-known SKILL.md source folders for Claude Code, Codex, Copilot,
    Cursor. Returns (label, path) pairs regardless of existence — callers
    filter with .is_dir() as needed."""
    home = Path.home()
    cwd = Path.cwd()
    candidates: List[Tuple[str, Path]] = [
        ("claude", home / ".claude" / "skills"),
        ("claude", cwd / ".claude" / "skills"),
        ("codex", home / ".codex" / "skills"),
        ("codex", cwd / ".codex" / "skills"),
        ("copilot", home / ".github" / "copilot" / "skills"),
        ("copilot", cwd / ".github" / "copilot" / "skills"),
        ("cursor", home / ".cursor" / "skills"),
        ("cursor", cwd / ".cursor" / "skills"),
    ]
    # De-duplicate while preserving order.
    seen: set = set()
    out: List[Tuple[str, Path]] = []
    for label, path in candidates:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        out.append((label, path))
    return out


def _iter_skill_md(
    root: Path,
    max_depth: int = _IMPORT_MAX_DEPTH,
    *,
    exclude_realpaths: Optional[Iterable[str]] = None,
    max_files: int = _IMPORT_MAX_SKILL_MD,
) -> Iterator[Path]:
    """Yield SKILL.md files under ``root`` up to ``max_depth`` levels deep.

    Does not follow symlinks. Tracks realpaths of visited directories so
    filesystem cycles (e.g. bind-mount loops, junction points) cannot cause
    an unbounded scan. Prunes any directory whose realpath appears in
    ``exclude_realpaths`` (used to keep the walker out of the destination
    skills root). Caps total yields at ``max_files``.
    """
    if not root.is_dir():
        return
    try:
        root_res = root.resolve()
    except OSError:
        return
    excluded = {os.path.normcase(str(p)) for p in (exclude_realpaths or [])}
    visited: set = set()
    yielded = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        try:
            here_res = Path(dirpath).resolve()
        except OSError:
            dirnames[:] = []
            continue
        here_key = os.path.normcase(str(here_res))
        if here_key in visited or here_key in excluded:
            dirnames[:] = []
            continue
        visited.add(here_key)
        try:
            depth = len(here_res.relative_to(root_res).parts)
        except (ValueError, OSError):
            depth = 0
        if depth > max_depth:
            dirnames[:] = []
            continue
        # Prune excluded and already-visited subdirs before descending.
        pruned = []
        for d in dirnames:
            try:
                child_res = (here_res / d).resolve()
            except OSError:
                continue
            child_key = os.path.normcase(str(child_res))
            if child_key in excluded or child_key in visited:
                continue
            pruned.append(d)
        dirnames[:] = pruned
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"
            yielded += 1
            if yielded >= max_files:
                return


def _sanitize_dir_name(name: str) -> str:
    """Filesystem-safe directory name derived from a skill name."""
    safe = _IMPORT_SAFE_NAME_RE.sub("_", (name or "").strip())
    safe = safe.strip("._-")
    return safe or "skill"


def _copy_skill_package(src_dir: Path, dest_dir: Path) -> int:
    """Copy SKILL.md and any bundled ``scripts/references/assets`` from
    ``src_dir`` into ``dest_dir``. Returns the number of files written."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    src_md = src_dir / "SKILL.md"
    if src_md.is_file() and not src_md.is_symlink():
        shutil.copy2(str(src_md), str(dest_dir / "SKILL.md"), follow_symlinks=False)
        count += 1
    for sub in _BUNDLE_DIRS:
        src_sub = src_dir / sub
        if not src_sub.is_dir() or src_sub.is_symlink():
            continue
        dest_sub = dest_dir / sub
        for root, dirs, files in os.walk(src_sub, followlinks=False):
            rel = Path(root).relative_to(src_sub)
            target_root = dest_sub / rel
            target_root.mkdir(parents=True, exist_ok=True)
            for f in files:
                src_file = Path(root) / f
                if src_file.is_symlink():
                    continue
                shutil.copy2(str(src_file), str(target_root / f), follow_symlinks=False)
                count += 1
                if count >= _MAX_BUNDLE_FILES:
                    return count
    return count


def _import_one(
    src_md: Path,
    dest_root: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    """Parse a candidate SKILL.md and (unless ``dry_run``) copy it into the
    CoAgent skills directory. Returns a per-skill status dict."""
    src_str = str(src_md)
    try:
        raw = src_md.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"src": src_str, "imported": False, "error": f"read failed: {e}"}
    fm, _body = _parse_frontmatter(raw)
    if not fm:
        return {"src": src_str, "imported": False, "error": "no frontmatter"}
    name = _derive_name(src_md, fm)
    if not name:
        return {"src": src_str, "imported": False, "error": "cannot determine name"}
    safe = _sanitize_dir_name(name)
    dest_dir = dest_root / safe
    description = (fm.get("description") or "").strip()
    if len(description) > _DESC_MAX:
        description = description[:_DESC_MAX].rstrip() + "..."
    result: Dict[str, Any] = {
        "src": src_str,
        "name": name,
        "safe_name": safe,
        "description": description,
        "dest": str(dest_dir),
    }
    if dest_dir.exists() and not overwrite:
        result["imported"] = False
        result["skipped"] = True
        result["reason"] = "exists"
        return result
    if dry_run:
        result["imported"] = False
        result["dry_run"] = True
        return result
    try:
        # Confine the copy to the CoAgent skills root.
        dest_root_r = dest_root.resolve()
        dest_r = dest_dir.resolve()
        dest_r.relative_to(dest_root_r)
    except (ValueError, OSError):
        result["imported"] = False
        result["error"] = "destination escapes skills root"
        return result
    if overwrite and dest_dir.exists():
        # Replace, not merge: drop stale files from a prior version so the
        # imported package doesn't retain orphaned scripts/references/assets.
        try:
            if dest_dir.is_symlink() or dest_dir.is_file():
                dest_dir.unlink()
            else:
                shutil.rmtree(dest_dir)
        except OSError as e:
            result["imported"] = False
            result["error"] = f"cannot replace existing skill: {e}"
            return result
    try:
        files = _copy_skill_package(src_md.parent, dest_dir)
    except OSError as e:
        result["imported"] = False
        result["error"] = f"copy failed: {e}"
        return result
    result["imported"] = True
    result["files_copied"] = files
    return result


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

    @app.route("/skills/import", methods=["GET", "POST"])
    @require_auth
    def route_skills_import():
        """Import SKILL.md skill packages from Claude Code, Codex, Copilot
        and Cursor skill folders into the CoAgent skills registry.

        JSON body (all optional):
            sources:   list of directories to scan (defaults to well-known)
            overwrite: bool; replace existing packages with the same name
            dry_run:   bool; report what would be imported, do not copy
        """
        try:
            body: Dict[str, Any] = {}
            raw_body = request.get_json(silent=True)
            if isinstance(raw_body, dict):
                body = raw_body
            overwrite = bool(body.get("overwrite", False))
            # GET requests are always a dry-run preview.
            dry_run = bool(body.get("dry_run", False)) or request.method == "GET"

            raw_sources = body.get("sources")
            sources: List[Tuple[str, Path]] = []
            if isinstance(raw_sources, list) and raw_sources:
                for entry in raw_sources:
                    if not isinstance(entry, str) or not entry.strip():
                        continue
                    try:
                        p = Path(entry).expanduser()
                    except (TypeError, ValueError):
                        continue
                    sources.append(("custom", p))
            else:
                sources = _known_source_paths()

            dest_root = _skills_root()
            try:
                dest_root.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return jsonify({"ok": False, "error": f"cannot create skills dir: {e}"}), 500

            # Resolve the destination once so we can (a) reject sources that
            # are the destination or an ancestor of it (which would recurse
            # into their own output) and (b) prune the destination subtree
            # from any scan whose source happens to contain it.
            try:
                dest_root_res = dest_root.resolve()
            except OSError as e:
                return jsonify({"ok": False, "error": f"cannot resolve skills dir: {e}"}), 500
            dest_key = os.path.normcase(str(dest_root_res))

            results: List[Dict[str, Any]] = []
            scanned: List[Dict[str, Any]] = []
            for label, path in sources:
                info: Dict[str, Any] = {
                    "label": label,
                    "path": str(path),
                    "exists": path.is_dir(),
                }
                scanned.append(info)
                if not info["exists"]:
                    continue

                # Guard: refuse to scan the destination itself or any
                # ancestor of it. Copying from such a path would land the
                # output inside the input, producing recursive copies and
                # potentially an unbounded loop across requests.
                try:
                    src_res = path.resolve()
                except OSError as exc:
                    info["skipped"] = f"resolve failed: {exc}"
                    continue
                src_key = os.path.normcase(str(src_res))
                if src_key == dest_key:
                    info["skipped"] = "source is destination"
                    continue
                try:
                    # Raises ValueError when dest is NOT under src.
                    dest_root_res.relative_to(src_res)
                    info["skipped"] = "source is ancestor of destination"
                    continue
                except ValueError:
                    pass

                found = 0
                for skill_md in _iter_skill_md(
                    path,
                    exclude_realpaths=[dest_root_res],
                ):
                    found += 1
                    entry = _import_one(
                        skill_md,
                        dest_root,
                        overwrite=overwrite,
                        dry_run=dry_run,
                    )
                    entry["source"] = label
                    results.append(entry)
                info["skill_md_count"] = found

            imported = sum(1 for r in results if r.get("imported"))
            skipped = sum(1 for r in results if r.get("skipped"))
            errors = sum(1 for r in results if r.get("error"))
            if imported:
                try:
                    cache.reload()
                except Exception as e:  # noqa: BLE001
                    _log(f"skills.import: reload failed: {e}")

            return jsonify({
                "ok": True,
                "dry_run": dry_run,
                "overwrite": overwrite,
                "sources": scanned,
                "results": results,
                "imported": imported,
                "skipped": skipped,
                "errors": errors,
                "count": len(results),
            })
        except Exception as exc:  # noqa: BLE001
            _log(f"skills.import: unhandled exception: {type(exc).__name__}: {exc}")
            return jsonify({
                "ok": False,
                "error": f"import failed: {type(exc).__name__}: {exc}",
            }), 500

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
