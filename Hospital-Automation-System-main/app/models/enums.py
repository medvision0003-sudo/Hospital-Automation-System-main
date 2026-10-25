import enum


# Employee Enums


class ShiftEnum(str, enum.Enum):
    """Work shift timings."""
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"
    NIGHT = "NIGHT"


class EmploymentStatusEnum(str, enum.Enum):
    """Employment / availability status of an employee."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ON_LEAVE = "ON_LEAVE"


class GenderEnum(str, enum.Enum):
    """Gender of an employee."""
    MALE = "MALE"
    FEMALE = "FEMALE"


# Check-in Enums

class CheckinStatusEnum(str, enum.Enum):
    """Attendance status for a worker check-in record."""
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    ABSENT = "ABSENT"


# Work Queue Enums

class WorkQueueStatusEnum(str, enum.Enum):
    """Dispatch pipeline status for DepartmentWorkQueue items."""
    PENDING_ASSIGNED = "PENDING_ASSIGNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatusEnum(str, enum.Enum):
    """Status values for TaskAssignment — tracks assignment lifecycle."""
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


class PriorityEnum(str, enum.Enum):
    """Priority levels for DepartmentWorkQueue and TaskMaster."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class TaskStatusEnum(str, enum.Enum):
    """Lifecycle status for a TaskMaster entry."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EventTypeEnum(str, enum.Enum):
    """Types of system events captured in EventLog."""
    WORKER_CHECKED_IN = "WORKER_CHECKED_IN"
    WORKER_CHECKED_OUT = "WORKER_CHECKED_OUT"
    TASK_CREATED = "TASK_CREATED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_CANCELLED = "TASK_CANCELLED"
    ALERT = "ALERT"
    SYSTEM = "SYSTEM"
    RECURRING_TASK_GENERATED = "RECURRING_TASK_GENERATED"


class TaskTypeEnum(str, enum.Enum):
    """Classification of how a task is triggered."""
    RECURRING = "RECURRING"
    EVENT_TEMPLATE = "EVENT_TEMPLATE"


class FrequencyTypeEnum(str, enum.Enum):
    """Interval units for recurring task scheduling."""
    MINUTES = "MINUTES"
    HOURS = "HOURS"
    DAYS = "DAYS"
    WEEKS = "WEEKS"
    MONTHS = "MONTHS"


class AgentActionStatusEnum(str, enum.Enum):
    """Outcome status for an AgentActionLog entry."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


# Emergency Enums

class HospitalCodeEnum(str, enum.Enum):
    """Commonly used hospital code protocol set.

    Each member maps to a standard color-coded emergency protocol.
    The .description property provides a human-readable summary
    suitable for UI display and audit logs.
    """
    CODE_BLUE   = "CODE_BLUE"
    CODE_RED    = "CODE_RED"
    CODE_PINK   = "CODE_PINK"
    CODE_SILVER = "CODE_SILVER"
    CODE_PURPLE = "CODE_PURPLE"
    CODE_BLACK  = "CODE_BLACK"
    CODE_ORANGE = "CODE_ORANGE"
    CODE_YELLOW = "CODE_YELLOW"
    CODE_GREEN  = "CODE_GREEN"
    CODE_BROWN  = "CODE_BROWN"

    @property
    def description(self) -> str:
        return _HOSPITAL_CODE_DESCRIPTIONS[self]


_HOSPITAL_CODE_DESCRIPTIONS = {
    HospitalCodeEnum.CODE_BLUE:   "Cardiac or respiratory arrest requiring immediate resuscitation",
    HospitalCodeEnum.CODE_RED:    "Fire, smoke, or a detected blaze within the facility",
    HospitalCodeEnum.CODE_PINK:   "Infant or child abduction",
    HospitalCodeEnum.CODE_SILVER: "Active shooter, hostage situation, or an armed intruder",
    HospitalCodeEnum.CODE_PURPLE: "Combative, violent, or aggressive person on the premises",
    HospitalCodeEnum.CODE_BLACK:  "Bomb threat or suspicious device",
    HospitalCodeEnum.CODE_ORANGE: "Hazardous material spill or chemical release",
    HospitalCodeEnum.CODE_YELLOW: "Missing or eloped patient",
    HospitalCodeEnum.CODE_GREEN:  "Hospital evacuation or disaster alert",
    HospitalCodeEnum.CODE_BROWN:  "Internal (facility-based) disaster or mass casualty influx",
}


