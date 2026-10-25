"""
Dashboard Pydantic response schemas.

These models define the JSON contract for GET /dashboard/.
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


# Summary Cards

class DashboardSummary(BaseModel):
    total_departments: int = 0
    checked_in_workers: int = 0
    pending_tasks: int = 0
    tasks_in_progress: int = 0
    completed_today: int = 0
    pending_supervisor_requests: int = 0
    active_emergencies: int = 0
    total_employees: int = 0


# Operations

class WorkQueueOps(BaseModel):
    pending: int = 0
    assigned: int = 0
    completed: int = 0


class EmployeeOps(BaseModel):
    checked_in: int = 0
    available: int = 0
    busy: int = 0
    off_shift: int = 0
    total_registered: int = 0


class DashboardOperations(BaseModel):
    work_queue: WorkQueueOps = WorkQueueOps()
    employees: EmployeeOps = EmployeeOps()


# Department Workload

class DepartmentWorkloadItem(BaseModel):
    department_id: int
    department_name: str
    description: Optional[str] = None
    pending_tasks: int = 0
    assigned_tasks: int = 0
    available_workers: int = 0
    total_staff: int = 0


# Recent Events

class RecentEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    event_log: str
    source_module: str
    employee_id: Optional[int] = None
    work_id: Optional[int] = None
    assignment_id: Optional[int] = None
    timestamp: datetime


# Top-Level Response

class DashboardResponse(BaseModel):
    status: str = "SUCCESS"
    summary: DashboardSummary = DashboardSummary()
    operations: DashboardOperations = DashboardOperations()
    departments: list[DepartmentWorkloadItem] = []
    recent_events: list[RecentEventItem] = []
