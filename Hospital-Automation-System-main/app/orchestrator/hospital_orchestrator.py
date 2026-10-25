"""
Hospital Orchestrator

Receives hospital events, resolves capabilities via the intelligence layer
(registry, planner, executor), executes plan steps in sequence, and returns
a structured workflow summary.

Exception handling is centralized here. Workflows raise AgentExecutionError
on failure; the orchestrator catches it, merges the execution trace, and
returns a structured response.
"""

import uuid
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.enums import HospitalEventEnum, AgentActionStatusEnum
from app.models.orchestrator_trace import OrchestratorTrace
from app.models.agent_action_log import AgentActionLog
from app.orchestrator.execution import AgentExecutionError, WorkflowPausedException
from app.orchestrator.constants import ExecutionStatus

from app.orchestrator.intelligence import (
    OrchestrationContext,
    IntelligentPlanner,
    IntelligentExecutor,
    default_registry,
)
from app.orchestrator.intelligence.sop_grounded_planner import (
    SOPGroundedPlanner,
    SOPValidationException,
)
from app.services.sop_retriever import retrieve_sop
from app.services.system_config_service import get_config_value

# ENABLE_SOP_LLM_PLANNER is resolved dynamically per request via
# get_config_value() instead of a module-level constant.

# Module-level planner and executor built from the default registry.
# As new capabilities are registered in the registry, the planner
# will automatically pick them up without changes here.
_planner = IntelligentPlanner(default_registry)
_sop_planner = SOPGroundedPlanner(default_registry)
_executor = IntelligentExecutor(default_registry)

# Keys that belong to the orchestrator response envelope and must
# never be overwritten by values from context.produced.
_RESERVED_KEYS = frozenset({
    "status", "workflow_id", "event", "workflow_execution",
    "failed_agent", "reason", "workflow", "event_id", "agent_action_id",
    "priority_source",
})


def _save_trace(db: Session, trace: OrchestratorTrace, **updates):
    """Persist trace updates to the database.

    All writes are best-effort: if the database operation fails,
    the error is logged but never raised so that primary hospital
    workflows are not interrupted by observability failures.
    """
    try:
        for key, value in updates.items():
            setattr(trace, key, value)
        db.commit()
    except Exception as exc:
        print(f"[TRACE] Failed to persist trace update: {exc}")
        try:
            db.rollback()
        except Exception:
            pass


def _commit_pending_experiences(context, partial: bool = False):
    """Persist staged recovery experiences after workflow completion.

    Only called when the workflow finishes with SUCCESS or
    PARTIAL_SUCCESS (with at least one corrective step that worked).
    """
    pending = context.metadata.get("pending_recovery_experiences", [])
    if not pending:
        return

    try:
        from app.services.workflow_experience_service import (
            record_workflow_experience,
        )
        from app.orchestrator.constants import ResolutionType

        dept_id = (
            context.produced.get("department_id")
            or context.payload.get("department_id")
        )

        for entry in pending:
            record_workflow_experience(
                db=context.db,
                event_type=context.event_type,
                resolution_type=ResolutionType.AUTOMATED_RECOVERY,
                department_id=dept_id,
                workflow_id=context.workflow_id,
                failed_capability=entry.get("failed_capability"),
                error_message=entry.get("error_message"),
                corrective_steps=entry.get("corrective_steps"),
                partial=partial,
            )
    except Exception as exp_err:
        print(f"[ORCHESTRATOR] Failed to commit recovery experiences: {exp_err}")


# Action types linked to intentional human gates that must never be auto-resolved
_HUMAN_GATE_KEYWORDS = frozenset({
    "HUMAN_REVIEW_REQUIRED",
    "PROOF_REVIEW_REQUIRED",
    "PENDING_HUMAN_APPROVAL",
    "CERTIFICATION_MISSING",
})


