"""
Failure and Continuation Policies

Defines structured failure behaviour preferences per event type.
The executor consults these policies to decide whether to abort,
continue, or mark a workflow as partial success when a step fails.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailurePolicy:
    """Describes how the executor should behave when a step fails.

    Attributes:
        event_type:              The HospitalEventEnum value this policy applies to.
        continue_on_failure:     If True, the executor records the error and
                                 proceeds to the next step.
        partial_success_allowed: If True, a workflow that completed some steps
                                 before a failure may return PARTIAL_SUCCESS
                                 instead of FAILED.
        rollback_on_failure:     Reserved for future use. If True, previously
                                 completed steps should be compensated.
    """

    event_type: str
    continue_on_failure: bool = False
    partial_success_allowed: bool = False
    rollback_on_failure: bool = False


# Pre-defined policies keyed by event type.
# Policies for events not listed here default to strict (abort on failure).

DEFAULT_POLICIES: dict[str, FailurePolicy] = {

    "DYNAMIC_TASK_REQUEST": FailurePolicy(
        event_type="DYNAMIC_TASK_REQUEST",
        continue_on_failure=False,
        partial_success_allowed=True,
    ),

    "WORKER_CHECKED_IN": FailurePolicy(
        event_type="WORKER_CHECKED_IN",
        continue_on_failure=False,
        partial_success_allowed=True,
    ),

    "TASK_COMPLETED": FailurePolicy(
        event_type="TASK_COMPLETED",
        continue_on_failure=False,
        partial_success_allowed=False,
    ),

    "TASK_CANCELLED": FailurePolicy(
        event_type="TASK_CANCELLED",
        continue_on_failure=False,
        partial_success_allowed=False,
    ),

    "SUPERVISOR_REQUEST_CREATED": FailurePolicy(
        event_type="SUPERVISOR_REQUEST_CREATED",
        continue_on_failure=False,
        partial_success_allowed=True,
    ),

    "EMERGENCY_RESPONSE": FailurePolicy(
        event_type="EMERGENCY_RESPONSE",
        continue_on_failure=True,
        partial_success_allowed=True,
    ),
}

# Strict default for unknown event types
_STRICT_POLICY = FailurePolicy(
    event_type="__default__",
    continue_on_failure=False,
    partial_success_allowed=False,
)


def get_policy(event_type: str) -> FailurePolicy:
    """Return the failure policy for an event type, falling back to strict."""
    return DEFAULT_POLICIES.get(event_type, _STRICT_POLICY)
