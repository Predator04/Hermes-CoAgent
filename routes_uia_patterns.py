"""UIA control-pattern write API — deterministic Toggle/Select/Expand/Value."""
from flask import Blueprint, jsonify, request
from shared import COAGENT_DIR  # noqa: F401

uia_patterns_bp = Blueprint("uia_patterns", __name__)

_ACTIONS = {
    "toggle",
    "select",
    "add_to_selection",
    "expand",
    "collapse",
    "set_value",
    "get_value",
}


def _control_summary(element):
    try:
        name = element.CurrentName or ""
    except Exception:
        name = ""
    try:
        automation_id = element.CurrentAutomationId or ""
    except Exception:
        automation_id = ""
    try:
        control_type = int(element.CurrentControlType)
    except Exception:
        control_type = 0
    return {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
    }


@uia_patterns_bp.route("/uia/pattern/invoke", methods=["POST"])
def route_uia_pattern_invoke():
    try:
        body = request.get_json(silent=True) or {}

        name = body.get("name")
        automation_id = body.get("automation_id")
        focused = bool(body.get("focused"))
        action = body.get("action")
        value = body.get("value")

        try:
            timeout_ms = int(body.get("timeout_ms", 5000))
        except (TypeError, ValueError):
            timeout_ms = 5000

        selectors = [
            bool(name),
            bool(automation_id),
            bool(focused),
        ]
        if sum(1 for s in selectors if s) != 1:
            return jsonify({
                "ok": False,
                "error": "exactly one of name, automation_id, focused must be provided",
            }), 400

        if not action or action not in _ACTIONS:
            return jsonify({
                "ok": False,
                "error": f"action must be one of {sorted(_ACTIONS)}",
            }), 400

        if action == "set_value" and value is None:
            return jsonify({
                "ok": False,
                "error": "value is required for set_value",
            }), 400

        import comtypes
        import comtypes.client

        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        try:
            from comtypes.gen import UIAutomationClient as UIA
        except Exception:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA

        iuia = comtypes.CoCreateInstance(
            UIA.CUIAutomation._reg_clsid_,
            interface=UIA.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )

        element = None
        if focused:
            try:
                element = iuia.GetFocusedElement()
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"failed to get focused element: {type(exc).__name__}: {exc}",
                }), 404
        else:
            import time as _time
            deadline = _time.monotonic() + max(0.0, timeout_ms / 1000.0)
            root = iuia.GetRootElement()

            if automation_id:
                condition = iuia.CreatePropertyCondition(
                    UIA.UIA_AutomationIdPropertyId, str(automation_id)
                )
            else:
                condition = iuia.CreatePropertyCondition(
                    UIA.UIA_NamePropertyId, str(name)
                )

            while True:
                try:
                    found = root.FindFirst(UIA.TreeScope_Subtree, condition)
                except Exception:
                    found = None

                if found is None and name:
                    # Fallback: substring/case-insensitive scan of descendants.
                    try:
                        true_cond = iuia.CreateTrueCondition()
                        walker_all = root.FindAll(UIA.TreeScope_Subtree, true_cond)
                        n = walker_all.Length if walker_all is not None else 0
                        needle = str(name).casefold()
                        for i in range(n):
                            try:
                                cand = walker_all.GetElement(i)
                                cand_name = (cand.CurrentName or "").casefold()
                                if needle in cand_name:
                                    found = cand
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass

                if found is not None:
                    element = found
                    break

                if _time.monotonic() >= deadline:
                    break

            if element is None:
                return jsonify({
                    "ok": False,
                    "error": "element not found",
                }), 404

        if not element:
            return jsonify({"ok": False, "error": "element not found"}), 404

        element_info = _control_summary(element)

        # Dispatch by action, each with its own try/except for pattern support.
        if action == "toggle":
            try:
                pat_unk = element.GetCurrentPattern(UIA.UIA_TogglePatternId)
                pat = pat_unk.QueryInterface(UIA.IUIAutomationTogglePattern)
            except Exception:
                return jsonify({
                    "ok": False,
                    "error": "pattern toggle not supported by element",
                }), 501
            try:
                pat.Toggle()
                state = int(pat.CurrentToggleState)
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"toggle failed: {type(exc).__name__}: {exc}",
                }), 500
            return jsonify({
                "ok": True,
                "action": action,
                "element": element_info,
                "result": {"toggle_state": state},
            })

        if action in ("select", "add_to_selection"):
            try:
                pat_unk = element.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                pat = pat_unk.QueryInterface(UIA.IUIAutomationSelectionItemPattern)
            except Exception:
                return jsonify({
                    "ok": False,
                    "error": f"pattern {action} not supported by element",
                }), 501
            try:
                if action == "select":
                    pat.Select()
                else:
                    pat.AddToSelection()
                is_selected = bool(pat.CurrentIsSelected)
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"{action} failed: {type(exc).__name__}: {exc}",
                }), 500
            return jsonify({
                "ok": True,
                "action": action,
                "element": element_info,
                "result": {"is_selected": is_selected},
            })

        if action in ("expand", "collapse"):
            try:
                pat_unk = element.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
                pat = pat_unk.QueryInterface(UIA.IUIAutomationExpandCollapsePattern)
            except Exception:
                return jsonify({
                    "ok": False,
                    "error": f"pattern {action} not supported by element",
                }), 501
            try:
                if action == "expand":
                    pat.Expand()
                else:
                    pat.Collapse()
                state = int(pat.CurrentExpandCollapseState)
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"{action} failed: {type(exc).__name__}: {exc}",
                }), 500
            return jsonify({
                "ok": True,
                "action": action,
                "element": element_info,
                "result": {"expand_collapse_state": state},
            })

        if action == "set_value":
            try:
                pat_unk = element.GetCurrentPattern(UIA.UIA_ValuePatternId)
                pat = pat_unk.QueryInterface(UIA.IUIAutomationValuePattern)
            except Exception:
                return jsonify({
                    "ok": False,
                    "error": "pattern set_value not supported by element",
                }), 501
            try:
                pat.SetValue(str(value))
                current = pat.CurrentValue or ""
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"set_value failed: {type(exc).__name__}: {exc}",
                }), 500
            return jsonify({
                "ok": True,
                "action": action,
                "element": element_info,
                "result": {"value": current},
            })

        if action == "get_value":
            try:
                pat_unk = element.GetCurrentPattern(UIA.UIA_ValuePatternId)
                pat = pat_unk.QueryInterface(UIA.IUIAutomationValuePattern)
            except Exception:
                return jsonify({
                    "ok": False,
                    "error": "pattern get_value not supported by element",
                }), 501
            try:
                current = pat.CurrentValue or ""
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": f"get_value failed: {type(exc).__name__}: {exc}",
                }), 500
            return jsonify({
                "ok": True,
                "action": action,
                "element": element_info,
                "result": {"value": current},
            })

        return jsonify({
            "ok": False,
            "error": f"unhandled action: {action}",
        }), 400

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }), 500


def register_routes(app, state, require_auth):
    app.register_blueprint(uia_patterns_bp)
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, uia_patterns_bp.name, require_auth)