def _auto_resolve_self_corrected(context):
    """Auto-resolve AgentActionLog rows for self-corrected failures.

    Only resolves failed logs whose action_type matches a capability
    listed in context.metadata['self_corrected_failures']. Skips any
    log whose decision_summary contains a human-gate keyword.
    """
    corrected = context.metadata.get("self_corrected_failures", [])
    if not corrected:
        return

    wf_id = context.workflow_id
    if not wf_id:
        return

    corrected_capabilities = {entry["failed_capability"] for entry in corrected}

    try:
        failed_logs = (
            context.db.query(AgentActionLog)
            .filter(
                AgentActionLog.workflow_id == wf_id,
                AgentActionLog.execution_status == AgentActionStatusEnum.FAILED,
                AgentActionLog.is_resolved == False,
                AgentActionLog.action_type.in_(corrected_capabilities),
            )
            .all()
        )

        resolved_count = 0
        for log in failed_logs:
            summary = (log.decision_summary or "").upper()
            if any(kw in summary for kw in _HUMAN_GATE_KEYWORDS):
                print(
                    f"[AUTO_RESOLVE] Skipping human-gate log "
                    f"agent_action_id={log.agent_action_id}: {log.decision_summary[:80]}"
                )
                continue

            log.is_resolved = True
            from datetime import datetime as _dt
            log.resolved_at = _dt.now()
            log.resolution_action = "AUTO_RESOLVED_SELF_CORRECTION"
            log.supervisor_notes = (
                f"Auto-resolved: orchestrator self-correction recovered "
                f"capability '{log.action_type}' in workflow {wf_id}."
            )
            resolved_count += 1

        if resolved_count:
            print(
                f"[AUTO_RESOLVE] Resolved {resolved_count} self-corrected "
                f"escalation(s) for workflow {wf_id}"
            )
    except Exception as err:
        print(f"[AUTO_RESOLVE] Failed to auto-resolve escalations: {err}")


