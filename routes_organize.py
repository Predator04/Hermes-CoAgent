"""Smart file organization & cleanup routes.

Endpoints:
  POST /organize/preview - dry-run scan of a directory; returns a proposed
                           move/rename/duplicate/clutter plan as JSON. No action.
  POST /organize/apply   - execute a previously-previewed plan (moves + renames
                           only by default). Collision-safe; every applied move
                           is recorded to COAGENT_DIR/organize_history/ for
                           reversibility.

Design:
  - Pure-stdlib (os / shutil / hashlib / mimetypes) so it works headless on any
    host and never breaks the Linux syntax-check CI.
  - Rule engine buckets files by extension into category subfolders
    (Images / Documents / Archives / Audio / Video / Installers / Code / Fonts).
  - Optional rename templates (e.g. "Screenshot-YYYYMMDD-HHMMSS{ext}").
  - Duplicate detection groups same-size files and hashes within a group; only
    one copy is kept, the rest are surfaced (moved only with explicit opt-in).
  - Clutter (temp / lock / partial files) is surfaced for review, never deleted
    or moved unless the caller explicitly opts in.
  - /organize/apply re-validates every action and refuses targets that escape
    the scanned directory.
"""

import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field

_HISTORY_DIR = Path(COAGENT_DIR) / "organize_history"
_PLAN_LOCK = threading.RLock()

# Extension -> category. Kept pure-ASCII. Files whose extension is not listed
# are left in place (category None) so the organizer is conservative by default.
CATEGORIES = {
    "Images": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tif",
        ".tiff", ".heic", ".ico", ".raw", ".cr2", ".nef",
    },
    "Documents": {
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".xls",
        ".xlsx", ".xlsm", ".csv", ".ppt", ".pptx", ".odp", ".ods", ".epub",
        ".pages", ".numbers", ".key",
    },
    "Archives": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab",
        ".dmg", ".apk", ".jar",
    },
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "Video": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
        ".mpg", ".mpeg", ".ts",
    },
    "Installers": {".exe", ".msi", ".pkg", ".deb", ".rpm", ".appx", ".msix"},
    "Code": {
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
        ".go", ".rs", ".rb", ".php", ".html", ".css", ".json", ".xml",
        ".yml", ".yaml", ".sh", ".ps1", ".sql", ".ipynb", ".toml", ".ini",
    },
    "Fonts": {".ttf", ".otf", ".woff", ".woff2", ".eot"},
}

# Files we flag as clutter but never touch by default.
_CLUTTER_EXTS = {".tmp", ".temp", ".bak", ".old", ".crdownload", ".part", ".dmp"}
_CLUTTER_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}

_TEMP_FILE_RE = re.compile(r"^~\$")  # Office lock files like "~$report.docx"


def _category_for(path: Path) -> str:
    ext = path.suffix.lower()
    if not ext:
        return "NoExtension"
    for category, exts in CATEGORIES.items():
        if ext in exts:
            return category
    return "Other"


def _is_clutter(path: Path) -> str:
    """Return a reason string if the file looks like clutter, else ""."""
    name = path.name
    if name.lower() in _CLUTTER_NAMES:
        return f"system clutter ({name})"
    if _TEMP_FILE_RE.match(name):
        return "Office lock/temp file"
    if path.suffix.lower() in _CLUTTER_EXTS:
        return f"temp/backup file ({path.suffix.lower()})"
    return ""


