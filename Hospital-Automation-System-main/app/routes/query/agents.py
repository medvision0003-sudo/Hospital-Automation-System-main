from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List

from app.database.connection import get_db
from app.models.agent_table import AgentTable
from app.models.agent_action_log import AgentActionLog
from app.models.enums import AgentActionStatusEnum
from app.schemas.agent_table import AgentTableResponse
from app.schemas.agent_action import AgentActionResponse
from app.schemas.capability import AgentStatsResponse

router = APIRouter(prefix="/agents", tags=["Query - Agents"])


@router.get("/", response_model=List[AgentTableResponse])
def get_all_agents(db: Session = Depends(get_db)):
    agents = db.query(AgentTable).all()
    return agents


@router.get("/{agent_id}", response_model=AgentTableResponse)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = db.query(AgentTable).filter(
        AgentTable.agent_id == agent_id
    ).first()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return agent


@router.get("/{agent_id}/stats", response_model=AgentStatsResponse)
def get_agent_stats(agent_id: int, db: Session = Depends(get_db)):
    agent = db.query(AgentTable).filter(
        AgentTable.agent_id == agent_id
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    stats = db.query(
        func.count(AgentActionLog.agent_action_id).label("total"),
        func.sum(case((AgentActionLog.execution_status == AgentActionStatusEnum.SUCCESS, 1), else_=0)).label("success"),
        func.sum(case((AgentActionLog.execution_status == AgentActionStatusEnum.FAILED, 1), else_=0)).label("failed"),
        func.sum(case((AgentActionLog.execution_status == AgentActionStatusEnum.PENDING, 1), else_=0)).label("pending"),
        func.avg(AgentActionLog.execution_time_ms).label("avg_time"),
        func.max(AgentActionLog.action_timestamp).label("last_active")
    ).filter(
        AgentActionLog.agent_id == agent_id
    ).first()

    total = stats.total or 0
    success = stats.success or 0
    failed = stats.failed or 0
    pending = stats.pending or 0
    avg_time = stats.avg_time
    last_active_dt = stats.last_active

    return AgentStatsResponse(
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        total_executions=total,
        success_count=success,
        failed_count=failed,
        pending_count=pending,
        success_rate=round((success / total * 100), 1) if total > 0 else 0.0,
        avg_execution_time_ms=round(avg_time, 1) if avg_time else None,
        last_active=last_active_dt.isoformat() if last_active_dt else None,
    )


@router.get("/{agent_id}/actions", response_model=List[AgentActionResponse])
def get_agent_actions(agent_id: int, limit: int = 50, db: Session = Depends(get_db)):
    actions = (
        db.query(AgentActionLog)
        .filter(AgentActionLog.agent_id == agent_id)
        .order_by(AgentActionLog.action_timestamp.desc())
        .limit(limit)
        .all()
    )
    return actions