def _run_intelligent_path(
    event_type: HospitalEventEnum,
    payload: dict,
    db: Session,
    workflow_id: str,
    trace: OrchestratorTrace,
) -> dict:
    """Execute an event through the capability-driven intelligent path.

    Builds an OrchestrationContext, asks the planner for a plan,
    and runs the plan through the executor. Error handling is
    self-contained so that AgentExecutionError does not bubble up
    to the legacy catch block.
    """
    context = OrchestrationContext(
        db=db,
        workflow_id=workflow_id,
        event_type=event_type.value,
        payload=payload,
    )

    available_keys = set(payload.keys())
    planning_mode = "STATIC"
    planner_status = "SUCCESS"
    sop_referenced = None
    sop_text_for_reflection = ""
    llm_plan_raw = None
    validation_errors_text = None
    experience_context = ""

    # Governed SOP planning: attempt LLM advisor when feature flag is on
    plan = None
    if get_config_value(db, "ENABLE_SOP_LLM_PLANNER", False):
        try:
            sop_text, sop_meta = retrieve_sop(event_type.value, payload, db)
            if sop_text and sop_meta:
                sop_referenced = sop_meta.get("_filename")
                sop_text_for_reflection = sop_text
                print(f"[ORCHESTRATOR] SOP matched: {sop_referenced}")

                # Retrieve historical experience context for the planner
                try:
                    from app.services.workflow_experience_service import (
                        get_relevant_experiences,
                        format_experience_context,
                    )
                    dept_id = payload.get("department_id")
                    experiences = get_relevant_experiences(
                        db, event_type.value, department_id=dept_id,
                    )
                    experience_context = format_experience_context(experiences)
                except Exception as exp_err:
                    print(f"[ORCHESTRATOR] Experience retrieval failed: {exp_err}")
                    experience_context = ""

                plan, llm_plan_raw = _sop_planner.plan(
                    event_type.value, available_keys, sop_text,
                    experience_context=experience_context,
                )
                planning_mode = "LLM_VALIDATED"
                print(f"[ORCHESTRATOR] LLM plan validated for {event_type.value}")
            else:
                print(f"[ORCHESTRATOR] No SOP match for {event_type.value}, using static planner")

        except SOPValidationException as exc:
            planning_mode = "STATIC_FALLBACK"
            planner_status = "VALIDATION_FAILED"
            validation_errors_text = json.dumps(exc.errors, default=str)
            print(f"[ORCHESTRATOR] SOP validation failed: {exc.errors}, falling back to static planner")
            plan = None

        except (ValueError, Exception) as exc:
            planning_mode = "STATIC_FALLBACK"
            planner_status = "LLM_ERROR"
            validation_errors_text = str(exc)
            print(f"[ORCHESTRATOR] SOP planner error: {exc}, falling back to static planner")
            plan = None

    # Fallback to deterministic static planner
    if plan is None:
        plan = _planner.plan(event_type.value, available_keys)
        if planning_mode == "STATIC":
            planning_mode = "STATIC"

    # Record planned steps and planner audit fields
    planned_steps = [
        {"capability_name": step.capability_name, "agent_name": step.agent_name}
        for step in plan.steps
    ]
    _save_trace(
        db, trace,
        planned_steps_json=json.dumps(planned_steps, default=str),
        planning_mode=planning_mode,
        planner_status=planner_status,
        sop_referenced=sop_referenced,
        llm_plan_raw=llm_plan_raw,
        validation_errors=validation_errors_text,
    )

    try:
        _executor.execute(plan, context, sop_planner=_sop_planner, sop_text=sop_text_for_reflection)

        print(f"[ORCHESTRATOR] Workflow {workflow_id} completed successfully.")

        # Commit staged recovery experiences after successful execution
        _commit_pending_experiences(context, partial=False)

        # Auto-resolve self-corrected escalations
        _auto_resolve_self_corrected(context)

        # If self-correction injected steps, update the planned_steps trace
        if context.metadata.get("executed_plan_steps"):
            _save_trace(
                db, trace,
                planned_steps_json=json.dumps(
                    context.metadata["executed_plan_steps"], default=str
                ),
            )

        result = {
            "status": context.status,
            "workflow_id": workflow_id,
            "event": event_type.value,
            "workflow_execution": context.workflow_execution,
        }

        # Merge produced values, skipping reserved envelope keys
        # Also exclude internal reflection tracking from the output
        _REFLECTION_KEYS = {"reflection_attempts", "reflection_history", "executed_plan_steps", "self_corrected_failures"}
        for key, value in context.produced.items():
            if key not in _RESERVED_KEYS:
                result[key] = value
        for rk in _REFLECTION_KEYS:
            result.pop(rk, None)

        _save_trace(
            db, trace,
            execution_status=context.status,
            completed_at=datetime.now(),
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            final_result_json=json.dumps(result, default=str),
        )

        return result

    except WorkflowPausedException as pause:
        # Persist remaining execution state for later resume
        from app.orchestrator.intelligence.serialization import (
            serialize_context,
            serialize_plan_steps,
        )

        print(
            f"[ORCHESTRATOR] Workflow {workflow_id} paused: {pause.message} "
            f"(remaining_steps={len(pause.remaining_steps)})"
        )

        result = {
            "status": pause.status,
            "workflow_id": workflow_id,
            "event": event_type.value,
            "workflow_execution": context.workflow_execution,
            "message": pause.message,
        }

        for key, value in context.produced.items():
            if key not in _RESERVED_KEYS:
                result[key] = value

        _save_trace(
            db, trace,
            execution_status=ExecutionStatus.PAUSED,
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            remaining_steps_json=serialize_plan_steps(pause.remaining_steps),
            context_state_json=serialize_context(context),
            final_result_json=json.dumps(result, default=str),
        )

        return result

    except AgentExecutionError as exc:
        # The executor already recorded completed steps and the
        # failed step into context.workflow_execution, so we use
        # that trace directly instead of merging again.
        status = exc.metadata.get("status", ExecutionStatus.FAILED)

        # Commit recovery experiences on PARTIAL_SUCCESS if corrective steps ran
        if status == ExecutionStatus.PARTIAL_SUCCESS:
            _commit_pending_experiences(context, partial=True)
            _auto_resolve_self_corrected(context)

        response = {
            "status": status,
            "workflow_id": workflow_id,
            "event": event_type.value,
            "workflow_execution": context.workflow_execution,
            "failed_agent": exc.agent,
            "reason": exc.message,
        }

        # Unpack dynamic metadata keys (work_id, request_id, etc.)
        for k, v in exc.metadata.items():
            if k != "status":
                response[k] = v

        _save_trace(
            db, trace,
            execution_status=status,
            completed_at=datetime.now(),
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            error_message=exc.message,
            final_result_json=json.dumps(response, default=str),
        )

        return response


