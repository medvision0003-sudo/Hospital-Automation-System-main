"""
Capability Registry

Central store of all declared AgentCapability instances.
Supports lookup by capability name and query by event type.
This replaces the need to manually wire every event inside
hospital_orchestrator.py.
"""

from app.orchestrator.intelligence.capabilities import AgentCapability


class CapabilityRegistry:
    """In-memory registry of agent capabilities.

    Usage:
        registry = CapabilityRegistry()
        registry.register(some_capability)
        caps = registry.get_capabilities_for_event("DYNAMIC_TASK_REQUEST")
    """

    def __init__(self) -> None:
        self._by_name: dict[str, AgentCapability] = {}
        self._by_event: dict[str, list[AgentCapability]] = {}

    def register(self, capability: AgentCapability) -> None:
        """Register a capability. Raises ValueError on duplicate names."""
        if capability.name in self._by_name:
            raise ValueError(
                f"Capability '{capability.name}' is already registered."
            )

        self._by_name[capability.name] = capability

        for event in capability.handles_events:
            self._by_event.setdefault(event, []).append(capability)

    def get_capability(self, name: str) -> AgentCapability:
        """Return a capability by exact name. Raises KeyError if missing."""
        if name not in self._by_name:
            raise KeyError(f"No capability registered with name '{name}'.")
        return self._by_name[name]

    def get_capabilities_for_event(self, event_type: str) -> list[AgentCapability]:
        """Return all capabilities that declare they handle ``event_type``.

        Results are sorted by priority (ascending).
        """
        caps = self._by_event.get(event_type, [])
        return sorted(caps, key=lambda c: c.priority)

    def supports_event(self, event_type: str) -> bool:
        """Check whether at least one capability handles this event."""
        return bool(self._by_event.get(event_type))

    def list_capabilities(self) -> list[AgentCapability]:
        """Return all registered capabilities sorted by name."""
        return sorted(self._by_name.values(), key=lambda c: c.name)


# Instantiate default registry and register Phase 2 capabilities
default_registry = CapabilityRegistry()

from app.orchestrator.intelligence.agent_adapters import (
    create_work_item_adapter,
    assign_work_item_adapter,
    create_work_item_idempotency,
    assign_work_item_idempotency,
)
from app.orchestrator.constants import TASK_MANAGEMENT_AGENT, ASSIGNMENT_AGENT

default_registry.register(AgentCapability(
    name="create_work_item",
    agent_name=TASK_MANAGEMENT_AGENT,
    handles_events=("DYNAMIC_TASK_REQUEST", "SUPERVISOR_REQUEST_CREATED"),
    requires=("task_id", "due_date"),
    produces=("work_id", "task_name", "department_id", "department_name", "shift_id", "priority"),
    priority=10,
    handler=create_work_item_adapter,
    idempotency_check=create_work_item_idempotency,
    description="Creates a work queue item from a task definition.",
))

default_registry.register(AgentCapability(
    name="assign_work_item",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("DYNAMIC_TASK_REQUEST", "SUPERVISOR_REQUEST_CREATED", "RECURRING_TASK_GENERATED"),
    requires=("work_id",),
    produces=("assignment_id", "employee_id", "employee_name"),
    priority=20,
    handler=assign_work_item_adapter,
    idempotency_check=assign_work_item_idempotency,
    description="Assigns a work queue item to the best checked-in employee.",
))

# Phase 5 capabilities: WORKER_CHECKED_IN

from app.orchestrator.intelligence.agent_adapters import (
    checkin_worker_adapter,
    checkout_worker_adapter,
    generate_shift_tasks_adapter,
    run_assignment_cycle_adapter,
    run_assignment_cycle_for_shift_start_adapter,
    checkin_worker_idempotency,
)
from app.orchestrator.constants import WORKFORCE_AGENT

default_registry.register(AgentCapability(
    name="checkin_worker",
    agent_name=WORKFORCE_AGENT,
    handles_events=("WORKER_CHECKED_IN",),
    requires=("employee_id",),
    produces=("employee_id", "employee_name", "department_id", "department_name",
              "shift_id", "roster_id", "checked_in"),
    priority=10,
    handler=checkin_worker_adapter,
    idempotency_check=checkin_worker_idempotency,
    description="Checks in an employee for their rostered shift.",
))

