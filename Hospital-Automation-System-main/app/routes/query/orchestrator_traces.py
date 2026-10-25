from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database.connection import get_db
from app.models.orchestrator_trace import OrchestratorTrace
from app.schemas.orchestrator_trace import (
    OrchestratorTraceListItem,
    OrchestratorTraceResponse,
)

router = APIRouter(
    prefix="/orchestrator-traces",
    tags=["Query - Orchestrator Traces"],
)


@router.get("/", response_model=List[OrchestratorTraceListItem])
def list_traces(limit: int = 50, db: Session = Depends(get_db)):
    return (
        db.query(OrchestratorTrace)
        .order_by(OrchestratorTrace.started_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/latest", response_model=OrchestratorTraceResponse)
def get_latest_trace(db: Session = Depends(get_db)):
    trace = (
        db.query(OrchestratorTrace)
        .order_by(OrchestratorTrace.started_at.desc())
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="No traces found")
    return trace


@router.get("/{workflow_id}", response_model=OrchestratorTraceResponse)
def get_trace(workflow_id: str, db: Session = Depends(get_db)):
    trace = (
        db.query(OrchestratorTrace)
        .filter(OrchestratorTrace.workflow_id == workflow_id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
