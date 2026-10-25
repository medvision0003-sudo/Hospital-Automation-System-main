import os
from fastapi import Depends, FastAPI
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from sqlalchemy import text

from app.database.connection import engine
from app.database.base import Base
from app.models.department import Department
from app.models.employee import Employee
from app.models.worker_memory import WorkerMemory
from app.models.worker_checkin import WorkerCheckin
from app.models.attendance_device import AttendanceDevice
from app.models.task_master import TaskMaster
from app.models.task_assignment import TaskAssignment
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.event_log import EventLog
from app.models.agent_action_log import AgentActionLog
from app.models.agent_table import AgentTable
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.models.task_schedule import TaskSchedule
from app.models.orchestrator_trace import OrchestratorTrace
from app.models.outbox_event import OutboxEvent
from app.models.task_proof import TaskProof
from app.models.approval_request import ApprovalRequest
from app.models.user import User
from app.models.system_config import SystemConfig
from app.models.whatsapp_message import WhatsAppMessage
from app.models.nursing_shift_log import NursingShiftLog
from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.automation_rule_audit import AutomationRuleAudit

from app.routes.query.employees import router as q_employee_router
from app.routes.query.nursing_shift_logs import router as q_nursing_shift_logs_router
from app.routes.query.departments import router as q_department_router
from app.routes.query.tasks import router as q_task_router
from app.routes.query.work_queue import router as q_work_queue_router
from app.routes.query.assignments import router as q_assignment_router
from app.routes.query.worker_memory import router as q_memory_router
from app.routes.query.event_logs import router as q_event_logs_router
from app.routes.query.agent_actions import router as q_agent_actions_router
from app.routes.query.agents import router as q_agents_router
from app.routes.query.checkins import router as q_checkins_router
from app.routes.query.supervisor_requests import router as q_supervisor_router
from app.routes.query.shifts import router as q_shifts_router
from app.routes.query.rosters import router as q_rosters_router
from app.routes.query.task_schedule import router as q_schedule_router
from app.routes.query.orchestrator_traces import router as q_trace_router
from app.routes.query.outbox_events import router as q_outbox_event_router
from app.routes.query.capabilities import router as q_capability_router
from app.routes.query.escalations import router as q_escalations_router

from app.routes.admin.employees import router as a_employee_router
from app.routes.admin.nursing_shift_logs import router as a_nursing_shift_logs_router
from app.routes.admin.departments import router as a_department_router
from app.routes.admin.tasks import router as a_task_router
from app.routes.admin.checkins import router as a_checkins_router
from app.routes.admin.agents import router as a_agents_router
from app.routes.admin.worker_memory import router as a_memory_router
from app.routes.admin.shifts import router as a_shifts_router
from app.routes.admin.rosters import router as a_rosters_router
from app.routes.admin.task_schedule import router as a_schedule_router
from app.routes.admin.system_config import router as a_system_config_router

from app.routes.workflow.hospital_events import router as event_gateway_router
from app.routes.workflow.supervisor_requests import router as wf_supervisor_router
from app.routes.workflow.work_queue import router as wf_work_queue_router
from app.routes.workflow.approvals import router as wf_approvals_router
from app.routes.workflow.uploads import router as uploads_router
from app.routes.workflow.whatsapp import router as whatsapp_router
from app.routes.workflow.nursing_shift_reports import router as nursing_shift_reports_router
from app.routes.workflow.staff_automation_rules import router as staff_automation_rules_router
from app.routes.workflow.device_attendance import router as device_attendance_router
from app.routes.workflow.device_attendance import admin_router as admin_attendance_devices_router

from app.routes.scheduler import router as scheduler_router
from app.routes.dashboard.dashboard import router as dashboard_router

from app.routes.auth import router as auth_router

from app.core.dependencies import require_roles
from app.models.enums import UserRoleEnum

# Dependency groups for router-level protection
admin_only = [Depends(require_roles([UserRoleEnum.ADMIN]))]
all_roles = [Depends(require_roles([UserRoleEnum.SUPERVISOR, UserRoleEnum.ADMIN]))]

Base.metadata.create_all(bind=engine)

# Run lightweight column migrations for existing SQLite tables
from app.database.migrations import run_migrations
run_migrations(engine)


def seed_initial_admin(db):
    """Create the bootstrap admin without using the development password in production."""
    from app.core.security import hash_password
    from app.models.user import User

    admin_email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@hospital.com")
    admin = db.query(User).filter(User.email == admin_email).first()
    if admin:
        return False

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    initial_password = os.getenv("INITIAL_ADMIN_PASSWORD")
    if app_env == "production":
        if not initial_password:
            raise RuntimeError(
                "INITIAL_ADMIN_PASSWORD must be configured before bootstrapping "
                "the production administrator."
            )
        if len(initial_password) < 12:
            raise RuntimeError(
                "INITIAL_ADMIN_PASSWORD must be at least 12 characters."
            )
    else:
        initial_password = initial_password or "Admin@23"

    db.add(User(
        email=admin_email,
        admin_id=os.getenv("INITIAL_ADMIN_ID", "ADMIN-001"),
        hashed_password=hash_password(initial_password),
        role=UserRoleEnum.ADMIN,
        is_active=True,
    ))
    db.flush()
    return True


