"""Mid-run natural-language steering for the goal-runner (issue #727).

Lets an operator interrupt a running goal and inject a corrected instruction
in natural language ("skip the settings step", "email me the result") without
aborting the run. Reuses the steering queue that already lives in
routes_copilot_enhanced (`_enqueue_steer`, `_drain_steer_queue`,
`_revise_plan`, `_rollback_last_completed`) plus its SSE event emitter, and
adds:

    POST /goal-runner/steer/<run_id>   -- inject instruction, return preview
    GET  /goal-runner/steer/<run_id>   -- steer status incl. awaiting_instruction

Flow on receipt of a steer:
    1. Look up the running goal by run_id; reject cleanly if unknown/terminal.
    2. Optionally rollback the last completed step (reuses existing ring buffer).
    3. Enqueue the instruction. The goal-runner loop drains the queue at the
       next step boundary and calls `_revise_plan`, which folds the operator's
       correction into the remaining (unexecuted) portion of the plan; already
       completed steps are preserved.
    4. Best-effort synchronous preview via `_decompose_goal` for the client.
    5. Emit `steer_received` on the existing SSE progress stream.

Approval-gated steps continue to route through routes_approvals; this module
does not bypass the gate. When the caller sets `approval_required=true`, the
steer itself is gated on `require_approval()` before being enqueued.
"""

import logging
import traceback

from flask import jsonify, request

from shared import _json_body, _missing_field

_LOGGER = logging.getLogger(__name__)


def _reuse():
    """Late-bind to routes_copilot_enhanced so import order never blocks us."""
    try:
        import routes_copilot_enhanced as ce
    except Exception as exc:
        return None, f"copilot_enhanced not available: {type(exc).__name__}: {exc}"
    return ce, None


def _no_active_run(run_id=None):
    payload = {"ok": False, "error": "no active run"}
    if run_id:
        payload["run_id"] = run_id
    return jsonify(payload), 404


def _awaiting_instruction(goal):
    if not goal:
        return False
    status = str(goal.get("status") or "").lower()
    if status in {"completed", "failed", "stopped"}:
        return False
    return bool(goal.get("steering_queue") or [])


def _remaining_index(goal):
    steps = goal.get("steps") or []
    for i, step in enumerate(steps):
        if step.get("status") in {"pending", "running"}:
            try:
                return int(step.get("index", i))
            except (TypeError, ValueError):
                return i
    return len(steps)


def _preview_revise(ce, run_id, instruction):
    """Best-effort synchronous re-plan for the client; does NOT mutate the goal."""
    with ce._GOALS_LOCK:
        goal = ce._GOALS.get(run_id)
        if not goal:
            return None, "goal not found"
        goal_text = str(goal.get("goal") or "")
        agent = goal.get("agent")
        model = goal.get("model")
        try:
            max_steps = int(goal.get("max_steps") or 10)
        except (TypeError, ValueError):
            max_steps = 10
        prior_pending = [
            str(s.get("instruction") or "").strip()
            for s in (goal.get("steering_queue") or [])
        ]
        remaining = _remaining_index(goal)

    prior_pending = [text for text in prior_pending if text and text != instruction]
    all_instructions = prior_pending + [instruction]
    formatted = "\n".join(f"- {text}" for text in all_instructions)
    combined = (
        f"{goal_text}\n\n"
        "Operator corrections to fold in (do not discard already-completed steps):\n"
        f"{formatted}"
    )
    try:
        auth = ce._auth_header(request.headers.get("Authorization", ""))
    except Exception:
        auth = ""
    try:
        steps, meta = ce._decompose_goal(combined, max_steps, auth, agent=agent, model=model)
    except Exception as exc:
        return None, f"preview failed: {type(exc).__name__}: {exc}"
    slots = max(1, max_steps - remaining)
    preview_steps = list(steps)[:slots]
    return {
        "revised_from_index": remaining,
        "steps": preview_steps,
        "step_count": len(preview_steps),
        "source": (meta or {}).get("source"),
    }, None


