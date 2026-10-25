"""
Orchestrator Constants

Centralized string constants for agent names and execution statuses.
Prevents typos and makes refactoring easier.
"""

from enum import Enum


# Agent Names
EVENT_AGENT = "EVENT_AGENT"
TASK_MANAGEMENT_AGENT = "TASK_MANAGEMENT_AGENT"
WORKFORCE_AGENT = "WORKFORCE_AGENT"
ASSIGNMENT_AGENT = "ASSIGNMENT_AGENT"
EMERGENCY_RESPONSE_AGENT = "EMERGENCY_RESPONSE_AGENT"
ORCHESTRATOR_AGENT = "ORCHESTRATOR_AGENT"
TASK_VERIFICATION_AGENT = "TASK_VERIFICATION_AGENT"
COMMUNICATION_AGENT = "COMMUNICATION_AGENT"

# Policy: relative overload threshold
# A worker is considered overworked when their active task count
# exceeds the eligible-pool average by this many tasks.
OVERLOAD_ABOVE_AVG_THRESHOLD = 3


class ExecutionStatus(str, Enum):
    """Workflow and agent execution statuses (inherits str for serialization)."""
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RESUMING = "RESUMING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SKIPPED_ALREADY_DONE = "SKIPPED_ALREADY_DONE"


class AssignmentTrigger:
    """String constants identifying what triggered an assignment cycle."""
    WORKER_CHECKIN = "WORKER_CHECKIN"
    NEW_TASK = "NEW_TASK"
    EMERGENCY = "EMERGENCY"
    SUPERVISOR_REQUEST = "SUPERVISOR_REQUEST"
    TASK_COMPLETED = "TASK_COMPLETED"
    RECOVERY = "RECOVERY"


class ResolutionType:
    """String constants for WorkflowExperience.resolution_type."""
    AUTOMATED_RECOVERY = "AUTOMATED_RECOVERY"
    SUPERVISOR_OVERRIDE = "SUPERVISOR_OVERRIDE"
    UNRESOLVED = "UNRESOLVED"