def _safe_target(base: Path, target: Path) -> bool:
    """Return True only if target stays within base (allows new subdirs)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _unique_target(target: Path) -> Path:
    """Append (1), (2), ... when the target already exists."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    parent = target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _mtime_safe(path: Path) -> float:
    """Return a path's mtime, or 0.0 if it vanished/raised (mid-scan delete)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _format_rename(template: str, path: Path, mtime: float) -> str:
    """Apply a rename template. Supports {name}, {ext}, {date}, {ts}."""
    dt = datetime.fromtimestamp(mtime)
    out = template
    out = out.replace("{name}", path.stem)
    out = out.replace("{ext}", path.suffix)
    out = out.replace("{date}", dt.strftime("%Y%m%d"))
    out = out.replace("{ts}", dt.strftime("%Y%m%d-%H%M%S"))
    return out


def _scan(directory: Path, rename_template: str = "", sort_by_category: bool = True):
    """Walk a directory (non-recursive by default) and build a plan."""
    actions = []
    if not directory.is_dir():
        return None, "directory not found"

    files = [p for p in directory.iterdir() if p.is_file()]

    # -- category / rename moves -----------------------------------------
    for path in files:
        # Clutter (lock/temp/backup files) is surfaced for review only and is
        # never silently moved or renamed.
        if _is_clutter(path):
            continue
        category = _category_for(path)
        is_known = category not in ("Other", "NoExtension")
        # Unknown-category files stay in place unless a rename template is set.
        if sort_by_category and not is_known and not rename_template:
            continue
        new_name = path.name
        if rename_template:
            try:
                new_name = _format_rename(rename_template, path, path.stat().st_mtime)
            except (OSError, ValueError):
                new_name = path.name
        if sort_by_category and is_known:
            target_dir = directory / category
            atype = "move"
            reason = f"category:{category}" + ("+rename" if rename_template else "")
        else:
            target_dir = directory
            atype = "rename"
            reason = "rename-template"
        target = target_dir / new_name
        if target.resolve() == path.resolve():
            continue
        actions.append({
            "type": atype,
            "from": str(path),
            "to": str(_unique_target(target)),
            "reason": reason,
            "category": category,
        })

    # -- clutter (surface only) -------------------------------------------
    for path in files:
        reason = _is_clutter(path)
        if reason:
            actions.append({
                "type": "clutter",
                "from": str(path),
                "reason": reason,
                "suggested_action": "review",
            })

    # -- duplicates --------------------------------------------------------
    by_size = defaultdict(list)
    for path in files:
        try:
            by_size[path.stat().st_size].append(path)
        except OSError:
            continue
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        by_hash = defaultdict(list)
        for path in group:
            try:
                h = hashlib.sha256()
                with path.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                digest = h.hexdigest()
            except (OSError, MemoryError):
                # Huge/unreadable file: use a unique per-file sentinel so two
                # *different* unreadable files can never be grouped as duplicates
                # (which would otherwise move one and cause data loss).
                digest = f"unhashable:{size}:{path.name.lower()}:{str(path)}"
            by_hash[digest].append(path)
        for digest, dupes in by_hash.items():
            if len(dupes) < 2:
                continue
            keep = sorted(dupes, key=lambda p: (_mtime_safe(p), str(p)))[0]
            for dup in dupes:
                if dup.resolve() == keep.resolve():
                    continue
                actions.append({
                    "type": "duplicate",
                    "from": str(dup),
                    "keep": str(keep),
                    "reason": "sha256 match",
                })

    summary = defaultdict(int)
    for action in actions:
        summary[action["type"]] += 1
    return {
        "directory": str(directory),
        "scanned": len(files),
        "summary": dict(summary),
        "actions": actions,
    }, None


def _write_history(actions):
    """Record applied actions for reversibility. Returns the manifest path."""
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest = _HISTORY_DIR / f"apply-{stamp}.json"
    try:
        manifest.write_text(json.dumps({
            "applied_at": datetime.now().isoformat(),
            "actions": actions,
        }, indent=2), encoding="utf-8")
        return str(manifest)
    except OSError:
        return ""


def _apply_actions(directory: Path, actions, include_duplicates=False,
                   include_clutter=False):
    """Execute move/rename actions. Returns (applied, skipped, errors)."""
    applied = []
    skipped = []
    errors = []

    for action in actions:
        atype = action.get("type")
        if atype == "duplicate":
            if not include_duplicates:
                skipped.append({**action, "why": "duplicates require opt-in"})
                continue
            src_raw = action.get("from")
            if not src_raw:
                skipped.append({**action, "why": "missing from"})
                continue
            src = Path(src_raw)
            if not _safe_target(directory, src):
                errors.append({**action, "why": "source escapes scan directory"})
                continue
            if not src.is_file():
                skipped.append({**action, "why": "source no longer exists"})
                continue
            dup_dir = directory / "Duplicates"
            try:
                dup_dir.mkdir(parents=True, exist_ok=True)
                final = _unique_target(dup_dir / src.name)
                shutil.move(str(src), str(final))
                applied.append({
                    "type": "duplicate", "from": str(src), "to": str(final),
                    "keep": action.get("keep"),
                })
            except (OSError, shutil.Error) as exc:
                errors.append({**action, "why": str(exc)})
            continue
        if atype == "clutter":
            if not include_clutter:
                skipped.append({**action, "why": "clutter requires opt-in"})
            else:
                skipped.append({**action, "why": "clutter is review-only, not deleted"})
            continue
        if atype not in ("move", "rename"):
            skipped.append({**action, "why": f"unsupported type {atype}"})
            continue

        src_raw = action.get("from")
        dst_raw = action.get("to")
        if not src_raw or not dst_raw:
            skipped.append({**action, "why": "missing from/to"})
            continue
        src = Path(src_raw)
        dst = Path(dst_raw)
        if not _safe_target(directory, dst):
            errors.append({**action, "why": "target escapes scan directory"})
            continue
        if not _safe_target(directory, src):
            errors.append({**action, "why": "source escapes scan directory"})
            continue
        if not src.is_file():
            skipped.append({**action, "why": "source no longer exists"})
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            final = _unique_target(dst)
            shutil.move(str(src), str(final))
            applied.append({"type": atype, "from": str(src), "to": str(final)})
        except (OSError, shutil.Error) as exc:
            errors.append({**action, "why": str(exc)})

    return applied, skipped, errors


def register_routes(app, state, require_auth):
    @app.route("/organize/preview", methods=["POST"])
    @require_auth
    def route_organize_preview():
        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        raw_path = body.get("path") or body.get("directory")
        if not raw_path:
            return _missing_field("path")
        if not isinstance(raw_path, str):
            return jsonify({"error": "path must be a string"}), 400

        try:
            directory = Path(os.path.expanduser(raw_path)).resolve()
        except (OSError, ValueError) as exc:
            return jsonify({"error": f"invalid path: {exc}"}), 400
        if not directory.is_dir():
            return jsonify({"error": "directory not found", "path": str(directory)}), 404

        rename_template = body.get("rename_template") or body.get("rename") or ""
        sort_by_category = bool(body.get("sort_by_category", True))

        plan, err = _scan(directory, rename_template=rename_template,
                          sort_by_category=sort_by_category)
        if err:
            return jsonify({"error": err}), 400

        _log(f"organize/preview path={directory} scanned={plan['scanned']} "
             f"actions={len(plan['actions'])}")
        return jsonify(plan)

    @app.route("/organize/apply", methods=["POST"])
    @require_auth
    def route_organize_apply():
        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        raw_path = body.get("path") or body.get("directory")
        actions = body.get("actions")
        if not raw_path or actions is None:
            return _missing_field("path" if not raw_path else "actions")
        if not isinstance(actions, list):
            return jsonify({"error": "actions must be a list"}), 400

        try:
            directory = Path(os.path.expanduser(raw_path)).resolve()
        except (OSError, ValueError) as exc:
            return jsonify({"error": f"invalid path: {exc}"}), 400
        if not directory.is_dir():
            return jsonify({"error": "directory not found", "path": str(directory)}), 404

        include_duplicates = bool(body.get("include_duplicates", False))
        include_clutter = bool(body.get("include_clutter", False))

        with _PLAN_LOCK:
            applied, skipped, errors = _apply_actions(
                directory, actions,
                include_duplicates=include_duplicates,
                include_clutter=include_clutter,
            )

        manifest = _write_history(applied) if applied else ""
        _log(f"organize/apply applied={len(applied)} skipped={len(skipped)} "
             f"errors={len(errors)}")
        return jsonify({
            "status": "ok",
            "applied": applied,
            "applied_count": len(applied),
            "skipped": skipped,
            "skipped_count": len(skipped),
            "errors": errors,
            "error_count": len(errors),
            "manifest": manifest,
        })