default_registry.register(AgentCapability(
    name="checkout_worker",
    agent_name=WORKFORCE_AGENT,
    handles_events=("WORKER_CHECKED_OUT",),
    requires=("employee_id",),
    produces=("employee_id", "checkout_time", "released_assignments", "handover_status"),
    priority=10,
    handler=checkout_worker_adapter,
    description="Checks out an employee and processes shift handover.",
))

default_registry.register(AgentCapability(
    name="generate_shift_tasks",
    agent_name=TASK_MANAGEMENT_AGENT,
    handles_events=("WORKER_CHECKED_IN",),
    requires=("department_id", "shift_id"),
    produces=("generated_work_ids", "generated_count", "tasks"),
    priority=15,
    handler=generate_shift_tasks_adapter,
    description="Generates due task-schedule work for the employee's active department and shift.",
))

default_registry.register(AgentCapability(
    name="run_assignment_cycle",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("WORKER_CHECKED_IN",),
    requires=("department_id", "generated_work_ids"),
    produces=("total_assigned", "total_failed", "assigned", "failures"),
    priority=20,
    handler=run_assignment_cycle_adapter,
    description="Runs a full assignment cycle for a department after worker check-in.",
))

default_registry.register(AgentCapability(
    name="run_assignment_cycle_for_shift_start",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("SHIFT_STARTED",),
    requires=("roster_id",),
    produces=("department_id", "total_assigned", "total_failed", "assigned", "failures"),
    priority=10,
    handler=run_assignment_cycle_for_shift_start_adapter,
    description="Reevaluates pending tasks when a scheduled shift becomes active.",
))

# Follow-up cycle for single-task events.
# After assigning the new task, this sweeps the department queue
# to re-route any pending work (including preempted tasks).
default_registry.register(AgentCapability(
    name="run_assignment_cycle_followup",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("DYNAMIC_TASK_REQUEST", "SUPERVISOR_REQUEST_CREATED"),
    requires=("department_id",),
    produces=("total_assigned", "total_failed", "assigned", "failures"),
    priority=30,
    handler=run_assignment_cycle_adapter,
    description="Follow-up cycle after single-task assignment to re-route any pending department work.",
))

# Phase 6 capabilities: TASK_COMPLETED and TASK_CANCELLED

from app.orchestrator.intelligence.agent_adapters import (
    complete_work_item_adapter,
    cancel_work_item_adapter,
    update_worker_task_metrics_adapter,
    complete_work_item_idempotency,
    cancel_work_item_idempotency,
)

default_registry.register(AgentCapability(
    name="complete_work_item",
    agent_name=TASK_MANAGEMENT_AGENT,
    handles_events=("TASK_COMPLETED",),
    requires=("work_id",),
    produces=("work_id", "old_status", "new_status", "employee_id",
              "event_id", "agent_action_id", "assignment_id"),
    priority=10,
    handler=complete_work_item_adapter,
    idempotency_check=complete_work_item_idempotency,
    description="Marks a work queue item as COMPLETED.",
))

default_registry.register(AgentCapability(
    name="cancel_work_item",
    agent_name=TASK_MANAGEMENT_AGENT,
    handles_events=("TASK_CANCELLED",),
    requires=("work_id",),
    produces=("work_id", "old_status", "new_status", "employee_id",
              "event_id", "agent_action_id", "assignment_id"),
    priority=10,
    handler=cancel_work_item_adapter,
    idempotency_check=cancel_work_item_idempotency,
    description="Marks a work queue item as CANCELLED.",
))

default_registry.register(AgentCapability(
    name="update_worker_task_metrics",
    agent_name=WORKFORCE_AGENT,
    handles_events=("TASK_COMPLETED", "TASK_CANCELLED", "TASK_PROOF_SUBMITTED"),
    requires=("employee_id", "new_status"),
    produces=("employee_id", "pending_task", "total_task_completed"),
    priority=30,
    handler=update_worker_task_metrics_adapter,
    description="Updates WorkerMemory metrics under the Workforce Agent.",
))

