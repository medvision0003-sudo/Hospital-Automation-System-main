"""
Models package initialization.
Import all models here to ensure SQLAlchemy mapper registry resolves all relationships.
"""

from app.models.enums import *
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
from app.models.user import User
from app.models.approval_request import ApprovalRequest
from app.models.system_config import SystemConfig
from app.models.whatsapp_message import WhatsAppMessage
from app.models.workflow_experience import WorkflowExperience
from app.models.nursing_shift_log import NursingShiftLog
from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.automation_rule_audit import AutomationRuleAudit