def resume_workflow(workflow_id: str, supervisor_inputs: dict, db: Session) -> dict:
    """Resume a paused workflow after supervisor action.

    Loads the serialized context and remaining plan steps from the trace,
    merges supervisor inputs, and re-executes the remaining steps.

    Args:
        workflow_id:      UUID of the paused workflow trace.
        supervisor_inputs: Key-value pairs from the supervisor (e.g. proof_verified).
        db:               Active SQLAlchemy session.

    Returns:
        A workflow summary dict matching the handle_event response format.

    Raises:
        ValueError: If the trace is not in PAUSED state (prevents double resume).
    """
    from app.orchestrator.intelligence.serialization import (
        deserialize_context,
        deserialize_plan_steps,
    )
    from app.orchestrator.execution import GracefulWorkflowAbort
    from sqlalchemy import update

    # Compare-and-set: atomically lock the trace only if it is still PAUSED.
    # This prevents double-resume if a supervisor clicks approve twice.
    stmt = (
        update(OrchestratorTrace)
        .where(
            OrchestratorTrace.workflow_id == workflow_id,
            OrchestratorTrace.execution_status == ExecutionStatus.PAUSED,
        )
        .values(execution_status=ExecutionStatus.RESUMING)
    )
    res = db.execute(stmt)
    db.commit()

    if res.rowcount == 0:
        # Either not found or not in PAUSED state
        trace = db.query(OrchestratorTrace).filter(
            OrchestratorTrace.workflow_id == workflow_id
        ).first()
        if not trace:
            raise ValueError(f"Workflow trace {workflow_id} not found")
        raise ValueError(
            f"Workflow {workflow_id} is not paused "
            f"(current status: {trace.execution_status})"
        )

    trace = db.query(OrchestratorTrace).filter(
        OrchestratorTrace.workflow_id == workflow_id
    ).first()

    print(f"[ORCHESTRATOR] Resuming workflow {workflow_id}")

    # Reconstruct context and remaining plan from saved state
    context = deserialize_context(db, trace.context_state_json)
    context.status = ExecutionStatus.SUCCESS
    remaining_plan = deserialize_plan_steps(
        trace.event_type, trace.remaining_steps_json,
    )

    # Merge supervisor inputs into context.produced
    context.merge_produced(supervisor_inputs)

    try:
        _executor.execute(remaining_plan, context)

        print(f"[ORCHESTRATOR] Resumed workflow {workflow_id} completed successfully.")

        result = {
            "status": context.status,
            "workflow_id": workflow_id,
            "event": trace.event_type,
            "workflow_execution": context.workflow_execution,
        }

        for key, value in context.produced.items():
            if key not in _RESERVED_KEYS:
                result[key] = value

        # Terminal success: clear paused state
        _save_trace(
            db, trace,
            execution_status=context.status,
            completed_at=datetime.now(),
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            final_result_json=json.dumps(result, default=str),
            remaining_steps_json=None,
            context_state_json=None,
        )

        return result

    except GracefulWorkflowAbort as abort:
        # Rejection or other terminal graceful abort during resumed execution
        print(
            f"[ORCHESTRATOR] Resumed workflow {workflow_id} aborted: "
            f"{abort.message} (status={abort.status})"
        )

        context.status = abort.status
        context.merge_produced(abort.metadata)

        result = {
            "status": abort.status,
            "workflow_id": workflow_id,
            "event": trace.event_type,
            "workflow_execution": context.workflow_execution,
            "message": abort.message,
        }

        for key, value in context.produced.items():
            if key not in _RESERVED_KEYS:
                result[key] = value

        # Terminal abort: clear paused state
        _save_trace(
            db, trace,
            execution_status=abort.status,
            completed_at=datetime.now(),
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            final_result_json=json.dumps(result, default=str),
            remaining_steps_json=None,
            context_state_json=None,
        )

        return result

    except AgentExecutionError as exc:
        status = exc.metadata.get("status", ExecutionStatus.FAILED)

        response = {
            "status": status,
            "workflow_id": workflow_id,
            "event": trace.event_type,
            "workflow_execution": context.workflow_execution,
            "failed_agent": exc.agent,
            "reason": exc.message,
        }

        for k, v in exc.metadata.items():
            if k != "status":
                response[k] = v

        # Agent failure: clear paused state since this is terminal
        _save_trace(
            db, trace,
            execution_status=status,
            completed_at=datetime.now(),
            workflow_execution_json=json.dumps(context.workflow_execution, default=str),
            produced_outputs_json=json.dumps(context.produced, default=str),
            error_message=exc.message,
            final_result_json=json.dumps(response, default=str),
            remaining_steps_json=None,
            context_state_json=None,
        )

        return response

    except Exception as exc:
        # Unexpected error: keep paused state for retry
        print(
            f"[ORCHESTRATOR] Resumed workflow {workflow_id} crashed: {exc}. "
            f"Paused state preserved for retry."
        )

        _save_trace(
            db, trace,
            execution_status=ExecutionStatus.PAUSED,
            error_message=str(exc),
        )

        raise