# Phase 7 capabilities: SUPERVISOR_REQUEST_CREATED

from app.orchestrator.intelligence.agent_adapters import (
    load_supervisor_request_adapter,
    mark_supervisor_request_processed_adapter,
    mark_supervisor_request_processed_idempotency,
)
from app.orchestrator.constants import ORCHESTRATOR_AGENT

default_registry.register(AgentCapability(
    name="load_supervisor_request",
    agent_name=ORCHESTRATOR_AGENT,
    handles_events=("SUPERVISOR_REQUEST_CREATED",),
    requires=("request_id",),
    produces=("task_id", "due_date", "priority_override", "request_id"),
    priority=5,
    handler=load_supervisor_request_adapter,
    description="Loads a supervisor task request and checks idempotency.",
))

default_registry.register(AgentCapability(
    name="mark_supervisor_request_processed",
    agent_name=ORCHESTRATOR_AGENT,
    handles_events=("SUPERVISOR_REQUEST_CREATED",),
    requires=("request_id", "assignment_id"),
    produces=(),
    priority=40,
    handler=mark_supervisor_request_processed_adapter,
    idempotency_check=mark_supervisor_request_processed_idempotency,
    description="Marks a supervisor task request as processed after successful assignment.",
))

# Phase 8 capabilities: EMERGENCY_RESPONSE

from app.orchestrator.intelligence.agent_adapters import (
    handle_emergency_adapter,
    assign_emergency_work_items_adapter,
)
from app.orchestrator.constants import EMERGENCY_RESPONSE_AGENT

default_registry.register(AgentCapability(
    name="handle_emergency",
    agent_name=EMERGENCY_RESPONSE_AGENT,
    handles_events=("EMERGENCY_RESPONSE",),
    requires=("emergency_type", "location", "reported_by"),
    produces=("work_ids", "emergency_type", "location", "reported_by",
              "tasks_created", "task_creation_failures"),
    priority=10,
    handler=handle_emergency_adapter,
    description="Validates emergency, generates response plan, and creates work items.",
))

default_registry.register(AgentCapability(
    name="assign_emergency_work_items",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("EMERGENCY_RESPONSE",),
    requires=("work_ids",),
    produces=("assignments", "assignment_failures"),
    priority=20,
    handler=assign_emergency_work_items_adapter,
    continue_on_failure=True,
    description="Resilient per-item assignment for emergency work items.",
))

# Step 3 capabilities: Autonomous Watcher Events

from app.orchestrator.constants import ORCHESTRATOR_AGENT
from app.orchestrator.intelligence.agent_adapters import (
    handle_task_timeout_adapter,
    handle_staff_shortage_adapter,
    rebalance_overloaded_worker_adapter,
    handle_shift_change_adapter,
    handle_staff_absent_adapter,
    reassign_absent_worker_tasks_adapter,
)

default_registry.register(AgentCapability(
    name="handle_task_timeout",
    agent_name=ORCHESTRATOR_AGENT,
    handles_events=("TASK_TIMEOUT_DETECTED",),
    requires=("work_id",),
    produces=("work_id", "action"),
    priority=10,
    handler=handle_task_timeout_adapter,
    description="Handles task timeout detection (v1: placeholder logging).",
))

default_registry.register(AgentCapability(
    name="handle_staff_shortage",
    agent_name=ORCHESTRATOR_AGENT,
    handles_events=("STAFF_SHORTAGE_DETECTED",),
    requires=("work_id",),
    produces=("work_id", "action"),
    priority=10,
    handler=handle_staff_shortage_adapter,
    description="Handles staff shortage detection (v1: placeholder logging).",
))

default_registry.register(AgentCapability(
    name="rebalance_overloaded_worker",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("WORKER_OVERLOAD_DETECTED",),
    requires=("employee_id",),
    produces=("department_id", "preempted_work_ids", "total_preempted"),
    priority=10,
    handler=rebalance_overloaded_worker_adapter,
    description="Rebalance overloaded worker by preempting LOW/MEDIUM non-specialized ASSIGNED tasks.",
))

