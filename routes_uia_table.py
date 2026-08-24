"""UIA data table / grid extraction routes.

Endpoint:
  POST /uia/table  - extract structured JSON from any Windows app grid/table

The extractor first attempts to use the UIA GridPattern (with the TablePattern
providing column headers when available), then falls back to enumerating row
and cell descendants by control type. Reuses the pywinauto backend already
initialized by :mod:`uia_engine` so we share one COM apartment/snapshot cache.

Windows-only dependencies are imported lazily inside try/except so the Linux
syntax-check CI does not fail when pywinauto/comtypes are missing.
"""

import os
import sys

from flask import jsonify

from shared import _json_body, _log, _missing_field, COAGENT_DIR


_ROW_CONTROL_TYPES = {
    "dataitem", "listitem", "row", "treeitem", "gridrow", "custom",
}
_CELL_CONTROL_TYPES = {
    "text", "edit", "hyperlink", "button", "image", "checkbox",
    "dataitem", "custom", "cell", "headeritem",
}
_HEADER_CONTROL_TYPES = {"header", "headeritem"}
_TABLE_CONTROL_TYPES = {
    "table", "datagrid", "grid", "list", "tree", "listview", "gridview",
}


def _get_uia_engine():
    if str(COAGENT_DIR) not in sys.path:
        sys.path.insert(0, str(COAGENT_DIR))
    import uia_engine as ue  # noqa: F401 — Windows-only side effects
    return ue


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _norm_ct(value):
    """Normalize a control_type string to its short lower-case suffix."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _element_text(elem):
    """Best-effort readable text for a UIA element (name -> value -> title)."""
    for attr in ("window_text",):
        try:
            fn = getattr(elem, attr, None)
            if callable(fn):
                text = fn()
                if text:
                    return str(text)
        except Exception:
            pass
    try:
        info = getattr(elem, "element_info", None)
        if info is not None:
            name = getattr(info, "name", "") or ""
            if name:
                return str(name)
    except Exception:
        pass
    try:
        val_iface = getattr(elem, "iface_value", None)
        if val_iface is not None:
            v = val_iface.CurrentValue
            if v:
                return str(v)
    except Exception:
        pass
    try:
        legacy = getattr(elem, "legacy_properties", None)
        if callable(legacy):
            props = legacy() or {}
            v = props.get("Value") or props.get("Name") or ""
            if v:
                return str(v)
    except Exception:
        pass
    return ""


def _wrap_raw_element(raw_elem):
    """Wrap a raw IUIAutomationElement returned by GridPattern.GetItem()."""
    try:
        from pywinauto.uia_element_info import UIAElementInfo
        from pywinauto.controls.uiawrapper import UIAWrapper
    except Exception:
        return None
    try:
        info = UIAElementInfo(raw_elem)
        return UIAWrapper(info)
    except Exception:
        return None


def _find_table_element(desktop, window_title, selector, automation_id, control_type_hint):
    """Locate the target grid/table wrapper element."""
    needle_win = (window_title or "").strip().lower()
    needle_sel = (selector or "").strip().lower()
    needle_aid = (automation_id or "").strip().lower()
    ct_hint = _norm_ct(control_type_hint)

    windows = []
    try:
        windows = list(desktop.windows())
    except Exception as exc:
        return None, f"desktop.windows() failed: {type(exc).__name__}: {exc}"

    target_windows = []
    if needle_win:
        for win in windows:
            try:
                name = (win.element_info.name or "").lower()
            except Exception:
                continue
            if needle_win in name:
                target_windows.append(win)
    else:
        target_windows = windows[:20]

    if not target_windows:
        return None, f"window {window_title!r} not found"

    def _matches(elem):
        try:
            info = elem.element_info
            ct = _norm_ct(info.control_type)
            name = (info.name or "").lower()
            aid = (info.automation_id or "").lower()
        except Exception:
            return False
        if needle_aid and needle_aid == aid:
            return True
        if ct_hint and ct_hint == ct:
            if needle_sel:
                return needle_sel in name or needle_sel in aid
            return True
        if needle_sel:
            if needle_sel in name or needle_sel in aid:
                return ct in _TABLE_CONTROL_TYPES
            return False
        return ct in _TABLE_CONTROL_TYPES

    for win in target_windows:
        try:
            if _matches(win):
                return win, None
        except Exception:
            pass
        try:
            descendants = win.descendants()
        except Exception:
            descendants = []
        for elem in descendants:
            try:
                if _matches(elem):
                    return elem, None
            except Exception:
                continue

    hint_parts = []
    if needle_sel:
        hint_parts.append(f"selector={selector!r}")
    if needle_aid:
        hint_parts.append(f"automation_id={automation_id!r}")
    if ct_hint:
        hint_parts.append(f"control_type={control_type_hint!r}")
    return None, "no table/grid element matched " + (", ".join(hint_parts) or "any table")


def _extract_via_grid_pattern(element, max_rows, max_cols):
    """Try to extract cells via GridPattern; return (table_dict, err)."""
    try:
        grid = element.iface_grid
    except Exception:
        return None, "GridPattern not supported"
    try:
        row_count = int(grid.CurrentRowCount)
        col_count = int(grid.CurrentColumnCount)
    except Exception as exc:
        return None, f"grid counts unavailable: {type(exc).__name__}: {exc}"
    if row_count < 0 or col_count < 0:
        return None, f"invalid grid dims rows={row_count} cols={col_count}"

    rows_take = min(row_count, max_rows)
    cols_take = min(col_count, max_cols)
    rows = []
    for r in range(rows_take):
        row = []
        for c in range(cols_take):
            try:
                raw = grid.GetItem(r, c)
            except Exception:
                row.append("")
                continue
            wrapper = _wrap_raw_element(raw)
            if wrapper is None:
                try:
                    row.append(str(raw.CurrentName or ""))
                except Exception:
                    row.append("")
            else:
                row.append(_element_text(wrapper))
        rows.append(row)

    headers = []
    try:
        table = element.iface_table
        headers_raw = table.GetCurrentColumnHeaders() or []
        for raw in headers_raw:
            wrapper = _wrap_raw_element(raw)
            if wrapper is not None:
                headers.append(_element_text(wrapper))
            else:
                try:
                    headers.append(str(raw.CurrentName or ""))
                except Exception:
                    headers.append("")
    except Exception:
        headers = []

    return {
        "method": "grid_pattern",
        "row_count": row_count,
        "column_count": col_count,
        "truncated": row_count > rows_take or col_count > cols_take,
        "headers": headers,
        "rows": rows,
    }, None


def _extract_via_descendants(element, max_rows, max_cols):
    """Fallback: enumerate row-like descendants and their leaf cell children."""
    try:
        descendants = element.descendants()
    except Exception as exc:
        return None, f"descendants unavailable: {type(exc).__name__}: {exc}"

    headers = []
    for elem in descendants:
        try:
            ct = _norm_ct(elem.element_info.control_type)
        except Exception:
            continue
        if ct in _HEADER_CONTROL_TYPES:
            if ct == "headeritem":
                # headeritem is a leaf: its label lives on the element itself,
                # not on child elements.
                text = _element_text(elem)
                if text:
                    headers.append(text)
            else:
                try:
                    for child in elem.children():
                        text = _element_text(child)
                        if text:
                            headers.append(text)
                except Exception:
                    pass
            if headers:
                break

    rows = []
    seen_row_ids = set()
    for elem in descendants:
        try:
            info = elem.element_info
            ct = _norm_ct(info.control_type)
        except Exception:
            continue
        if ct not in _ROW_CONTROL_TYPES:
            continue
        parent_ok = True
        try:
            parent = elem.parent()
            if parent is not None and parent.element_info.control_type_id == info.control_type_id:
                parent_ok = False
        except Exception:
            pass
        if not parent_ok:
            continue

        try:
            rid = tuple(info.runtime_id or ())
        except Exception:
            rid = ()
        if not rid:
            rid = (id(elem),)
        key = (info.name or "", info.automation_id or "", rid)
        if key in seen_row_ids:
            continue
        seen_row_ids.add(key)

        try:
            cell_children = list(elem.children())
        except Exception:
            cell_children = []
        row_cells = []
        for cell in cell_children[:max_cols]:
            row_cells.append(_element_text(cell))
        if not row_cells:
            text = _element_text(elem)
            if text:
                row_cells = [text]
        if row_cells:
            rows.append(row_cells)
        if len(rows) >= max_rows:
            break

    if not rows and not headers:
        return None, "no rows or headers found via descendant enumeration"

    col_count = max((len(r) for r in rows), default=len(headers))
    return {
        "method": "descendants",
        "row_count": len(rows),
        "column_count": col_count,
        "truncated": len(rows) >= max_rows,
        "headers": headers,
        "rows": rows,
    }, None


def _rows_as_objects(headers, rows):
    if not headers:
        return None
    objects = []
    for row in rows:
        obj = {}
        for i, cell in enumerate(row):
            key = headers[i] if i < len(headers) and headers[i] else f"col_{i}"
            obj[key] = cell
        objects.append(obj)
    return objects


def register_routes(app, state, require_auth):

    @app.route("/uia/table", methods=["POST"])
    @require_auth
    def route_uia_table():
        if os.name != "nt":
            return _windows_only()

        body = _json_body() if callable(_json_body) else {}
        if not isinstance(body, dict):
            body = {}
        window_title = str(body.get("window") or body.get("title") or "").strip()
        selector = str(body.get("selector") or body.get("name") or "").strip()
        automation_id = str(body.get("automation_id") or "").strip()
        control_type = str(body.get("control_type") or body.get("type") or "").strip()
        try:
            max_rows = max(1, min(int(body.get("max_rows", 500)), 5000))
        except (TypeError, ValueError):
            max_rows = 500
        try:
            max_cols = max(1, min(int(body.get("max_cols", 64)), 256))
        except (TypeError, ValueError):
            max_cols = 64
        as_objects = bool(body.get("as_objects", False))

        if not (window_title or selector or automation_id or control_type):
            return _missing_field("window or selector or automation_id or control_type")

        try:
            ue = _get_uia_engine()
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "uia_engine unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
            }), 500

        if not getattr(ue, "UIA_READY", False):
            return jsonify({
                "ok": False,
                "error": "UIA not ready",
                "detail": getattr(ue, "_uia_error", "") or "pywinauto uia backend unavailable",
                "code": "UIA_NOT_READY",
            }), 503

        try:
            from pywinauto import Desktop as PyWinDesktop
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "pywinauto import failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }), 500

        try:
            desktop = PyWinDesktop(backend="uia")
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "desktop init failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }), 500

        element, err = _find_table_element(
            desktop, window_title, selector, automation_id, control_type,
        )
        if element is None:
            return jsonify({
                "ok": False,
                "error": "element not found",
                "detail": err,
                "code": "TABLE_NOT_FOUND",
            }), 404

        try:
            info = element.element_info
            found_meta = {
                "name": info.name or "",
                "automation_id": info.automation_id or "",
                "control_type": info.control_type or "",
                "class_name": info.class_name or "",
            }
        except Exception:
            found_meta = {}

        table, gp_err = _extract_via_grid_pattern(element, max_rows, max_cols)
        fallback_err = None
        if table is None:
            table, fallback_err = _extract_via_descendants(element, max_rows, max_cols)
        if table is None:
            _log(f"[uia_table] extraction failed grid={gp_err} desc={fallback_err}")
            return jsonify({
                "ok": False,
                "error": "extraction failed",
                "grid_pattern_error": gp_err,
                "descendants_error": fallback_err,
                "element": found_meta,
            }), 500

        response = {
            "ok": True,
            "element": found_meta,
            "table": table,
        }
        if as_objects:
            objects = _rows_as_objects(table.get("headers") or [], table.get("rows") or [])
            if objects is not None:
                response["table"]["row_objects"] = objects
        return jsonify(response)
