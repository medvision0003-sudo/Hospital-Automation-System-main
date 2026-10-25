"""
SOP-Grounded Planner

A governed planning advisor that reads Standard Operating Procedure
documents and uses an LLM to propose capability step sequences.
The LLM is strictly limited to selecting and ordering registered
capabilities. A deterministic validator approves or rejects the
proposal before any execution occurs.

Design principles:
  - The CapabilityRegistry remains the sole source of truth.
  - The LLM can only propose, never execute.
  - The static IntelligentPlanner is the fallback, not this.
  - This class is opt-in via the ENABLE_SOP_LLM_PLANNER feature flag.
"""

import os
import json
import time

import requests
from dotenv import load_dotenv

from app.orchestrator.intelligence.capabilities import AgentCapability
from app.orchestrator.intelligence.registry import CapabilityRegistry
from app.orchestrator.intelligence.planner import PlanStep, ExecutionPlan

load_dotenv()

# Reuse the same NVIDIA NIM endpoint and model as the Assignment Agent
NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
PLANNING_MODEL = os.getenv(
    "SOP_PLANNING_MODEL", "nvidia/nemotron-3-super-120b-a12b"
)
PLANNING_TIMEOUT = 20.0
PLANNING_TEMPERATURE = 0.1


# Mandatory capabilities per event type (V1 policy map)
# The validator rejects any LLM plan missing these steps.

MANDATORY_CAPABILITIES: dict[str, set[str]] = {
    "DYNAMIC_TASK_REQUEST": {"create_work_item", "assign_work_item"},
    "EMERGENCY_RESPONSE": {"handle_emergency", "assign_emergency_work_items"},
    "WORKER_CHECKED_IN": {
        "checkin_worker",
        "generate_shift_tasks",
        "run_assignment_cycle",
    },
    "WORKER_CHECKED_OUT": {"checkout_worker"},
    "SHIFT_STARTED": {"run_assignment_cycle_for_shift_start"},
    "STAFF_ABSENT_DETECTED": {"handle_staff_absent", "reassign_absent_worker_tasks"},
    "TASK_COMPLETED": {"complete_work_item", "update_worker_task_metrics"},
    "TASK_CANCELLED": {"cancel_work_item", "update_worker_task_metrics"},
    "SUPERVISOR_REQUEST_CREATED": {
        "load_supervisor_request",
        "create_work_item",
        "assign_work_item",
        "mark_supervisor_request_processed",
    },
    "TASK_PROOF_SUBMITTED": {
        "verify_task_proof",
        "complete_work_item_for_proof",
        "update_worker_task_metrics",
    },
    "SEND_WHATSAPP_NOTIFICATION": {"send_whatsapp_task_notification"},
}


# Recovery allowlist: capabilities that may be injected during self-correction.
# Only these capabilities can be proposed by the LLM for recovery replanning.
RECOVERY_CAPABILITIES: dict[str, set[str]] = {
    "DYNAMIC_TASK_REQUEST": {
        "recover_assignment_cycle",
        "rebalance_overloaded_worker",
        "handle_staff_shortage",
    },
    "WORKER_CHECKED_IN": {
        "recover_assignment_cycle",
    },
    "SUPERVISOR_REQUEST_CREATED": {
        "recover_assignment_cycle",
        "rebalance_overloaded_worker",
        "handle_staff_shortage",
    },
    "WORKER_OVERLOAD_DETECTED": {
        "recover_assignment_cycle",
    },
}


