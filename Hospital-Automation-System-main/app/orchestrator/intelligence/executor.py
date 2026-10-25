"""
Intelligent Executor

Runs the steps of an ExecutionPlan sequentially.
For each step it:
  1. Builds the step payload from context.payload + context.produced.
  2. Looks up the capability handler from the registry.
  3. Calls the handler.
  4. Merges returned values into context.produced.
  5. Appends a trace entry to context.workflow_execution.
  6. Applies the failure policy if the handler raises.

Self-Correction Loop (opt-in via ENABLE_ORCHESTRATOR_SELF_CORRECTION):
  When a reflectable error occurs and the feature flag is enabled,
  the executor asks the SOP planner to propose recovery steps, injects
  them at the head of the remaining queue, and continues execution.
  Non-reflectable errors (security, human-review, schema) bypass
  self-correction entirely.
"""

from app.orchestrator.intelligence.context import OrchestrationContext
from app.orchestrator.intelligence.planner import ExecutionPlan
from app.orchestrator.intelligence.registry import CapabilityRegistry
from app.orchestrator.intelligence.policies import get_policy
from app.orchestrator.execution import (
    AgentExecutionError,
    GracefulWorkflowAbort,
    WorkflowPausedException,
    record_step,
)
from app.orchestrator.constants import ExecutionStatus, ResolutionType
from app.models.agent_action_log import AgentActionLog
from app.models.enums import AgentActionStatusEnum


class StepResult:
    """Outcome of executing a single plan step."""

    __slots__ = ("capability_name", "agent_name", "success", "output", "error")

    def __init__(
        self,
        capability_name: str,
        agent_name: str,
        success: bool,
        output: dict | None = None,
        error: str | None = None,
    ):
        self.capability_name = capability_name
        self.agent_name = agent_name
        self.success = success
        self.output = output or {}
        self.error = error


# Error message fragments that indicate non-reflectable failure categories
_NON_REFLECTABLE_KEYWORDS = frozenset({
    "HUMAN_REVIEW_REQUIRED",
    "PROOF_REJECTED",
    "CERTIFICATION_MISSING",
    "SECURITY_VIOLATION",
    "AUTHENTICATION_FAILED",
    "SCHEMA_VALIDATION",
    "PAYLOAD_INVALID",
})


