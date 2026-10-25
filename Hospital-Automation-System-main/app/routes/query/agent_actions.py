from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database.connection import get_db
from app.models.agent_action_log import AgentActionLog
from app.schemas.agent_action import AgentActionResponse

router = APIRouter(prefix="/agent-actions", tags=["Query - Agent Actions"])


@router.get("/", response_model=List[AgentActionResponse])
def get_all_agent_actions(db: Session = Depends(get_db)):
    actions = db.query(AgentActionLog).all()
    return actions


@router.get("/event/{event_id}", response_model=List[AgentActionResponse])
def get_agent_actions_by_event(event_id: int, db: Session = Depends(get_db)):
    actions = db.query(AgentActionLog).filter(
        AgentActionLog.event_id == event_id
    ).all()

    return actions


@router.get("/{action_id}", response_model=AgentActionResponse)
def get_agent_action(action_id: int, db: Session = Depends(get_db)):
    action = db.query(AgentActionLog).filter(
        AgentActionLog.agent_action_id == action_id
    ).first()

    if not action:
        raise HTTPException(status_code=404, detail="Agent action not found")

    return action