def parse_cors_origins(raw: str) -> list:
    """Parse comma-separated CORS origins from environment variable.

    Returns a list of trimmed, non-empty origin strings.
    """
    if not raw or not raw.strip():
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate security configuration before starting any background workers
    from app.core.security import validate_security_config
    validate_security_config()

    # Seed operational config defaults before daemon threads read them
    from app.services.system_config_service import seed_system_config
    from app.database.connection import SessionLocal
    config_db = SessionLocal()
    try:
        seed_system_config(config_db)
        from app.services.staff_task_library import seed_staff_task_library
        seed_staff_task_library(config_db)
        from app.services.demo_staff_data import demo_staff_data_enabled, seed_demo_staff_data
        if demo_staff_data_enabled():
            seed_demo_staff_data(config_db)
        seed_initial_admin(config_db)
        from app.services.agent_registry_service import seed_agent_registry
        seed_agent_registry(config_db)
        config_db.commit()
    finally:
        config_db.close()

    import sys
    if "pytest" not in sys.modules:
        from app.services.outbox_dispatcher import start_outbox_service
        from app.services.recurring_task_scheduler import start_scheduler
        start_outbox_service()
        start_scheduler()

    try:
        yield
    finally:
        if "pytest" not in sys.modules:
            from app.services.outbox_dispatcher import stop_outbox_service
            from app.services.recurring_task_scheduler import stop_scheduler
            stop_outbox_service()
            stop_scheduler()


app = FastAPI(title="Hospital Automation API", lifespan=lifespan)

# Environment-driven CORS origins
_cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_cors_origins = parse_cors_origins(_cors_raw)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Query routers: accessible by both SUPERVISOR and ADMIN
app.include_router(q_employee_router, dependencies=all_roles)
app.include_router(q_nursing_shift_logs_router, dependencies=all_roles)
app.include_router(q_department_router, dependencies=all_roles)
app.include_router(q_task_router, dependencies=all_roles)
app.include_router(q_work_queue_router, dependencies=all_roles)
app.include_router(q_assignment_router, dependencies=all_roles)
app.include_router(q_memory_router, dependencies=all_roles)
app.include_router(q_event_logs_router, dependencies=all_roles)
app.include_router(q_agent_actions_router, dependencies=all_roles)
app.include_router(q_agents_router, dependencies=all_roles)
app.include_router(q_checkins_router, dependencies=all_roles)
app.include_router(q_supervisor_router, dependencies=all_roles)
app.include_router(q_shifts_router, dependencies=all_roles)
app.include_router(q_rosters_router, dependencies=all_roles)
app.include_router(q_schedule_router, dependencies=all_roles)
app.include_router(q_trace_router, dependencies=all_roles)
app.include_router(q_outbox_event_router, dependencies=all_roles)
app.include_router(q_capability_router, dependencies=all_roles)
app.include_router(q_escalations_router, dependencies=all_roles)

# Admin mutation routers: ADMIN only
app.include_router(a_employee_router, dependencies=admin_only)
app.include_router(a_nursing_shift_logs_router, dependencies=admin_only)
app.include_router(a_department_router, dependencies=admin_only)
app.include_router(a_task_router, dependencies=admin_only)
app.include_router(a_checkins_router, dependencies=admin_only)
app.include_router(a_agents_router, dependencies=admin_only)
app.include_router(admin_attendance_devices_router)
app.include_router(a_memory_router, dependencies=admin_only)
app.include_router(a_shifts_router, dependencies=admin_only)
app.include_router(a_rosters_router, dependencies=admin_only)
app.include_router(a_system_config_router, dependencies=admin_only)

# Schedule admin: both roles can manage schedules
app.include_router(a_schedule_router, dependencies=all_roles)

# Workflow routers: supervisor requests and approvals need auth
app.include_router(wf_supervisor_router, dependencies=all_roles)
app.include_router(nursing_shift_reports_router, dependencies=all_roles)
app.include_router(staff_automation_rules_router, dependencies=all_roles)
app.include_router(wf_approvals_router, dependencies=all_roles)

# Workflow gateways: authenticated access required
# Currently uses SUPERVISOR/ADMIN roles; future support for SERVICE/SYSTEM
# machine tokens can be added when automated inter-service calls are needed.
app.include_router(event_gateway_router, dependencies=all_roles)
app.include_router(wf_work_queue_router, dependencies=all_roles)
app.include_router(device_attendance_router)

# Scheduler: both roles can view; POST /run is further restricted in scheduler.py
app.include_router(scheduler_router, dependencies=all_roles)
app.include_router(dashboard_router, dependencies=all_roles)

# Auth: public
app.include_router(auth_router)

# WhatsApp: mixed auth (public webhooks + protected sandbox)
app.include_router(whatsapp_router)

from fastapi.responses import FileResponse

# Ensure uploads directory exists for proof file storage
uploads_path = Path("uploads")
uploads_path.mkdir(parents=True, exist_ok=True)

# Protected uploads: authenticated file serving (must be registered before SPA mount)
app.include_router(uploads_router, dependencies=all_roles)

frontend_path = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/health")
def health_check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.get("/workflow")
@app.get("/agents")
@app.get("/scheduler")
@app.get("/emergency")
@app.get("/task-master")
@app.get("/employees")
@app.get("/task-proof")
@app.get("/staff-automation")
@app.get("/supervisor")
@app.get("/auth")
@app.get("/login")
@app.get("/escalation-review")
@app.get("/whatsapp-sandbox")
def serve_spa():
    return FileResponse(
        str(frontend_path / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

if frontend_path.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