def _approval_gate(action_label, detail):
    """If routes_approvals is enabled, block on human approval. Fails closed."""
    try:
        from routes_approvals import require_approval
    except Exception:
        return False, {"status": "unavailable"}
    try:
        return require_approval(action_label, detail=detail, timeout=30.0)
    except Exception as exc:
        return False, {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def reg_midrun_steering(app, state, require_auth):
    """Register the mid-run steering endpoints on the given Flask app."""

    @app.route("/goal-runner/steer/<run_id>", methods=["POST"])
    @require_auth
    def route_goal_runner_steer(run_id):
        try:
            ce, err = _reuse()
            if err:
                return jsonify({"ok": False, "error": err}), 503

            body = _json_body() or {}
            missing = _missing_field(body, "instruction")
            if missing is not None:
                return missing
            instruction = str(body.get("instruction") or "").strip()
            if not instruction:
                return jsonify({"ok": False, "error": "instruction is required"}), 400

            rollback = (
                str(body.get("rollback", "")).lower() in {"1", "true", "yes", "on"}
                or body.get("rollback") is True
            )
            requires_approval = bool(body.get("approval_required"))
            source = str(body.get("source") or "operator")

            with ce._GOALS_LOCK:
                goal = ce._GOALS.get(run_id)
                if not goal:
                    return _no_active_run(run_id)
                if str(goal.get("status") or "").lower() in ce._TERMINAL_GOAL_STATUSES:
                    return _no_active_run(run_id)

            if requires_approval:
                allowed, item = _approval_gate(
                    f"midrun_steer:{run_id[:8]}",
                    detail={"instruction": instruction, "run_id": run_id},
                )
                if not allowed:
                    return jsonify({
                        "ok": False,
                        "error": "steer rejected by approval gate",
                        "approval": item,
                        "run_id": run_id,
                    }), 403

            rollback_result = None
            if rollback:
                try:
                    auth = ce._auth_header(request.headers.get("Authorization", ""))
                    rollback_result = ce._rollback_last_completed(run_id, auth)
                    if rollback_result and rollback_result.get("rolled_back_index") is not None:
                        ce._emit_goal_event(run_id, "steer_rollback", rollback_result)
                except Exception as exc:
                    rollback_result = {"error": f"{type(exc).__name__}: {exc}"}

            entry, enq_err = ce._enqueue_steer(
                run_id, instruction, rollback=rollback, source=source
            )
            if enq_err:
                return jsonify({"ok": False, "error": enq_err, "run_id": run_id}), 409

            try:
                ce._emit_goal_event(run_id, "steer_received", {
                    "run_id": run_id,
                    "instruction": instruction,
                    "queued_id": (entry or {}).get("id"),
                    "rollback": bool(rollback_result and rollback_result.get("rolled_back_index") is not None),
                    "approval_required": requires_approval,
                })
                ce._emit_goal_timeline(run_id)
            except Exception as exc:
                _LOGGER.debug("emit steer_received failed: %s", exc)

            preview, preview_err = _preview_revise(ce, run_id, instruction)

            with ce._GOALS_LOCK:
                goal = ce._GOALS.get(run_id) or {}
                queued = len(goal.get("steering_queue") or [])
                awaiting = _awaiting_instruction(goal)
                goal_status = goal.get("status")

            return jsonify({
                "ok": True,
                "run_id": run_id,
                "status": goal_status,
                "awaiting_instruction": awaiting,
                "steer": entry,
                "queued": queued,
                "rollback": rollback_result,
                "revised_plan_preview": preview,
                "preview_error": preview_err,
                "approval_required": requires_approval,
            })
        except Exception as exc:
            _LOGGER.error(
                "goal-runner steer failed: %s\n%s", exc, traceback.format_exc(limit=6)
            )
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/goal-runner/steer/<run_id>", methods=["GET"])
    @require_auth
    def route_goal_runner_steer_status(run_id):
        try:
            ce, err = _reuse()
            if err:
                return jsonify({"ok": False, "error": err}), 503
            with ce._GOALS_LOCK:
                goal = ce._GOALS.get(run_id)
                if not goal:
                    return _no_active_run(run_id)
                status = goal.get("status")
                queue = list(goal.get("steering_queue") or [])
                history = list(goal.get("steering_history") or [])
                remaining = _remaining_index(goal)
                awaiting = _awaiting_instruction(goal)
                goal_text = str(goal.get("goal") or "")
            return jsonify({
                "ok": True,
                "run_id": run_id,
                "status": status,
                "awaiting_instruction": awaiting,
                "steering_queue": queue,
                "steering_history": history,
                "remaining_from_index": remaining,
                "goal": goal_text,
            })
        except Exception as exc:
            _LOGGER.error(
                "goal-runner steer status failed: %s\n%s",
                exc,
                traceback.format_exc(limit=6),
            )
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    _LOGGER.info("Mid-run steering routes registered (/goal-runner/steer/<run_id>)")


def register_routes(app, state, require_auth):
    """Convention-compatible alias for reg_midrun_steering."""
    reg_midrun_steering(app, state, require_auth)