default_registry.register(AgentCapability(
    name="run_assignment_cycle_overload",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("WORKER_OVERLOAD_DETECTED",),
    requires=("department_id",),
    produces=("total_assigned", "total_failed", "assigned", "failures"),
    priority=20,
    handler=run_assignment_cycle_adapter,
    description="Reroute preempted tasks after overload rebalancing.",
))

default_registry.register(AgentCapability(
    name="handle_shift_change",
    agent_name=WORKFORCE_AGENT,
    handles_events=("SHIFT_CHANGE_DETECTED",),
    requires=("roster_id",),
    produces=("roster_id", "employee_id", "released_count"),
    priority=10,
    handler=handle_shift_change_adapter,
    description="Handles shift-end cleanup: releases active assignments, reverts work items, and recalculates metrics.",
))

default_registry.register(AgentCapability(
    name="handle_staff_absent",
    agent_name=WORKFORCE_AGENT,
    handles_events=("STAFF_ABSENT_DETECTED",),
    requires=("roster_id",),
    produces=("roster_id", "employee_id", "old_status", "new_status", "released_work_ids"),
    priority=10,
    handler=handle_staff_absent_adapter,
    description="Marks a roster entry as ABSENT when a worker fails to check in within the grace period.",
))

default_registry.register(AgentCapability(
    name="reassign_absent_worker_tasks",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=("STAFF_ABSENT_DETECTED",),
    requires=("roster_id",),
    produces=("total_assigned", "total_failed", "assigned", "failures"),
    priority=20,
    handler=reassign_absent_worker_tasks_adapter,
    description="Reassigns unstarted work released from an absent employee to current eligible staff.",
))


# Task Proof Verification and Completion Loop (Outbox/Orchestrator integration)

from app.orchestrator.intelligence.agent_adapters import verify_task_proof_adapter
from app.orchestrator.constants import TASK_VERIFICATION_AGENT

default_registry.register(AgentCapability(
    name="verify_task_proof",
    agent_name=TASK_VERIFICATION_AGENT,
    handles_events=("TASK_PROOF_SUBMITTED",),
    requires=("work_id", "proof_image_path"),
    produces=("proof_verified", "verification_confidence", "verification_rationale"),
    priority=10,
    handler=verify_task_proof_adapter,
    description="Verifies the submitted proof for task completion.",
))

default_registry.register(AgentCapability(
    name="complete_work_item_for_proof",
    agent_name=TASK_MANAGEMENT_AGENT,
    handles_events=("TASK_PROOF_SUBMITTED",),
    requires=("work_id", "proof_verified"),
    produces=("work_id", "old_status", "new_status", "employee_id",
              "event_id", "agent_action_id", "assignment_id"),
    priority=20,
    handler=complete_work_item_adapter,
    description="Marks a work queue item as COMPLETED.",
))


# WhatsApp Notification (Communication Agent)

from app.orchestrator.intelligence.agent_adapters import (
    send_whatsapp_task_notification_adapter,
)
from app.orchestrator.constants import COMMUNICATION_AGENT

default_registry.register(AgentCapability(
    name="send_whatsapp_task_notification",
    agent_name=COMMUNICATION_AGENT,
    handles_events=("SEND_WHATSAPP_NOTIFICATION",),
    requires=("employee_id", "work_id"),
    produces=("message_id", "status"),
    priority=10,
    handler=send_whatsapp_task_notification_adapter,
    description="Sends a WhatsApp task notification to the assigned worker.",
))

# Self-Correction Recovery Capability

from app.orchestrator.intelligence.agent_adapters import (
    recover_assignment_cycle_adapter,
)

default_registry.register(AgentCapability(
    name="recover_assignment_cycle",
    agent_name=ASSIGNMENT_AGENT,
    handles_events=(),
    requires=("department_id",),
    produces=("total_assigned", "total_failed", "assigned", "failures"),
    priority=99,
    handler=recover_assignment_cycle_adapter,
    description="Recovery cycle to re-route pending tasks after transient failures.",
))
