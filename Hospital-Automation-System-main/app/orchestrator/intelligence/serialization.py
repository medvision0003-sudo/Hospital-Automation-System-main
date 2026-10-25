"""
Serialization Helpers

Serialize and deserialize OrchestrationContext and PlanStep objects
for persisting paused workflow state in the database.
"""

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.orchestrator.intelligence.context import OrchestrationContext
from app.orchestrator.intelligence.planner import PlanStep, ExecutionPlan


def serialize_context(context: OrchestrationContext) -> str:
    """Serialize context state to a JSON string.

    The db session is excluded since it cannot be serialized.
    Only workflow metadata, payload, produced outputs, execution
    trace, and status are persisted.
    """
    data = {
        "workflow_id": context.workflow_id,
        "event_type": context.event_type,
        "payload": context.payload,
        "metadata": context.metadata,
        "produced": context.produced,
        "workflow_execution": context.workflow_execution,
        "status": context.status,
        "actor": context.actor,
        "request_id": context.request_id,
    }
    return json.dumps(data, default=str)


def deserialize_context(db: Session, data_json: str) -> OrchestrationContext:
    """Reconstruct an OrchestrationContext from its JSON representation.

    The active database session is bound to the reconstructed context.
    """
    data = json.loads(data_json)
    return OrchestrationContext(
        db=db,
        workflow_id=data["workflow_id"],
        event_type=data["event_type"],
        payload=data.get("payload", {}),
        metadata=data.get("metadata", {}),
        produced=data.get("produced", {}),
        workflow_execution=data.get("workflow_execution", []),
        status=data.get("status", "SUCCESS"),
        actor=data.get("actor"),
        request_id=data.get("request_id"),
    )


def serialize_plan_steps(steps: list[PlanStep]) -> str:
    """Serialize a list of PlanStep dataclasses to a JSON string."""
    data = [
        {
            "capability_name": s.capability_name,
            "agent_name": s.agent_name,
            "requires": list(s.requires),
            "produces": list(s.produces),
            "continue_on_failure": s.continue_on_failure,
        }
        for s in steps
    ]
    return json.dumps(data, default=str)


def deserialize_plan_steps(
    event_type: str,
    data_json: str,
) -> ExecutionPlan:
    """Reconstruct an ExecutionPlan from its JSON representation."""
    data = json.loads(data_json)
    steps = [
        PlanStep(
            capability_name=d["capability_name"],
            agent_name=d["agent_name"],
            requires=tuple(d.get("requires", ())),
            produces=tuple(d.get("produces", ())),
            continue_on_failure=d.get("continue_on_failure", False),
        )
        for d in data
    ]
    return ExecutionPlan(event_type=event_type, steps=steps)
