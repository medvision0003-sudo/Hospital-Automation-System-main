from sqlalchemy.orm import Session

from app.models.agent_table import AgentTable
from app.orchestrator.constants import (
    ASSIGNMENT_AGENT,
    COMMUNICATION_AGENT,
    EMERGENCY_RESPONSE_AGENT,
    EVENT_AGENT,
    ORCHESTRATOR_AGENT,
    TASK_MANAGEMENT_AGENT,
    TASK_VERIFICATION_AGENT,
    WORKFORCE_AGENT,
)


AGENT_DEFINITIONS = (
    (1, ORCHESTRATOR_AGENT, "Coordinates registered agent capabilities and workflow execution."),
    (2, ASSIGNMENT_AGENT, "Selects eligible workers and balances task assignments."),
    (3, TASK_MANAGEMENT_AGENT, "Creates work items and manages task lifecycle transitions."),
    (4, WORKFORCE_AGENT, "Tracks worker attendance, availability, and shift handovers."),
    (5, EVENT_AGENT, "Validates incoming hospital events and forwards them to workflows."),
    (6, EMERGENCY_RESPONSE_AGENT, "Maps emergency events to hospital response tasks."),
    (7, TASK_VERIFICATION_AGENT, "Evaluates task proof images and routes uncertain results for review."),
    (8, COMMUNICATION_AGENT, "Sends task notifications and processes WhatsApp worker messages."),
)


def seed_agent_registry(db: Session) -> None:
    """Ensure fixed agent IDs used by action logs are registered consistently."""
    for agent_id, agent_name, description in AGENT_DEFINITIONS:
        by_id = db.query(AgentTable).filter(
            AgentTable.agent_id == agent_id
        ).first()
        by_name = db.query(AgentTable).filter(
            AgentTable.agent_name == agent_name
        ).first()

        if by_name and by_name.agent_id != agent_id:
            raise RuntimeError(
                f"Agent {agent_name} is registered with ID {by_name.agent_id}; "
                f"agent action logging requires ID {agent_id}."
            )
        if by_id and by_id.agent_name != agent_name:
            raise RuntimeError(
                f"Agent ID {agent_id} belongs to {by_id.agent_name}, "
                f"expected {agent_name}."
            )
        if by_id is None:
            db.add(
                AgentTable(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_category=agent_name,
                    description=description,
                )
            )
        else:
            by_id.agent_category = agent_name
            by_id.description = description

    db.commit()
