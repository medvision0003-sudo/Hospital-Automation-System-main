"""
Dashboard routes — Frontend UI analytics endpoints.

Endpoints:
    GET /dashboard/  - Dashboard overview (summary, operations, recent events)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard import get_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/", response_model=DashboardResponse)
def dashboard_overview(db: Session = Depends(get_db)):
    """Return the full dashboard summary for the frontend."""
    return get_dashboard_summary(db)
