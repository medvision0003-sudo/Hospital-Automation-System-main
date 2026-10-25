"""
OrchestrationContext

Carries shared execution state through the planner and executor.
Avoids passing many loose parameters and gives every step a
single, consistent view of the workflow.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session


@dataclass
class OrchestrationContext:
    """Mutable state bag shared across a single orchestration run.

    Attributes:
        db:                  Active SQLAlchemy session forwarded to agents.
        workflow_id:         UUID identifying this workflow execution.
        event_type:          The HospitalEventEnum value that triggered this run.
        payload:             Raw event payload dict from the caller.
        metadata:            Arbitrary key-value metadata produced during execution.
        produced:            Accumulated outputs from completed steps. Later steps
                             can read values placed here by earlier steps.
        workflow_execution:  Ordered list of execution trace dicts
                             (matches the existing ExecutionStep schema).
        actor:               Optional identifier for the user or system that
                             initiated this event.
        request_id:          Optional external correlation ID.
    """

    db: Session
    workflow_id: str
    event_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    produced: dict[str, Any] = field(default_factory=dict)
    workflow_execution: list[dict[str, str]] = field(default_factory=list)
    status: str = "SUCCESS"
    actor: Optional[str] = None
    request_id: Optional[str] = None

    # Helpers

    def get(self, key: str, default: Any = None) -> Any:
        """Look up a value from produced outputs, falling back to payload."""
        if key in self.produced:
            return self.produced[key]
        return self.payload.get(key, default)

    def has(self, key: str) -> bool:
        """Check whether a key is available in produced or payload."""
        return key in self.produced or key in self.payload

    def merge_produced(self, values: dict[str, Any]) -> None:
        """Merge a dict of produced values into the context."""
        self.produced.update(values)
