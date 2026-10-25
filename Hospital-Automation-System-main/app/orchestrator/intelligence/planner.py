"""
Intelligent Planner

Builds an ordered execution plan from the event type, payload,
and the capabilities registered in the CapabilityRegistry.

The planner resolves dependency order using the ``requires`` and
``produces`` declarations on each capability. It performs a
topological sort so that a step only runs after all its required
keys are either present in the original payload or produced by
an earlier step.
"""

from dataclasses import dataclass, field

from app.orchestrator.intelligence.capabilities import AgentCapability
from app.orchestrator.intelligence.registry import CapabilityRegistry


@dataclass(frozen=True)
class PlanStep:
    """A single step inside an execution plan."""
    capability_name: str
    agent_name: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    continue_on_failure: bool = False


@dataclass(frozen=True)
class ExecutionPlan:
    """Ordered sequence of steps the executor should run."""
    event_type: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0


class IntelligentPlanner:
    """Deterministic capability planner.

    Given an event type and the keys available in the payload, the
    planner queries the registry for matching capabilities, then
    topologically sorts them so that each step's ``requires`` are
    satisfied by the payload or by earlier steps' ``produces``.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def supports(self, event_type: str) -> bool:
        """Check whether the registry has capabilities for this event."""
        return self._registry.supports_event(event_type)

    def plan(self, event_type: str, available_keys: set[str]) -> ExecutionPlan:
        """Build an execution plan for the given event.

        Args:
            event_type:      HospitalEventEnum value string.
            available_keys:  Set of keys already present in the payload.

        Returns:
            An ExecutionPlan with topologically sorted steps.

        Raises:
            ValueError: If a capability's requirements cannot be
                        satisfied by the payload or by prior steps.
        """
        capabilities = self._registry.get_capabilities_for_event(event_type)

        if not capabilities:
            return ExecutionPlan(event_type=event_type)

        ordered = self._topological_sort(capabilities, available_keys)

        steps = [
            PlanStep(
                capability_name=cap.name,
                agent_name=cap.agent_name,
                requires=cap.requires,
                produces=cap.produces,
                continue_on_failure=cap.continue_on_failure,
            )
            for cap in ordered
        ]

        return ExecutionPlan(event_type=event_type, steps=steps)

    @staticmethod
    def _topological_sort(
        capabilities: list[AgentCapability],
        available_keys: set[str],
    ) -> list[AgentCapability]:
        """Order capabilities so every step's requires are satisfied.

        Uses a simple iterative resolution algorithm:
        1. Start with the set of keys from the payload.
        2. On each pass, find capabilities whose requires are all
           in the available set, add them to the result, and extend
           the available set with their produces.
        3. Repeat until all capabilities are placed or no progress
           is made (which means unresolvable dependencies).
        """
        remaining = list(capabilities)
        ordered: list[AgentCapability] = []
        resolved_keys = set(available_keys)

        while remaining:
            progress = False
            still_remaining = []

            for cap in remaining:
                if all(key in resolved_keys for key in cap.requires):
                    ordered.append(cap)
                    resolved_keys.update(cap.produces)
                    progress = True
                else:
                    still_remaining.append(cap)

            remaining = still_remaining

            if not progress:
                unresolved_names = [c.name for c in remaining]
                missing = {}
                for c in remaining:
                    missing[c.name] = [
                        k for k in c.requires if k not in resolved_keys
                    ]
                raise ValueError(
                    f"Cannot resolve dependencies for capabilities: "
                    f"{unresolved_names}. Missing keys: {missing}"
                )

        return ordered
