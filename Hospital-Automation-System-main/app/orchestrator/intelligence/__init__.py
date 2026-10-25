"""
Intelligent Orchestrator Package

Provides the capability-driven planning and execution layer
that sits above existing agents. This package does NOT replace
agents or workflows; it offers an alternative orchestration path
that the Hospital Orchestrator can opt into per event type.
"""

from app.orchestrator.intelligence.context import OrchestrationContext
from app.orchestrator.intelligence.capabilities import AgentCapability
from app.orchestrator.intelligence.registry import CapabilityRegistry, default_registry
from app.orchestrator.intelligence.planner import IntelligentPlanner, ExecutionPlan, PlanStep
from app.orchestrator.intelligence.executor import IntelligentExecutor
from app.orchestrator.intelligence.policies import FailurePolicy
from app.orchestrator.intelligence.sop_grounded_planner import (
    SOPGroundedPlanner,
    SOPValidationException,
)

__all__ = [
    "OrchestrationContext",
    "AgentCapability",
    "CapabilityRegistry",
    "default_registry",
    "IntelligentPlanner",
    "IntelligentExecutor",
    "ExecutionPlan",
    "PlanStep",
    "FailurePolicy",
    "SOPGroundedPlanner",
    "SOPValidationException",
]