class EmergencyTypeEnum(str, enum.Enum):
    """Clean internal emergency event types.

    These represent what actually happened. The Emergency Response Agent
    maps each event to the appropriate HospitalCodeEnum protocol.
    Legacy values (ACCIDENT, CODE_BLUE, EQUIPMENT_FAILURE, SECURITY_INCIDENT)
    are translated at the API gateway via app.utils.emergency_mapping.
    """
    PATIENT_COLLAPSE = "PATIENT_COLLAPSE"
    FIRE             = "FIRE"
    ACTIVE_SHOOTER   = "ACTIVE_SHOOTER"
    HAZMAT_SPILL     = "HAZMAT_SPILL"
    INFANT_ABDUCTION = "INFANT_ABDUCTION"
    BOMB_THREAT      = "BOMB_THREAT"
    COMBATIVE_PERSON = "COMBATIVE_PERSON"
    MISSING_PATIENT  = "MISSING_PATIENT"
    EVACUATION_ALERT = "EVACUATION_ALERT"
    MASS_CASUALTY    = "MASS_CASUALTY"


# Roster Enums

# Planned roster status for ShiftRoster entries. Represents the status of the scheduler entry.
class RosterStatusEnum(str, enum.Enum):
    """Planned roster status for ShiftRoster entries."""
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    HALF_DAY = "HALF_DAY"
    COMPLETED = "COMPLETED"
    ABSENT = "ABSENT"
    CANCELLED = "CANCELLED"
    OVERTIME = "OVERTIME"


class OvertimeDurationEnum(str, enum.Enum):
    """Preset overtime extension durations for shift handover approvals."""
    ONE_HOUR = "ONE_HOUR"
    TWO_HOURS = "TWO_HOURS"
    FOUR_HOURS = "FOUR_HOURS"


# Orchestrator Enums 

class HospitalEventEnum(str, enum.Enum):
    """
    Centralized registry of hospital events the orchestrator can handle.

    Each value maps to a distinct workflow inside handle_event().
    Adding a new event here is the first step when introducing a new workflow.
    """
    DYNAMIC_TASK_REQUEST = "DYNAMIC_TASK_REQUEST"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_CANCELLED = "TASK_CANCELLED"
    WORKER_CHECKED_IN = "WORKER_CHECKED_IN"
    WORKER_CHECKED_OUT = "WORKER_CHECKED_OUT"
    SUPERVISOR_REQUEST_CREATED = "SUPERVISOR_REQUEST_CREATED"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    SHIFT_STARTED = "SHIFT_STARTED"

    # Step 4 - Task Proof Verification
    TASK_PROOF_SUBMITTED = "TASK_PROOF_SUBMITTED"

    # Autonomous watcher events (Step 3 - Outbox)
    TASK_TIMEOUT_DETECTED = "TASK_TIMEOUT_DETECTED"
    STAFF_SHORTAGE_DETECTED = "STAFF_SHORTAGE_DETECTED"
    WORKER_OVERLOAD_DETECTED = "WORKER_OVERLOAD_DETECTED"
    SHIFT_CHANGE_DETECTED = "SHIFT_CHANGE_DETECTED"
    STAFF_ABSENT_DETECTED = "STAFF_ABSENT_DETECTED"

    # Shift handover and overtime events
    SHIFT_HANDOVER_REVIEW = "SHIFT_HANDOVER_REVIEW"
    EMERGENCY_OVERTIME_ASSIGNED = "EMERGENCY_OVERTIME_ASSIGNED"
    IN_PROGRESS_OVERTIME = "IN_PROGRESS_OVERTIME"

    # Scheduler event (Task Management Agent)
    RECURRING_TASK_GENERATED = "RECURRING_TASK_GENERATED"

    # WhatsApp notification (Communication Agent)
    SEND_WHATSAPP_NOTIFICATION = "SEND_WHATSAPP_NOTIFICATION"


# Supervisor Console Enums

class DueOffsetEnum(str, enum.Enum):
    """Relative time offsets for supervisor task due times.
    The backend service layer resolves these to absolute datetimes."""
    ONE_HOUR = "ONE_HOUR"
    TWO_HOURS = "TWO_HOURS"
    FOUR_HOURS = "FOUR_HOURS"
    END_OF_DAY = "END_OF_DAY"


class TaskProofStatusEnum(str, enum.Enum):
    """Verification status for a submitted task completion proof."""
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# Authentication Enums

class UserRoleEnum(str, enum.Enum):
    """System access roles for authenticated users.
    These represent login access level, not hospital job roles (Employee.role).
    SUPERVISOR: Supervisor-level system access.
    ADMIN: Full administrative system access.
    """
    SUPERVISOR = "SUPERVISOR"
    ADMIN = "ADMIN"