class IntelligentExecutor:
    """Runs an ExecutionPlan against live agents via the registry."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _is_reflectable_error(exc: AgentExecutionError) -> bool:
        """Determine whether the failure is safe for self-correction.

        Returns True ONLY for transient/operational failures:
          - Connection timeouts / network transient errors
          - Temporary capacity conflicts / workload spikes
          - Duplicate / idempotent operations
          - Assignment races
          - Non-critical side-effects

        Returns False for:
          - Human-in-the-loop triggers (HUMAN_REVIEW_REQUIRED)
          - Proof rejections (PROOF_REJECTED)
          - Missing certifications / static profile mismatches
          - Security or authentication failures
          - Schema / payload invalidations
        """
        # Priority check: structured metadata signals
        meta = exc.metadata or {}
        if meta.get("escalation_required") is True:
            return False
        if meta.get("escalation_type") == "HUMAN_REVIEW_REQUIRED":
            return False

        # Fallback: keyword matching on the error message
        msg_upper = (exc.message or "").upper()
        for keyword in _NON_REFLECTABLE_KEYWORDS:
            if keyword in msg_upper:
                return False

        return True

    def _tag_action_logs_with_workflow(self, context):
        """Tag untagged AgentActionLog objects in the active session.

        Scans db.new (pending INSERTs) and the identity_map (already-flushed
        objects still tracked by the session) for AgentActionLog rows that
        have no workflow_id set and stamps them with context.workflow_id.
        This is the fallback mechanism for domain agents that do not accept
        workflow_id explicitly.
        """
        wf_id = context.workflow_id
        if not wf_id:
            return

        for obj in list(context.db.new):
            if isinstance(obj, AgentActionLog) and not obj.workflow_id:
                obj.workflow_id = wf_id

        if hasattr(context.db, "identity_map"):
            for obj in list(context.db.identity_map.values()):
                if isinstance(obj, AgentActionLog) and not obj.workflow_id:
                    obj.workflow_id = wf_id

    def execute(
        self,
        plan: ExecutionPlan,
        context: OrchestrationContext,
        sop_planner=None,
        sop_text: str = "",
    ) -> list[StepResult]:
        """Execute every step in the plan using a queue-drain pattern.

        When self-correction is enabled and a reflectable error occurs,
        the executor injects LLM-proposed recovery steps at the head
        of the remaining queue and continues execution.

        Args:
            plan:        The ExecutionPlan produced by IntelligentPlanner.
            context:     The shared OrchestrationContext for this workflow run.
            sop_planner: Optional SOPGroundedPlanner instance for reflection.
            sop_text:    SOP document text for reflection prompts.

        Returns:
            A list of StepResult objects, one per attempted step.

        Raises:
            AgentExecutionError: Re-raised from an agent if the
                failure policy says to abort.
        """
        from app.services.system_config_service import get_config_value

        policy = get_policy(context.event_type)
        results: list[StepResult] = []

        # Build the mutable step queue from the plan
        remaining_steps = list(plan.steps)
        executed_plan_steps = []

        # Read self-correction config
        self_correction_enabled = (
            sop_planner is not None
            and get_config_value(
                context.db, "ENABLE_ORCHESTRATOR_SELF_CORRECTION", False
            )
        )
        max_attempts = get_config_value(
            context.db, "MAX_REFLECTION_ATTEMPTS", 1
        )

        # Initialize reflection tracking in context metadata
        if "reflection_attempts" not in context.metadata:
            context.metadata["reflection_attempts"] = 0
        if "pending_recovery_experiences" not in context.metadata:
            context.metadata["pending_recovery_experiences"] = []
        if "self_corrected_failures" not in context.metadata:
            context.metadata["self_corrected_failures"] = []

        while remaining_steps:
            step = remaining_steps.pop(0)
            capability = self._registry.get_capability(step.capability_name)

            # Track executed steps for trace persistence
            executed_plan_steps.append({
                "capability_name": step.capability_name,
                "agent_name": step.agent_name,
            })

            # Build the combined payload for this step
            step_payload = {**context.payload, **context.produced}

            # Idempotency check: skip step if domain state says it already happened
            if capability.idempotency_check is not None:
                check_result = capability.idempotency_check(step_payload, context)
                if check_result is not None and check_result.get("already_done"):
                    reason = check_result.get("reason", "already done")
                    print(
                        f"[EXECUTOR] Skipping '{step.capability_name}': {reason}"
                    )
                    skip_outputs = check_result.get("outputs", {})
                    if skip_outputs:
                        context.merge_produced(skip_outputs)
                    record_step(
                        context.workflow_execution,
                        step.agent_name,
                        ExecutionStatus.SKIPPED_ALREADY_DONE,
                        capability=step.capability_name,
                    )
                    results.append(StepResult(
                        capability_name=step.capability_name,
                        agent_name=step.agent_name,
                        success=True,
                        output=skip_outputs,
                    ))
                    continue

            try:
                print(
                    f"[EXECUTOR] Running capability '{step.capability_name}' "
                    f"(agent: {step.agent_name})..."
                )
                # Check for diagnostic mock error simulation
                sim_err = step_payload.get("simulate_error")
                if sim_err:
                    if sim_err == "TIMEOUT" and step.capability_name == "assign_work_item":
                        if "simulate_error" in context.payload:
                            del context.payload["simulate_error"]
                        raise AgentExecutionError(step.agent_name, "Simulated assignment failure: connection timed out")
                    elif sim_err == "WORKFORCE_SHORTAGE" and step.capability_name == "assign_work_item":
                        if "simulate_error" in context.payload:
                            del context.payload["simulate_error"]
                        raise AgentExecutionError(step.agent_name, "Simulated assignment failure: no eligible worker found (ACLS Nurse Missing)")
                    elif sim_err == "PROOF_REJECTED" and step.capability_name == "verify_task_proof":
                        if "simulate_error" in context.payload:
                            del context.payload["simulate_error"]
                        raise AgentExecutionError(step.agent_name, "Simulated verification failure: PROOF_REJECTED")

                output = capability.handler(step_payload, context)
                output = output if isinstance(output, dict) else {}

                # Merge produced outputs into context
                context.merge_produced(output)

                # Record success in the execution trace
                if output and isinstance(output, dict) and "workflow" in output:
                    for sub_step in output["workflow"]:
                        context.workflow_execution.append(sub_step)
                else:
                    record_step(
                        context.workflow_execution,
                        step.agent_name,
                        ExecutionStatus.SUCCESS,
                        capability=step.capability_name,
                    )

                results.append(StepResult(
                    capability_name=step.capability_name,
                    agent_name=step.agent_name,
                    success=True,
                    output=output,
                ))

                # Tag any untagged AgentActionLog rows created by the handler
                self._tag_action_logs_with_workflow(context)

            except GracefulWorkflowAbort as abort:
                # Merge metadata before deciding to pause or break
                context.status = abort.status
                context.merge_produced(abort.metadata)

                if abort.status in ("PENDING_HUMAN_APPROVAL", "PAUSED"):
                    # Pause-compatible: capture remaining steps and surface to orchestrator
                    print(
                        f"[EXECUTOR] Pausing at '{step.capability_name}': "
                        f"{abort.message} (status={abort.status}, "
                        f"remaining_steps={len(remaining_steps)})"
                    )
                    # Persist executed plan steps before pausing
                    context.metadata["executed_plan_steps"] = executed_plan_steps
                    raise WorkflowPausedException(
                        status=abort.status,
                        message=abort.message,
                        remaining_steps=remaining_steps,
                        metadata=abort.metadata,
                    )
                else:
                    # Graceful abort: stop execution without error
                    print(
                        f"[EXECUTOR] Graceful abort in '{step.capability_name}': "
                        f"{abort.message} (status={abort.status})"
                    )
                    break

            except AgentExecutionError as exc:
                # Merge any completed sub-steps the agent reported
                context.workflow_execution.extend(exc.completed_steps)

                # Check if self-correction can handle this error
                attempts = context.metadata.get("reflection_attempts", 0)
                can_self_correct = (
                    self_correction_enabled
                    and self._is_reflectable_error(exc)
                    and attempts < max_attempts
                )

                if can_self_correct:
                    try:
                        context.metadata["reflection_attempts"] = attempts + 1

                        # Compute available keys for the recovery planner
                        available_keys = set(context.payload.keys()) | set(context.produced.keys())
                        remaining_names = [s.capability_name for s in remaining_steps]

                        corrective_steps, reflection_dict = sop_planner.reflect_and_replan(
                            event_type=context.event_type,
                            failed_capability=step.capability_name,
                            error_message=exc.message,
                            available_keys=available_keys,
                            sop_text=sop_text,
                            remaining_steps=remaining_names,
                        )

                        # Record reflection history
                        if "reflection_history" not in context.metadata:
                            context.metadata["reflection_history"] = []
                        context.metadata["reflection_history"].append({
                            "failed_capability": step.capability_name,
                            "error": exc.message,
                            "corrective_steps": [s.capability_name for s in corrective_steps],
                            "reflection_summary": reflection_dict.get("reflection_summary"),
                            "correction_rationale": reflection_dict.get("correction_rationale"),
                        })

                        # Determine if the recovery is an escalation fallback
                        corrective_names = [s.capability_name for s in corrective_steps]
                        is_escalation = "handle_staff_shortage" in corrective_names

                        if is_escalation:
                            record_step(
                                context.workflow_execution,
                                "SYSTEM_REFLECTION",
                                "ESCALATION_FALLBACK",
                            )
                            context.workflow_execution[-1]["message"] = (
                                "Automated recovery unavailable. Creating supervisor escalation."
                            )
                        else:
                            summary = reflection_dict.get("reflection_summary", "Recovery attempted")
                            record_step(
                                context.workflow_execution,
                                "SYSTEM_REFLECTION",
                                "REFLECTING",
                            )
                            context.workflow_execution[-1]["message"] = (
                                f"{summary}. Recovery attempted: {corrective_names}"
                            )

                        print(
                            f"[EXECUTOR] Self-correction: injecting {corrective_names} "
                            f"after '{step.capability_name}' failure "
                            f"(attempt {attempts + 1}/{max_attempts})"
                        )

                        # Track corrective steps as executed
                        for cs in corrective_steps:
                            executed_plan_steps.append({
                                "capability_name": cs.capability_name,
                                "agent_name": cs.agent_name,
                                "injected_by": "SELF_CORRECTION",
                            })

                        # Stage recovery experience for post-success commit
                        context.metadata["pending_recovery_experiences"].append({
                            "failed_capability": step.capability_name,
                            "error_message": exc.message,
                            "corrective_steps": corrective_names,
                            "reflection_summary": reflection_dict.get("reflection_summary", ""),
                        })

                        # Track self-corrected failure for auto-resolution
                        context.metadata["self_corrected_failures"].append({
                            "failed_capability": step.capability_name,
                            "agent_name": step.agent_name,
                            "error_message": exc.message,
                        })

                        # Inject corrective steps at head of remaining queue
                        remaining_steps = corrective_steps + remaining_steps
                        continue

                    except Exception as reflection_err:
                        # Reflection itself failed, fall through to normal error handling
                        print(
                            f"[EXECUTOR] Self-correction failed: {reflection_err}. "
                            f"Falling back to normal error handling."
                        )

                # Normal error handling (no self-correction or self-correction failed)
                record_step(
                    context.workflow_execution,
                    exc.agent,
                    ExecutionStatus.FAILED,
                    capability=step.capability_name,
                )

                results.append(StepResult(
                    capability_name=step.capability_name,
                    agent_name=exc.agent,
                    success=False,
                    error=exc.message,
                ))

                # Fallback: if the domain agent did not create an
                # AgentActionLog for this failure, create one now so
                # the escalation is visible in supervisor dashboards.
                existing_failed = any(
                    isinstance(obj, AgentActionLog)
                    and obj.execution_status == AgentActionStatusEnum.FAILED
                    and obj.action_type == step.capability_name
                    for obj in list(context.db.new)
                )
                if not existing_failed:
                    dept_id = (
                        context.produced.get("department_id")
                        or context.payload.get("department_id")
                    )
                    fallback_action = AgentActionLog(
                        event_id=None,
                        department_id=dept_id,
                        agent_id=None,
                        action_type=step.capability_name,
                        execution_status=AgentActionStatusEnum.FAILED,
                        decision_summary=exc.message,
                        workflow_id=context.workflow_id,
                    )
                    context.db.add(fallback_action)
                    self._tag_action_logs_with_workflow(context)
                    context.db.flush()

                # Record permanent failure as UNRESOLVED experience
                try:
                    from app.services.workflow_experience_service import (
                        record_workflow_experience,
                    )
                    record_workflow_experience(
                        db=context.db,
                        event_type=context.event_type,
                        resolution_type=ResolutionType.UNRESOLVED,
                        department_id=context.produced.get("department_id") or context.payload.get("department_id"),
                        workflow_id=context.workflow_id,
                        failed_capability=step.capability_name,
                        error_message=exc.message,
                    )
                except Exception as exp_err:
                    print(f"[EXECUTOR] Failed to record UNRESOLVED experience: {exp_err}")

                should_continue = (
                    step.continue_on_failure
                    or capability.continue_on_failure
                    or policy.continue_on_failure
                )

                if not should_continue:
                    # Attach partial-success status when the policy allows it
                    if policy.partial_success_allowed and results and any(r.success for r in results):
                        exc.metadata.setdefault("status", ExecutionStatus.PARTIAL_SUCCESS)
                    # Persist executed steps before raising
                    context.metadata["executed_plan_steps"] = executed_plan_steps
                    raise

            except Exception as exc:
                record_step(
                    context.workflow_execution,
                    step.agent_name,
                    ExecutionStatus.FAILED,
                    capability=step.capability_name,
                )

                results.append(StepResult(
                    capability_name=step.capability_name,
                    agent_name=step.agent_name,
                    success=False,
                    error=str(exc),
                ))

                should_continue = (
                    step.continue_on_failure
                    or capability.continue_on_failure
                    or policy.continue_on_failure
                )

                if not should_continue:
                    context.metadata["executed_plan_steps"] = executed_plan_steps
                    raise AgentExecutionError(
                        agent=step.agent_name,
                        message=str(exc),
                        completed_steps=list(context.workflow_execution),
                        metadata=(
                            {"status": ExecutionStatus.PARTIAL_SUCCESS}
                            if policy.partial_success_allowed and any(r.success for r in results)
                            else {}
                        ),
                    )

        # Persist final executed plan steps
        context.metadata["executed_plan_steps"] = executed_plan_steps
        return results
