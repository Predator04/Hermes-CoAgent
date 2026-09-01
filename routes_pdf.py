"""PDF AcroForm routes: read, fill, and flatten PDF form fields.

The write-side complement to `/doc/extract` and `/doc/table`.

Endpoints:
  POST /pdf/fields   - list AcroForm fields (name, type, value, default,
                       options, flags, read-only/required)
  POST /pdf/fill     - set field values by name; returns the filled PDF
  POST /pdf/flatten  - fill (optional) then flatten to a static, non-editable PDF

Input (all endpoints, JSON body):
  {"path": "C:/x.pdf"}                    local file path, or
  {"data": "<base64>", "filename": "x"}   inline bytes + filename hint

  /pdf/fill and /pdf/flatten additionally accept:
    {"fields": {"name": "value", ...}}    flat field-name -> value map
    {"output": "C:/out.pdf"}              optional output path (defaults to
                                           returning the PDF as base64)

Field values:
  - text / choice fields take a plain string.
  - checkbox / radio buttons take the export state name (e.g. "Yes", "/On",
    "/Off"); use `/pdf/fields` to discover the available states. A boolean
    true/false is also accepted (true -> first on-state, false -> /Off).
  - field names are matched exact-first, then case-insensitively, then with
    spaces/underscores/hyphens normalized so "customer_name" matches the
    field "Customer Name".

Implemented headlessly with pypdf (a dependency already used by
routes_doc_intel). pypdf is imported inside try/except so the Linux
syntax-check CI stays green and hosts without pypdf get a clean 501.
"""

import base64
import os
import re
import tempfile

from flask import jsonify

from shared import _json_body, _log, _missing_field, _sanitize_path

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    from pypdf.generic import NameObject, ArrayObject  # type: ignore
    _HAS_PYPDF = True
except Exception:
    PdfReader = PdfWriter = NameObject = ArrayObject = None  # type: ignore
    _HAS_PYPDF = False

_MAX_INLINE_BYTES = 32 * 1024 * 1024  # 32 MB cap for base64 payloads

# Field flag bits (PDF spec, /Ff)
_FLAG_READONLY = 1
_FLAG_REQUIRED = 2
_FLAG_MULTILINE = 1 << 12      # 4096
_FLAG_PASSWORD = 1 << 13       # 8192
_FLAG_RADIO = 1 << 15          # 32768  (buttons: radio group)
_FLAG_PUSHBUTTON = 1 << 16     # 65536  (buttons: push button)
_FLAG_COMBO = 1 << 17          # 131072 (choice: combo vs list)

_BUTTON_OFF = "/Off"


# ---------------------------------------------------------------------------
# Input resolution (mirrors routes_doc_intel._resolve_source so this module
# stays fully self-contained and independent of import order).
# ---------------------------------------------------------------------------
def _resolve_pdf_source(body):
    """Return (path_or_None, tmp_path_or_None, filename, error_response)."""
    path = body.get("path") or body.get("file")
    data_b64 = body.get("data")
    filename = (body.get("filename") or "").strip()

    if path:
        path = str(path)
        if not os.path.isfile(path):
            return None, None, None, (jsonify({"error": f"file not found: {path}"}), 404)
        return path, None, filename or os.path.basename(path), None

    if data_b64:
        if not filename:
            return None, None, None, (
                jsonify({"error": "filename required when using base64 data"}), 400,
            )
        encoded_len = len(str(data_b64))
        if encoded_len > (_MAX_INLINE_BYTES * 4 // 3) + 4:
            return None, None, None, (
                jsonify({"error": "payload too large",
                         "detail": f"encoded {encoded_len} bytes exceeds limit"}), 413,
            )
        try:
            raw = base64.b64decode(str(data_b64), validate=False)
        except Exception as exc:
            return None, None, None, (
                jsonify({"error": f"invalid base64: {exc}"}), 400,
            )
        if len(raw) > _MAX_INLINE_BYTES:
            return None, None, None, (
                jsonify({"error": "payload too large",
                         "detail": f"{len(raw)} > {_MAX_INLINE_BYTES}"}), 413,
            )
        suffix = os.path.splitext(filename)[1] or ".bin"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="pdf_form_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return None, None, None, (
                jsonify({"error": f"tempfile write failed: {exc}"}), 500,
            )
        return tmp_path, tmp_path, filename, None

    return None, None, None, (
        jsonify({"error": "provide 'path', 'file', or 'data' (base64 with 'filename')"}), 400,
    )


