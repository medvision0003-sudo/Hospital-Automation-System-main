"""
Dashboard Service  -  Aggregation Layer

Encapsulates all dashboard metric queries inside a single
DashboardService class. Each internal method is independent
and performs its own queries. Only get_dashboard_summary()
composes the final response.

Tables used:
    Department, Employee, WorkerCheckin, DepartmentWorkQueue,
    TaskAssignment, SupervisorTaskRequest, AgentActionLog,
    WorkerMemory, EventLog
"""

from datetime import datetime, time

from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.worker_checkin import WorkerCheckin
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.agent_action_log import AgentActionLog
from app.models.worker_memory import WorkerMemory
from app.models.event_log import EventLog
from app.models.enums import (
    CheckinStatusEnum,
    EmploymentStatusEnum,
    WorkQueueStatusEnum,
    AssignmentStatusEnum,
)


class DashboardService:
    """Composes the GET /dashboard/ response from independent queries."""

    def __init__(self, db: Session):
        self.db = db

    # Private query helpers

    def _count_checked_in_workers(self) -> int:
        """
        Count employees whose latest check-in status is CHECKED_IN.

        Uses a subquery to find the most recent checkin_time per employee,
        then filters for CHECKED_IN status on that row.
        """
        latest_sub = (
            self.db.query(
                WorkerCheckin.employee_id,
                sql_func.max(WorkerCheckin.checkin_time).label("max_time"),
            )
            .group_by(WorkerCheckin.employee_id)
            .subquery()
        )

        return (
            self.db.query(sql_func.count(WorkerCheckin.employee_id))
            .join(
                latest_sub,
                (WorkerCheckin.employee_id == latest_sub.c.employee_id)
                & (WorkerCheckin.checkin_time == latest_sub.c.max_time),
            )
            .filter(WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN)
            .scalar()
        ) or 0

    def _count_work_queue_by_status(self, status: WorkQueueStatusEnum) -> int:
        """Count DepartmentWorkQueue items matching a given status."""
        return (
            self.db.query(sql_func.count(DepartmentWorkQueue.work_id))
            .filter(DepartmentWorkQueue.queue_status == status)
            .scalar()
        ) or 0

    def _count_completed_today(self) -> int:
        """
        Count DepartmentWorkQueue items completed today.

        Uses TaskAssignment.completed_at to determine the completion date,
        since DepartmentWorkQueue itself does not have a completed_at column.
        """
        start_of_day = datetime.combine(datetime.now().date(), time.min)
        end_of_day = datetime.combine(datetime.now().date(), time(23, 59, 59))

        return (
            self.db.query(sql_func.count(TaskAssignment.assignment_id))
            .filter(
                TaskAssignment.assignment_status == AssignmentStatusEnum.COMPLETED,
                TaskAssignment.completed_at >= start_of_day,
                TaskAssignment.completed_at <= end_of_day,
            )
            .scalar()
        ) or 0

    def _count_pending_supervisor_requests(self) -> int:
        """Count supervisor task requests that have not been processed yet."""
        return (
            self.db.query(sql_func.count(SupervisorTaskRequest.request_id))
            .filter(SupervisorTaskRequest.processed_at.is_(None))
            .scalar()
        ) or 0

    def _count_active_emergencies(self) -> int:
        """
        Count active emergencies.

        V1 (Demo): counts distinct created_at timestamps for work queue
        items that were created by the Emergency Response Agent and are
        still active (PENDING_ASSIGNED or ASSIGNED).

        Long-term design: add a workflow_id or emergency_id column to
        DepartmentWorkQueue and COUNT(DISTINCT workflow_id) instead.
        This removes dependence on timestamp grouping.
        """
        emergency_work_ids_sub = (
            self.db.query(EventLog.work_id)
            .join(
                AgentActionLog,
                AgentActionLog.event_id == EventLog.event_id,
            )
            .filter(
                AgentActionLog.action_type == "CREATE_WORK_ITEM",
                EventLog.source_module == "TASK_MANAGEMENT_AGENT",
                EventLog.work_id.isnot(None),
            )
            .subquery()
        )

        return (
            self.db.query(
                sql_func.count(
                    sql_func.distinct(DepartmentWorkQueue.created_at)
                )
            )
            .filter(
                DepartmentWorkQueue.work_id.in_(
                    self.db.query(emergency_work_ids_sub.c.work_id)
                ),
                DepartmentWorkQueue.queue_status.in_([
                    WorkQueueStatusEnum.PENDING_ASSIGNED,
                    WorkQueueStatusEnum.ASSIGNED,
                ]),
                DepartmentWorkQueue.priority == "CRITICAL",
            )
            .scalar()
        ) or 0

    def _count_busy_employees(self) -> int:
        """
        Count checked-in employees with pending_task > 0 in WorkerMemory.

        An employee is "busy" if they are currently checked in AND have
        at least one pending task.
        """
        latest_sub = (
            self.db.query(
                WorkerCheckin.employee_id,
                sql_func.max(WorkerCheckin.checkin_time).label("max_time"),
            )
            .group_by(WorkerCheckin.employee_id)
            .subquery()
        )

        return (
            self.db.query(sql_func.count(WorkerMemory.employee_id))
            .join(
                latest_sub,
                WorkerMemory.employee_id == latest_sub.c.employee_id,
            )
            .join(
                WorkerCheckin,
                (WorkerCheckin.employee_id == latest_sub.c.employee_id)
                & (WorkerCheckin.checkin_time == latest_sub.c.max_time),
            )
            .filter(
                WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
                WorkerMemory.pending_task > 0,
            )
            .scalar()
        ) or 0

    def _count_total_active_employees(self) -> int:
        """Count all employees with ACTIVE employment status."""
        return (
            self.db.query(sql_func.count(Employee.employee_id))
            .filter(Employee.availability == EmploymentStatusEnum.ACTIVE)
            .scalar()
        ) or 0

    # Section builders

    def _count_total_employees(self) -> int:
        """Count all employees in the employee table."""
        return (
            self.db.query(sql_func.count(Employee.employee_id)).scalar()
        ) or 0

    def _get_summary(self) -> dict:
        """
        Build the summary cards section.

        Each metric runs its own query. No dependency on other helpers.
        """
        total_departments = (
            self.db.query(sql_func.count(Department.department_id)).scalar()
        ) or 0
        total_employees = self._count_total_employees()
        checked_in = self._count_checked_in_workers()
        pending = self._count_work_queue_by_status(WorkQueueStatusEnum.PENDING_ASSIGNED)
        in_progress = self._count_work_queue_by_status(WorkQueueStatusEnum.ASSIGNED)
        completed_today = self._count_completed_today()
        pending_sup = self._count_pending_supervisor_requests()
        emergencies = self._count_active_emergencies()

        return {
            "total_departments": total_departments,
            "checked_in_workers": checked_in,
            "pending_tasks": pending,
            "tasks_in_progress": in_progress,
            "completed_today": completed_today,
            "pending_supervisor_requests": pending_sup,
            "active_emergencies": emergencies,
            "total_employees": total_employees,
        }

    def _get_operations(self) -> dict:
        """
        Build the operations section.

        Runs its own queries for work queue counts and employee
        availability. Does NOT call _get_summary().
        """
        pending = self._count_work_queue_by_status(WorkQueueStatusEnum.PENDING_ASSIGNED)
        assigned = self._count_work_queue_by_status(WorkQueueStatusEnum.ASSIGNED)
        completed = self._count_work_queue_by_status(WorkQueueStatusEnum.COMPLETED)

        total_employees = self._count_total_employees()
        total_active = self._count_total_active_employees()
        checked_in = self._count_checked_in_workers()
        busy = self._count_busy_employees()
        available = checked_in - busy
        off_shift = max(total_employees - checked_in, 0)

        return {
            "work_queue": {
                "pending": pending,
                "assigned": assigned,
                "completed": completed,
            },
            "employees": {
                "checked_in": checked_in,
                "available": available,
                "busy": busy,
                "off_shift": off_shift,
                "total_registered": total_employees,
            },
        }

    def _get_department_workloads(self) -> list[dict]:
        """
        Build per-department workload metrics.

        For each department, counts pending and assigned tasks from the
        DepartmentWorkQueue, counts available workers (checked-in
        employees with latest checkin status CHECKED_IN in that department),
        and counts total registered staff assigned to that department.
        """
        departments = self.db.query(Department).all()

        # Subquery: latest checkin per employee
        latest_checkin_sub = (
            self.db.query(
                WorkerCheckin.employee_id,
                sql_func.max(WorkerCheckin.checkin_time).label("max_time"),
            )
            .group_by(WorkerCheckin.employee_id)
            .subquery()
        )

        result = []
        for dept in departments:
            pending = (
                self.db.query(sql_func.count(DepartmentWorkQueue.work_id))
                .filter(
                    DepartmentWorkQueue.department_id == dept.department_id,
                    DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED,
                )
                .scalar()
            ) or 0

            assigned = (
                self.db.query(sql_func.count(DepartmentWorkQueue.work_id))
                .filter(
                    DepartmentWorkQueue.department_id == dept.department_id,
                    DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.ASSIGNED,
                )
                .scalar()
            ) or 0

            available_workers = (
                self.db.query(sql_func.count(Employee.employee_id))
                .join(
                    latest_checkin_sub,
                    Employee.employee_id == latest_checkin_sub.c.employee_id,
                )
                .join(
                    WorkerCheckin,
                    (WorkerCheckin.employee_id == latest_checkin_sub.c.employee_id)
                    & (WorkerCheckin.checkin_time == latest_checkin_sub.c.max_time),
                )
                .filter(
                    Employee.department_id == dept.department_id,
                    WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
                )
                .scalar()
            ) or 0

            total_staff = (
                self.db.query(sql_func.count(Employee.employee_id))
                .filter(Employee.department_id == dept.department_id)
                .scalar()
            ) or 0

            result.append({
                "department_id": dept.department_id,
                "department_name": dept.department_name,
                "description": dept.description,
                "pending_tasks": pending,
                "assigned_tasks": assigned,
                "available_workers": available_workers,
                "total_staff": total_staff,
            })

        return result

    def _get_recent_events(self, limit: int = 10) -> list[dict]:
        """
        Fetch the most recent event log entries.

        Returns the latest `limit` rows ordered by timestamp DESC.
        """
        rows = (
            self.db.query(EventLog)
            .order_by(EventLog.timestamp.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "event_id": row.event_id,
                "event_log": row.event_log,
                "source_module": row.source_module,
                "employee_id": row.employee_id,
                "work_id": row.work_id,
                "assignment_id": row.assignment_id,
                "timestamp": row.timestamp,
            }
            for row in rows
        ]

    # Public compositor

    def get_dashboard_summary(self) -> dict:
        """
        Compose the full dashboard response from independent section builders.

        This is the only method that calls other section builders.
        """
        return {
            "status": "SUCCESS",
            "summary": self._get_summary(),
            "operations": self._get_operations(),
            "departments": self._get_department_workloads(),
            "recent_events": self._get_recent_events(),
        }


# Module-level convenience function (used by the router)

def get_dashboard_summary(db: Session) -> dict:
    """Instantiate DashboardService and compose the full response."""
    return DashboardService(db).get_dashboard_summary()