class SOPValidationException(Exception):
    """Raised when the LLM-proposed plan fails deterministic validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"SOP plan validation failed: {errors}")


class SOPGroundedPlanner:
    """Governed planning advisor backed by SOP documents and an LLM.

    The planner constructs a prompt from the SOP text and the list of
    registered capabilities, asks the LLM to propose an ordered step
    sequence, and then validates the proposal deterministically before
    converting it into an ExecutionPlan that the existing executor can
    run.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    # Public interface

    def plan(
        self,
        event_type: str,
        available_keys: set[str],
        sop_text: str,
        experience_context: str = "",
    ) -> tuple[ExecutionPlan, str]:
        """Propose and validate an SOP-grounded execution plan.

        Args:
            event_type:          HospitalEventEnum value string.
            available_keys:      Keys already present in the event payload.
            sop_text:            Body text of the matched SOP document.
            experience_context:  Formatted historical experience text block.

        Returns:
            (ExecutionPlan, llm_raw_json) on success.

        Raises:
            SOPValidationException: If the proposed plan fails validation.
            ValueError:             If the LLM call fails or returns bad JSON.
        """
        capabilities = self._registry.get_capabilities_for_event(event_type)
        cap_schemas = self._serialize_capabilities(capabilities)

        prompt = self._build_prompt(
            event_type, sop_text, cap_schemas,
            experience_context=experience_context,
        )
        raw_json = self._call_llm(prompt)

        proposed_names = self._parse_llm_response(raw_json)
        self._validate(proposed_names, event_type, available_keys)

        plan = self._build_execution_plan(proposed_names, event_type)
        return plan, raw_json

    # Self-Correction: Reflection and Replanning

    def reflect_and_replan(
        self,
        event_type: str,
        failed_capability: str,
        error_message: str,
        available_keys: set[str],
        sop_text: str,
        remaining_steps: list[str],
        experience_context: str = "",
    ) -> tuple[list[PlanStep], dict]:
        """Reflect on a capability failure and propose corrective recovery steps.

        The LLM is given the failure context, the SOP document, and the
        restricted set of recovery capabilities for this event type.
        Its response is validated by a dedicated corrective validator
        before being converted into injectable PlanSteps.

        Args:
            event_type:         HospitalEventEnum value string.
            failed_capability:  Name of the capability that failed.
            error_message:      Error message from the failed step.
            available_keys:     Keys currently available in context (payload + produced).
            sop_text:           Body text of the matched SOP document.
            remaining_steps:    Names of capabilities still queued after the failure.

        Returns:
            (list[PlanStep], reflection_dict) where reflection_dict contains
            the LLM's structured reasoning fields.

        Raises:
            SOPValidationException: If the proposed recovery steps fail validation.
            ValueError:             If the LLM call fails or returns bad JSON.
        """
        allowed = RECOVERY_CAPABILITIES.get(event_type, set())
        if not allowed:
            raise ValueError(
                f"No recovery capabilities defined for event type '{event_type}'"
            )

        # Build recovery capability descriptions for the LLM
        recovery_caps = []
        for cap_name in sorted(allowed):
            try:
                cap = self._registry.get_capability(cap_name)
                recovery_caps.append(cap)
            except KeyError:
                pass

        if not recovery_caps:
            raise ValueError(
                f"None of the recovery capabilities for '{event_type}' are registered"
            )

        cap_schemas = self._serialize_capabilities(recovery_caps)
        prompt = self._build_reflection_prompt(
            event_type=event_type,
            failed_capability=failed_capability,
            error_message=error_message,
            sop_text=sop_text,
            cap_schemas=cap_schemas,
            remaining_steps=remaining_steps,
            experience_context=experience_context,
        )

        raw_json = self._call_llm(prompt)

        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON for reflection: {exc}")

        corrective_names = []
        for step in parsed.get("corrective_steps", []):
            if isinstance(step, dict):
                corrective_names.append(step.get("capability_name", ""))
            elif isinstance(step, str):
                corrective_names.append(step)

        if not corrective_names:
            raise ValueError("LLM proposed no corrective steps")

        # Validate corrective steps with the dedicated recovery validator
        self._validate_corrective_steps(
            corrective_names=corrective_names,
            event_type=event_type,
            available_keys=available_keys,
            remaining_steps=remaining_steps,
            failed_capability=failed_capability,
        )

        # Convert validated names to PlanSteps
        plan_steps = []
        for name in corrective_names:
            cap = self._registry.get_capability(name)
            plan_steps.append(
                PlanStep(
                    capability_name=cap.name,
                    agent_name=cap.agent_name,
                    requires=cap.requires,
                    produces=cap.produces,
                    continue_on_failure=cap.continue_on_failure,
                )
            )

        reflection_dict = {
            "reflection_summary": parsed.get("reflection_summary", ""),
            "correction_rationale": parsed.get("correction_rationale", ""),
            "recovery_decision": parsed.get("recovery_decision", ""),
        }

        return plan_steps, reflection_dict

    def _validate_corrective_steps(
        self,
        corrective_names: list[str],
        event_type: str,
        available_keys: set[str],
        remaining_steps: list[str],
        failed_capability: str,
    ) -> None:
        """Validate recovery steps against the corrective allowlist.

        Unlike the main _validate, this does NOT enforce event compatibility
        or mandatory capability checks. It only ensures:
          1. Authenticity: every name exists in the registry.
          2. Allowlist compliance: every name is in RECOVERY_CAPABILITIES[event_type].
          3. Dependency check: required inputs are available in context.
          4. Duplicate safeguard: does not immediately repeat the failed capability.
        """
        errors: list[str] = []
        allowed = RECOVERY_CAPABILITIES.get(event_type, set())

        # 1. Authenticity
        for name in corrective_names:
            try:
                self._registry.get_capability(name)
            except KeyError:
                errors.append(f"Unregistered recovery capability: '{name}'")

        if errors:
            raise SOPValidationException(errors)

        # 2. Allowlist compliance
        for name in corrective_names:
            if name not in allowed:
                errors.append(
                    f"Recovery capability '{name}' not in allowlist for '{event_type}'"
                )

        # 3. Dependency check: required inputs must be satisfiable
        resolved_keys = set(available_keys)
        for name in corrective_names:
            cap = self._registry.get_capability(name)
            unmet = [k for k in cap.requires if k not in resolved_keys]
            if unmet:
                errors.append(
                    f"Recovery capability '{name}' has unmet requirements: {unmet}"
                )
            resolved_keys.update(cap.produces)

        # 4. Duplicate safeguard: no immediate repeat of the failed capability
        if corrective_names and corrective_names[0] == failed_capability:
            errors.append(
                f"Recovery plan immediately repeats failed capability '{failed_capability}'"
            )

        if errors:
            raise SOPValidationException(errors)

    @staticmethod
    def _build_reflection_prompt(
        event_type: str,
        failed_capability: str,
        error_message: str,
        sop_text: str,
        cap_schemas: str,
        remaining_steps: list[str],
        experience_context: str = "",
    ) -> str:
        """Build a structured prompt asking the LLM to propose recovery steps."""
        base = (
            "You are a hospital workflow recovery advisor.\n"
            "\n"
            "A capability step has FAILED during execution. You must analyze the "
            "failure, consult the SOP, and propose corrective recovery steps.\n"
            "\n"
            "Rules:\n"
            "- You may ONLY use capabilities from the recovery list below.\n"
            "- Do NOT invent new capabilities.\n"
            "- Do NOT immediately repeat the failed capability.\n"
            "- Return ONLY the structured JSON response.\n"
            "\n"
            f"Event Type: {event_type}\n"
            f"Failed Capability: {failed_capability}\n"
            f"Error Message: {error_message}\n"
            f"Remaining Steps: {remaining_steps}\n"
            "\n"
            "Available Recovery Capabilities:\n"
            f"{cap_schemas}\n"
            "\n"
            "SOP Document:\n"
            f"{sop_text}\n"
        )
        if experience_context:
            base += f"\n{experience_context}\n"
        base += (
            "\n"
            "Return format:\n"
            '{\n'
            '  "reflection_summary": "<concise summary of what failed and why>",\n'
            '  "correction_rationale": "<why these recovery steps are appropriate>",\n'
            '  "recovery_decision": "<detailed recovery strategy explanation>",\n'
            '  "corrective_steps": [{"capability_name": "<name>"}, ...]\n'
            '}\n'
        )
        return base

    # Prompt construction

    @staticmethod
    def _serialize_capabilities(capabilities: list[AgentCapability]) -> str:
        """Build a compact text block listing available capabilities."""
        lines = []
        for cap in capabilities:
            lines.append(
                f"- {cap.name} "
                f"(requires: {list(cap.requires)}, "
                f"produces: {list(cap.produces)}, "
                f"description: {cap.description})"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_prompt(
        event_type: str,
        sop_text: str,
        cap_schemas: str,
        experience_context: str = "",
    ) -> str:
        base = (
            "You are a hospital workflow planner.\n"
            "\n"
            "You will be given a Standard Operating Procedure (SOP) document "
            "and a list of available system capabilities.\n"
            "\n"
            "Your task is to select and order the capabilities that best "
            "satisfy the SOP steps for this event.\n"
            "\n"
            "Rules:\n"
            "- You may ONLY use capabilities from the list below.\n"
            "- Do NOT invent new capabilities.\n"
            "- Do NOT provide arguments, agent names, or output fields.\n"
            "- Return ONLY the capability names in execution order.\n"
            "- Respond with valid JSON only.\n"
            "\n"
            f"Event Type: {event_type}\n"
            "\n"
            "Available Capabilities:\n"
            f"{cap_schemas}\n"
            "\n"
            "SOP Document:\n"
            f"{sop_text}\n"
        )
        if experience_context:
            base += f"\n{experience_context}\n"
        base += (
            "\n"
            "Return format:\n"
            '{"steps": [{"capability_name": "<name>"}, ...]}\n'
        )
        return base

    # LLM call

    @staticmethod
    def _call_llm(prompt: str) -> str:
        """Call the NVIDIA NIM endpoint and return the raw content string."""
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY not configured for SOP planner")

        payload = {
            "model": PLANNING_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": PLANNING_TEMPERATURE,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        start = time.perf_counter()
        response = requests.post(
            NVIDIA_NIM_URL,
            headers=headers,
            json=payload,
            timeout=PLANNING_TIMEOUT,
        )
        response.raise_for_status()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        print(f"[SOP_PLANNER] LLM call completed in {elapsed_ms}ms")

        data = response.json()
        return data["choices"][0]["message"]["content"]

    # Response parsing

    @staticmethod
    def _parse_llm_response(raw_json: str) -> list[str]:
        """Parse LLM JSON response into a list of capability names.

        Raises ValueError on malformed output.
        """
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}")

        steps = parsed.get("steps")
        if not isinstance(steps, list):
            raise ValueError(
                f"LLM response missing 'steps' list, got: {type(steps)}"
            )

        names = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or "capability_name" not in step:
                raise ValueError(
                    f"Step {i} missing 'capability_name' key: {step}"
                )
            names.append(step["capability_name"])

        if not names:
            raise ValueError("LLM returned empty steps list")

        return names

    # Deterministic validation

    def _validate(
        self,
        proposed_names: list[str],
        event_type: str,
        available_keys: set[str],
    ) -> None:
        """Run all validation checks. Raises SOPValidationException on failure."""
        errors: list[str] = []

        # 1. Capability authenticity: every name must exist in the registry
        for name in proposed_names:
            try:
                self._registry.get_capability(name)
            except KeyError:
                errors.append(f"Unregistered capability: '{name}'")

        if errors:
            raise SOPValidationException(errors)

        # 2. Event compatibility: each capability must handle this event_type
        for name in proposed_names:
            cap = self._registry.get_capability(name)
            if event_type not in cap.handles_events:
                errors.append(
                    f"Capability '{name}' does not handle event '{event_type}'"
                )

        # 3. No duplicate steps
        seen = set()
        for name in proposed_names:
            if name in seen:
                errors.append(f"Duplicate capability in plan: '{name}'")
            seen.add(name)

        # 4. Mandatory step verification
        mandatory = MANDATORY_CAPABILITIES.get(event_type, set())
        missing = mandatory - set(proposed_names)
        if missing:
            errors.append(
                f"Missing mandatory capabilities for {event_type}: {sorted(missing)}"
            )

        # 5. Dependency resolution: each step's requires must be satisfiable
        resolved_keys = set(available_keys)
        for name in proposed_names:
            cap = self._registry.get_capability(name)
            unmet = [k for k in cap.requires if k not in resolved_keys]
            if unmet:
                errors.append(
                    f"Capability '{name}' has unmet requirements: {unmet}"
                )
            resolved_keys.update(cap.produces)

        if errors:
            raise SOPValidationException(errors)

    # Plan construction

    def _build_execution_plan(
        self,
        proposed_names: list[str],
        event_type: str,
    ) -> ExecutionPlan:
        """Convert validated capability names into an ExecutionPlan."""
        steps = []
        for name in proposed_names:
            cap = self._registry.get_capability(name)
            steps.append(
                PlanStep(
                    capability_name=cap.name,
                    agent_name=cap.agent_name,
                    requires=cap.requires,
                    produces=cap.produces,
                    continue_on_failure=cap.continue_on_failure,
                )
            )
        return ExecutionPlan(event_type=event_type, steps=steps)
