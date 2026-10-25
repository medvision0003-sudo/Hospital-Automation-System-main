"""
AgentCapability

Declarative description of a single executable behaviour that an
agent exposes. Capabilities declare what events they handle, what
inputs they require, what outputs they produce, and point to a
handler function that performs the actual work.
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Optional


@dataclass(frozen=True)
class AgentCapability:
    """Immutable declaration of an agent capability.

    Attributes:
        name:                Unique capability identifier (e.g. "create_work_item").
        agent_name:          Constant from orchestrator.constants (e.g. TASK_MANAGEMENT_AGENT).
        handles_events:      Tuple of HospitalEventEnum values this capability applies to.
        requires:            Tuple of keys that must be present in the context
                             (payload or produced) before the handler can run.
        produces:            Tuple of keys the handler will add to context.produced.
        priority:            Lower numbers run first when multiple capabilities
                             match the same event and have no dependency ordering.
        handler:             Callable(payload: dict, context: OrchestrationContext) -> dict.
                             Returns a dict whose keys match ``produces``.
        continue_on_failure: If True the executor records the error and moves
                             to the next step instead of aborting the plan.
        description:         Human-readable summary for logging and debugging.
        metadata:            Arbitrary extra data for future extensibility.
    """

    name: str
    agent_name: str
    handles_events: tuple[str, ...]
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    priority: int
    handler: Callable[[dict[str, Any], Any], dict[str, Any]]
    continue_on_failure: bool = False
    description: str = ""
    idempotency_check: Optional[Callable[[dict[str, Any], Any], Optional[dict[str, Any]]]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