# ---------------------------------------------------------------------------
# Field introspection helpers
# ---------------------------------------------------------------------------
def _scalar(value):
    """Turn a pypdf PdfObject scalar into a plain Python value."""
    if value is None:
        return None
    s = str(value)
    # Name objects surface with a leading slash.
    if isinstance(value, type(None)):
        return None
    return s


def _field_type(ft):
    if ft is None:
        return "unknown"
    ft = str(ft)
    return {
        "/Tx": "text",
        "/Btn": "button",
        "/Ch": "choice",
        "/Sig": "signature",
    }.get(ft, ft.lstrip("/"))


def _field_options(field):
    """Extract /Opt choices (text or [export, display] pairs)."""
    try:
        opt = field.get("/Opt")
    except Exception:
        opt = None
    if opt is None:
        return None
    out = []
    try:
        for item in opt:
            if isinstance(item, (list, tuple)):
                # [export, display] pair
                if len(item) >= 2:
                    out.append({"value": str(item[0]), "label": str(item[1])})
                elif len(item) == 1:
                    out.append({"value": str(item[0]), "label": str(item[0])})
            else:
                out.append({"value": str(item), "label": str(item)})
    except Exception:
        return None
    return out or None


def _button_states(field):
    """Discover the on/off appearance states for a button field."""
    states = []
    try:
        ap = field.get("/AP")
        if ap is not None:
            normal = ap.get("/N")
            if normal is not None:
                for key in normal.keys():
                    states.append(str(key))
    except Exception:
        pass
    # Fall back to /Opt-derived values if no appearance states are present.
    if not states:
        opts = _field_options(field)
        if opts:
            states = [o["value"] for o in opts]
    return states


def _field_to_dict(name, field):
    flags = 0
    try:
        raw_flags = field.get("/Ff")
        if raw_flags is not None:
            flags = int(raw_flags)
    except Exception:
        flags = 0

    ft = str(field.field_type) if getattr(field, "field_type", None) is not None else None
    ftype = _field_type(ft)

    try:
        value = _scalar(field.value)
    except Exception:
        value = None
    try:
        default = _scalar(field.default_value)
    except Exception:
        default = None

    info = {
        "name": name,
        "type": ftype,
        "value": value,
        "default": default,
        "options": _field_options(field),
        "flags": flags,
        "readonly": bool(flags & _FLAG_READONLY),
        "required": bool(flags & _FLAG_REQUIRED),
    }
    if ftype == "button":
        info["radio"] = bool(flags & _FLAG_RADIO)
        info["push_button"] = bool(flags & _FLAG_PUSHBUTTON)
        info["states"] = _button_states(field)
    elif ftype == "choice":
        info["combo"] = bool(flags & _FLAG_COMBO)
    elif ftype == "text":
        info["multiline"] = bool(flags & _FLAG_MULTILINE)
        info["password"] = bool(flags & _FLAG_PASSWORD)
    return info


def _list_fields(reader):
    fields = reader.get_fields()
    if not fields:
        return []
    result = []
    for name, field in fields.items():
        try:
            result.append(_field_to_dict(name, field))
        except Exception as exc:
            _log(f"pdf/fields skipping field {name!r}: {type(exc).__name__}: {exc}")
    return result


# ---------------------------------------------------------------------------
# Field-name matching (exact -> case-insensitive -> normalized)
# ---------------------------------------------------------------------------
def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).casefold())