def handle_event(event_type: HospitalEventEnum, payload: dict, db: Session) -> dict:
    """
    Centralized Hospital Orchestrator.

    Receives a hospital event and coordinates downstream agents.
    It does not directly manipulate the database; each agent owns
    its own data operations.

    Routes through the intelligent path when the capability registry
    supports the event, otherwise raises ValueError for unsupported events.

    Args:
        event_type: The hospital event that triggered this workflow.
        payload:    Event-specific data dict (contract varies by event).
        db:         SQLAlchemy session, forwarded to agents as-is.

    Returns:
        A workflow summary dict containing status, workflow_execution trace,
        and relevant IDs produced by each agent.
    """

    workflow_id = str(uuid.uuid4())

    print(f"[ORCHESTRATOR] Event: {event_type.value}  workflow_id: {workflow_id}")

    # Create the trace row (best-effort, never blocks the workflow)
    try:
        input_payload_json = json.dumps(payload, default=str)
    except Exception:
        input_payload_json = "{}"

    trace = OrchestratorTrace(
        workflow_id=workflow_id,
        event_type=event_type.value,
        execution_status="RUNNING",
        trigger_source=payload.get("trigger_source", "API"),
        started_at=datetime.now(),
        input_payload_json=input_payload_json,
    )
    db.add(trace)
    _save_trace(db, trace)


    # Intelligent path: registry-based routing
    if _planner.supports(event_type.value):
        print(f"[ORCHESTRATOR] Using intelligent path for {event_type.value}")
        return _run_intelligent_path(event_type, payload, db, workflow_id, trace)

    raise ValueError(
        f"Unsupported event type '{event_type.value}'. No registered capabilities handle this event."
    )