def _match_fields(field_names, wanted):
    """Return {actual_field_name: value} after fuzzy-matching wanted keys."""
    wanted = {str(k): v for k, v in (wanted or {}).items()}
    if not wanted:
        return {}, {}

    by_exact = {n: n for n in field_names}
    by_lower = {n.casefold(): n for n in field_names}
    by_norm = {_norm_key(n): n for n in field_names}

    matched = {}
    unmatched = {}
    for want, value in wanted.items():
        if want in by_exact:
            matched[by_exact[want]] = value
        elif want.casefold() in by_lower:
            matched[by_lower[want.casefold()]] = value
        elif _norm_key(want) in by_norm:
            matched[by_norm[_norm_key(want)]] = value
        else:
            unmatched[want] = value
    return matched, unmatched


def _normalize_button_value(value, states):
    """Coerce a button value into a valid appearance-state name string."""
    if isinstance(value, bool):
        if value:
            # Prefer the first non-/Off state, else the first state.
            for s in states:
                if s != _BUTTON_OFF:
                    return s
            return states[0] if states else "/Yes"
        return _BUTTON_OFF
    s = str(value)
    if s == "":
        return _BUTTON_OFF
    if s == _BUTTON_OFF:
        return s
    # If we know the states and the value is not among them, try a tolerant match.
    if states:
        norm = _norm_key(s)
        for st in states:
            if _norm_key(st) == norm:
                return st
    return s


def _prepare_fill(field_infos, wanted):
    """Return (fill_map, matched_names, unmatched)."""
    names = [f["name"] for f in field_infos]
    matched, unmatched = _match_fields(names, wanted)

    # Normalize button values against the field's discovered states.
    by_name = {f["name"]: f for f in field_infos}
    fill_map = {}
    for actual, value in matched.items():
        info = by_name.get(actual, {})
        if info.get("type") == "button":
            fill_map[actual] = _normalize_button_value(value, info.get("states") or [])
        else:
            fill_map[actual] = value
    return fill_map, list(matched.keys()), unmatched


def _apply_fill(reader, fill_map, flatten):
    """Best-effort field fill.

    Returns (writer, skipped) where `skipped` is a list of button fields that
    could not be filled (e.g. a malformed form missing the button's appearance
    stream /AP). Text/choice fields always fill cleanly; buttons are filled one
    at a time so a single bad button never aborts the rest of the document.
    """
    info = {f["name"]: f for f in _list_fields(reader)}
    text_choice = {}
    buttons = {}
    for name, value in fill_map.items():
        if info.get(name, {}).get("type") == "button":
            buttons[name] = value
        else:
            text_choice[name] = value

    writer = PdfWriter(clone_from=reader)

    if text_choice:
        writer.update_page_form_field_values(None, text_choice, flatten=flatten)

    skipped = []
    for name, value in buttons.items():
        try:
            writer.update_page_form_field_values(None, {name: value}, flatten=flatten)
        except Exception as exc:
            skipped.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
            _log(f"pdf fill: button {name!r} skipped: {exc}")
    return writer, skipped


def _write_output(writer, output_path, source_filename):
    """Write the PDF and return (payload_dict, status)."""
    if output_path:
        try:
            out = _sanitize_path(output_path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        try:
            with open(out, "wb") as fh:
                writer.write(fh)
        except OSError as exc:
            return {"ok": False, "error": f"write failed: {exc}"}, 500
        return {"ok": True, "path": out, "filename": os.path.basename(out)}, 200

    buf = tempfile.TemporaryFile()
    try:
        writer.write(buf)
        buf.seek(0)
        data = buf.read()
    finally:
        buf.close()
    base = os.path.splitext(os.path.basename(source_filename or "filled.pdf"))[0]
    return {
        "ok": True,
        "data": base64.b64encode(data).decode("ascii"),
        "filename": f"{base}.pdf",
        "bytes": len(data),
    }, 200


def _strip_form(writer):
    """Remove the AcroForm and widget annotations to make the PDF static."""
    # Drop the catalog's /AcroForm entry.
    root = writer._root_object
    if "/AcroForm" in root:
        del root["/AcroForm"]
    # Drop /Widget annotations from every page.
    for page in writer.pages:
        annots = page.get("/Annots")
        if annots is None:
            continue
        kept = [a for a in annots if str(a.get_object().get("/Subtype", "")) != "/Widget"]
        if kept:
            page[NameObject("/Annots")] = ArrayObject(kept)
        elif "/Annots" in page:
            del page["/Annots"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
def register_routes(app, state, require_auth):

    def _load_reader(body):
        if not _HAS_PYPDF:
            return None, None, None, (
                jsonify({"ok": False,
                         "error": "pypdf not installed (pip install pypdf)"}), 501,
            )
        source_path, tmp_path, filename, err = _resolve_pdf_source(body)
        if err:
            return None, None, None, err
        try:
            reader = PdfReader(source_path)
        except Exception as exc:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return None, None, None, (
                jsonify({"ok": False,
                         "error": f"could not open PDF: {type(exc).__name__}: {exc}"}), 400,
            )
        return reader, tmp_path, filename, None

    @app.route("/pdf/fields", methods=["POST"])
    @require_auth
    def route_pdf_fields():
        body = _json_body() or {}
        reader, tmp_path, filename, err = _load_reader(body)
        if err:
            return err
        try:
            fields = _list_fields(reader)
            if not fields:
                return jsonify({
                    "ok": True,
                    "filename": filename,
                    "count": 0,
                    "fields": [],
                    "hint": "no AcroForm fields found in this PDF",
                })
            return jsonify({
                "ok": True,
                "filename": filename,
                "count": len(fields),
                "fields": fields,
            })
        except Exception as exc:
            return jsonify({"ok": False,
                            "error": f"{type(exc).__name__}: {exc}"}), 500
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.route("/pdf/fill", methods=["POST"])
    @require_auth
    def route_pdf_fill():
        body = _json_body() or {}
        reader, tmp_path, filename, err = _load_reader(body)
        if err:
            return err
        try:
            fields = _list_fields(reader)
            if not fields:
                return jsonify({"ok": False,
                                "error": "no AcroForm fields found in this PDF"}), 400
            fill_map, matched, unmatched = _prepare_fill(fields, body.get("fields"))
            if not fill_map:
                return jsonify({"ok": False,
                                "error": "no fields matched",
                                "unmatched": unmatched}), 400
            writer, skipped = _apply_fill(reader, fill_map, flatten=False)
            payload, status = _write_output(writer, body.get("output"), filename)
            payload["filled"] = matched
            payload["unmatched"] = unmatched
            payload["skipped"] = skipped
            return jsonify(payload), status
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.route("/pdf/flatten", methods=["POST"])
    @require_auth
    def route_pdf_flatten():
        body = _json_body() or {}
        reader, tmp_path, filename, err = _load_reader(body)
        if err:
            return err
        try:
            fields = _list_fields(reader)
            if not fields:
                return jsonify({"ok": False,
                                "error": "no AcroForm fields found in this PDF"}), 400
            wanted = body.get("fields") or {}
            if wanted:
                fill_map, matched, unmatched = _prepare_fill(fields, wanted)
            else:
                # Flatten an already-filled form: bake the existing /V values.
                fill_map = {}
                for f in fields:
                    v = f.get("value")
                    if v in (None, "", "/Off"):
                        continue
                    fill_map[f["name"]] = v
                matched = list(fill_map.keys())
                unmatched = {}
            writer, skipped = _apply_fill(reader, fill_map, flatten=True)
            _strip_form(writer)
            payload, status = _write_output(writer, body.get("output"), filename)
            payload["filled"] = matched
            payload["unmatched"] = unmatched
            payload["skipped"] = skipped
            payload["flattened"] = True
            return jsonify(payload), status
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
