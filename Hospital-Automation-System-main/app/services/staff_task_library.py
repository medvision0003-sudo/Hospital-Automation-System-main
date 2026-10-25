"""Seed the role-specific recurring task library used by Staff Automation."""

import logging
from datetime import datetime, time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.enums import (
    AssignmentStatusEnum,
    FrequencyTypeEnum,
    PriorityEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    WorkQueueStatusEnum,
)
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.task_schedule import TaskSchedule


logger = logging.getLogger(__name__)

_DEPARTMENTS = {
    "Nursing": ("nursing", "nursing department", "nursing services"),
    "Ward": ("ward", "wards", "general ward"),
    "Pharmacy": ("pharmacy", "pharmacy services"),
    "Laboratory": ("laboratory", "lab", "laboratory services"),
    "Reception": ("reception", "front desk", "patient reception"),
    "Housekeeping": ("housekeeping", "environmental services"),
}

TASK_LIBRARY = (
    {
        "department": "Nursing",
        "task_name": "Vital Signs Monitoring",
        "description": "Record scheduled vital signs using the approved observation protocol. Escalate out-of-range readings to the responsible clinician.",
        "required_role": "NURSE",
        "required_skill": "VITAL_SIGNS",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(7, 15),
        "due_time": time(8, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Patient Medication Administration",
        "description": "Complete scheduled medication administration and documentation in accordance with the active prescription and hospital policy.",
        "required_role": "NURSE",
        "required_skill": "MEDICATION_ADMINISTRATION",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 45,
        "suggested_start_time": time(8, 0),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Patient Care Plan Update",
        "description": "Review assigned care-plan documentation for completeness and record approved updates for the current shift.",
        "required_role": "NURSE",
        "required_skill": "CARE_PLAN_DOCUMENTATION",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 30,
        "suggested_start_time": time(9, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Nursing Documentation",
        "description": "Complete required nursing notes and routine documentation in the authorized patient record before the shift deadline.",
        "required_role": "NURSE",
        "required_skill": "NURSING_DOCUMENTATION",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 30,
        "suggested_start_time": time(10, 0),
        "due_time": time(14, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Infection Control Round",
        "description": "Complete the assigned infection-control checklist and escalate any observed breach through the hospital reporting process.",
        "required_role": "NURSE",
        "required_skill": "INFECTION_CONTROL",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(10, 30),
        "due_time": time(13, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Patient Bedside Check",
        "description": "Complete the scheduled bedside safety and comfort check for assigned patients and document completion.",
        "required_role": "NURSE",
        "required_skill": "BEDSIDE_SAFETY",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(11, 0),
        "due_time": time(13, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "IV/Fluid Monitoring",
        "description": "Document the scheduled IV and fluid checks according to the existing care plan and escalate discrepancies to the responsible clinician.",
        "required_role": "NURSE",
        "required_skill": "IV_MONITORING",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(11, 30),
        "due_time": time(14, 0),
        "requires_proof": True,
    },
    {
        "department": "Nursing",
        "task_name": "Shift Handover Documentation",
        "description": "Complete the structured shift handover record for assigned patients and confirm required documentation is available to the incoming team.",
        "required_role": "NURSE",
        "required_skill": "SHIFT_HANDOVER",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(14, 0),
        "due_time": time(15, 0),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Ward Inspection",
        "description": "Inspect assigned ward areas using the routine operations checklist and report issues requiring maintenance or clinical follow-up.",
        "required_role": "WARD STAFF",
        "required_skill": "WARD_INSPECTION",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 25,
        "suggested_start_time": time(7, 0),
        "due_time": time(8, 0),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Bed Availability Check",
        "description": "Verify recorded bed availability with the ward status board and notify the authorized bed-coordination team of discrepancies.",
        "required_role": "WARD STAFF",
        "required_skill": "BED_COORDINATION",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(7, 30),
        "due_time": time(8, 30),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Equipment Readiness Check",
        "description": "Check assigned ward equipment for availability and readiness using the approved checklist; report faults for service.",
        "required_role": "WARD STAFF",
        "required_skill": "EQUIPMENT_CHECK",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(8, 0),
        "due_time": time(9, 0),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Patient Area Safety Check",
        "description": "Check assigned patient areas for routine environmental safety concerns and record/escalate hazards through the approved process.",
        "required_role": "WARD STAFF",
        "required_skill": "PATIENT_AREA_SAFETY",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(9, 0),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Infection Control Inspection",
        "description": "Verify routine ward infection-control measures against the current checklist and log any exception for follow-up.",
        "required_role": "WARD STAFF",
        "required_skill": "INFECTION_CONTROL",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(10, 0),
        "due_time": time(11, 0),
        "requires_proof": True,
    },
    {
        "department": "Ward",
        "task_name": "Medical Supply Check",
        "description": "Review ward supply levels against minimum stock guidance and submit replenishment requests through the approved inventory process.",
        "required_role": "WARD STAFF",
        "required_skill": "MEDICAL_SUPPLY",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 20,
        "suggested_start_time": time(11, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Pharmacy",
        "task_name": "Medication Stock Verification",
        "description": "Verify assigned medication stock against inventory records and document discrepancies for pharmacist review.",
        "required_role": "PHARMACIST",
        "required_skill": "INVENTORY_CONTROL",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(7, 30),
        "due_time": time(9, 0),
        "requires_proof": True,
    },
    {
        "department": "Pharmacy",
        "task_name": "Expiry Date Check",
        "description": "Inspect assigned stock for expiry dates and quarantine/report items requiring action under pharmacy policy.",
        "required_role": "PHARMACIST",
        "required_skill": "MEDICATION_SAFETY",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(8, 30),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Pharmacy",
        "task_name": "Controlled Medication Count",
        "description": "Complete the required controlled-medication count with the authorized witness and record both staff identities per policy.",
        "required_role": "PHARMACIST",
        "required_skill": "CONTROLLED_MEDICATIONS",
        "priority_category": PriorityEnum.CRITICAL,
        "estimated_time": 20,
        "suggested_start_time": time(9, 0),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Pharmacy",
        "task_name": "Prescription Queue Review",
        "description": "Review the assigned prescription queue for operational completeness and route clinical or dispensing questions to the authorized pharmacist.",
        "required_role": "PHARMACIST",
        "required_skill": "PRESCRIPTION_REVIEW",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(10, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Pharmacy",
        "task_name": "Medication Storage Inspection",
        "description": "Verify assigned storage areas meet pharmacy storage requirements and report temperature or access exceptions.",
        "required_role": "PHARMACIST",
        "required_skill": "MEDICATION_STORAGE",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(11, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Laboratory",
        "task_name": "Sample Collection Verification",
        "description": "Verify assigned collection records and specimen acceptance details against laboratory procedure; route exceptions to the designated reviewer.",
        "required_role": "LAB TECHNICIAN",
        "required_skill": "SPECIMEN_HANDLING",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(7, 30),
        "due_time": time(9, 0),
        "requires_proof": True,
    },
    {
        "department": "Laboratory",
        "task_name": "Sample Label Validation",
        "description": "Validate specimen labels against the authorized identifiers and laboratory acceptance checklist before processing.",
        "required_role": "LAB TECHNICIAN",
        "required_skill": "SPECIMEN_LABELING",
        "priority_category": PriorityEnum.CRITICAL,
        "estimated_time": 20,
        "suggested_start_time": time(8, 0),
        "due_time": time(9, 0),
        "requires_proof": True,
    },
    {
        "department": "Laboratory",
        "task_name": "Equipment Readiness Check",
        "description": "Complete routine analyzer and bench-equipment readiness checks and record any out-of-service equipment for follow-up.",
        "required_role": "LAB TECHNICIAN",
        "required_skill": "LAB_EQUIPMENT",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(7, 0),
        "due_time": time(8, 30),
        "requires_proof": True,
    },
    {
        "department": "Laboratory",
        "task_name": "Pending Sample Review",
        "description": "Review the pending specimen queue for age and processing status and escalate exceptions according to laboratory procedure.",
        "required_role": "LAB TECHNICIAN",
        "required_skill": "SPECIMEN_PROCESSING",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(9, 0),
        "due_time": time(11, 0),
        "requires_proof": True,
    },
    {
        "department": "Laboratory",
        "task_name": "Lab Safety Checklist",
        "description": "Complete the assigned laboratory safety checklist and report hazards or equipment concerns through the laboratory safety process.",
        "required_role": "LAB TECHNICIAN",
        "required_skill": "LAB_SAFETY",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(10, 0),
        "due_time": time(11, 0),
        "requires_proof": True,
    },
    {
        "department": "Reception",
        "task_name": "Patient Registration Queue",
        "description": "Review the assigned registration queue for complete demographic and visit records and route exceptions to authorized registration staff.",
        "required_role": "RECEPTIONIST",
        "required_skill": "PATIENT_REGISTRATION",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(7, 30),
        "due_time": time(9, 0),
        "requires_proof": True,
    },
    {
        "department": "Reception",
        "task_name": "Appointment Verification",
        "description": "Verify the assigned appointment list and flag scheduling discrepancies for the responsible clinic team.",
        "required_role": "RECEPTIONIST",
        "required_skill": "APPOINTMENT_SCHEDULING",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 25,
        "suggested_start_time": time(8, 0),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Reception",
        "task_name": "Insurance/Document Verification",
        "description": "Check assigned registration documents for presence and legibility; route coverage or eligibility questions to the authorized billing team.",
        "required_role": "RECEPTIONIST",
        "required_skill": "DOCUMENT_VERIFICATION",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 30,
        "suggested_start_time": time(9, 0),
        "due_time": time(11, 0),
        "requires_proof": True,
    },
    {
        "department": "Reception",
        "task_name": "Patient Help Desk Follow-up",
        "description": "Review open non-clinical help-desk requests, document follow-up, and route clinical questions to qualified care staff.",
        "required_role": "RECEPTIONIST",
        "required_skill": "PATIENT_SUPPORT",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 20,
        "suggested_start_time": time(10, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Reception",
        "task_name": "Patient Queue Coordination",
        "description": "Review the active non-clinical reception queue, coordinate registration order, and route urgent clinical concerns to the appropriate care team.",
        "required_role": "RECEPTIONIST",
        "required_skill": "PATIENT_FLOW_COORDINATION",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 25,
        "suggested_start_time": time(10, 30),
        "due_time": time(13, 0),
        "requires_proof": True,
    },
    {
        "department": "Housekeeping",
        "task_name": "Ward Cleaning Verification",
        "description": "Verify assigned ward cleaning completion against the environmental-services checklist and record any missed area for rework.",
        "required_role": "HOUSEKEEPER",
        "required_skill": "HOSPITAL_CLEANING",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(7, 0),
        "due_time": time(8, 30),
        "requires_proof": True,
    },
    {
        "department": "Housekeeping",
        "task_name": "Sanitization Checklist",
        "description": "Complete the assigned area sanitization checklist using approved products and procedures; report supply or access issues.",
        "required_role": "HOUSEKEEPER",
        "required_skill": "HOSPITAL_SANITIZATION",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 30,
        "suggested_start_time": time(8, 0),
        "due_time": time(10, 0),
        "requires_proof": True,
    },
    {
        "department": "Housekeeping",
        "task_name": "Waste Segregation Check",
        "description": "Inspect assigned waste points for correct segregation and report any handling issue through the hospital waste-management process.",
        "required_role": "HOUSEKEEPER",
        "required_skill": "WASTE_SEGREGATION",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 20,
        "suggested_start_time": time(10, 0),
        "due_time": time(11, 0),
        "requires_proof": True,
    },
    {
        "department": "Housekeeping",
        "task_name": "High-touch Surface Cleaning",
        "description": "Clean assigned high-touch surfaces using the approved schedule and product instructions, then record completion for the area.",
        "required_role": "HOUSEKEEPER",
        "required_skill": "HIGH_TOUCH_CLEANING",
        "priority_category": PriorityEnum.HIGH,
        "estimated_time": 25,
        "suggested_start_time": time(11, 0),
        "due_time": time(12, 0),
        "requires_proof": True,
    },
    {
        "department": "Housekeeping",
        "task_name": "Linen and Supply Restock Check",
        "description": "Check assigned clean-linen and housekeeping supply points, record low stock, and route replenishment needs through the approved supply process.",
        "required_role": "HOUSEKEEPER",
        "required_skill": "LINEN_SUPPLY_MANAGEMENT",
        "priority_category": PriorityEnum.MEDIUM,
        "estimated_time": 20,
        "suggested_start_time": time(12, 0),
        "due_time": time(14, 0),
        "requires_proof": True,
    },
)

_OBSOLETE_DEMO_TASK_NAMES = {
    "DAILY WARD SANITIZATION",
    "CODE BLUE RESPONSE PREP",
}


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _department_ids(db: Session) -> dict[str, int]:
    departments = db.query(Department).all()
    aliases = {
        _normalize_name(alias): canonical
        for canonical, names in _DEPARTMENTS.items()
        for alias in (canonical, *names)
    }
    resolved = {}
    for department in departments:
        canonical = aliases.get(_normalize_name(department.department_name))
        if canonical and canonical not in resolved:
            resolved[canonical] = department.department_id

    for canonical in _DEPARTMENTS:
        if canonical not in resolved:
            department = Department(
                department_name=canonical,
                description=f"Operational department for {canonical.lower()} Staff Automation tasks.",
            )
            db.add(department)
            db.flush()
            resolved[canonical] = department.department_id
    return resolved


def _deactivate_obsolete_demo_tasks(db: Session) -> int:
    obsolete_tasks = (
        db.query(TaskMaster)
        .filter(func.upper(TaskMaster.task_name).in_(_OBSOLETE_DEMO_TASK_NAMES))
        .all()
    )
    cancelled_work_count = 0
    active_work_statuses = (
        WorkQueueStatusEnum.PENDING_ASSIGNED,
        WorkQueueStatusEnum.ASSIGNED,
    )
    active_assignment_statuses = (
        AssignmentStatusEnum.PENDING,
        AssignmentStatusEnum.ASSIGNED,
        AssignmentStatusEnum.IN_PROGRESS,
    )

    for task in obsolete_tasks:
        task.task_state = TaskStatusEnum.INACTIVE
        for schedule in task.schedules:
            schedule.is_active = False

        open_work = (
            db.query(DepartmentWorkQueue)
            .filter(
                DepartmentWorkQueue.task_id == task.task_id,
                DepartmentWorkQueue.queue_status.in_(active_work_statuses),
            )
            .all()
        )
        for work_item in open_work:
            db.query(TaskAssignment).filter(
                TaskAssignment.work_id == work_item.work_id,
                TaskAssignment.assignment_status.in_(active_assignment_statuses),
            ).update(
                {"assignment_status": AssignmentStatusEnum.CANCELLED},
                synchronize_session=False,
            )
            work_item.queue_status = WorkQueueStatusEnum.CANCELLED
            cancelled_work_count += 1

    return cancelled_work_count


def seed_staff_task_library(db: Session) -> dict[str, int]:
    """Idempotently upsert hospital task templates and their daily schedules."""
    department_ids = _department_ids(db)
    now = datetime.now()
    templates_created = 0
    schedules_created = 0

    for definition in TASK_LIBRARY:
        values = {key: value for key, value in definition.items() if key != "department"}
        values["department_id"] = department_ids[definition["department"]]
        values["task_type"] = TaskTypeEnum.RECURRING

        task = (
            db.query(TaskMaster)
            .filter(
                TaskMaster.department_id == values["department_id"],
                func.upper(TaskMaster.task_name) == values["task_name"].upper(),
            )
            .first()
        )
        if task is None:
            task = TaskMaster(**values, task_state=TaskStatusEnum.ACTIVE)
            db.add(task)
            db.flush()
            templates_created += 1
        else:
            for key, value in values.items():
                setattr(task, key, value)
            db.flush()

        schedule_name = f"Daily - {task.task_name}"
        schedule = (
            db.query(TaskSchedule)
            .filter(
                TaskSchedule.task_id == task.task_id,
                TaskSchedule.schedule_name == schedule_name,
            )
            .first()
        )
        if schedule is None:
            schedule = TaskSchedule(
                task_id=task.task_id,
                schedule_name=schedule_name,
                frequency_type=FrequencyTypeEnum.DAYS,
                frequency_value=1,
                next_run=datetime.combine(now.date(), task.suggested_start_time),
                is_active=True,
            )
            db.add(schedule)
            schedules_created += 1

    cancelled_work = _deactivate_obsolete_demo_tasks(db)
    db.commit()
    result = {
        "templates_created": templates_created,
        "templates_available": len(TASK_LIBRARY),
        "schedules_created": schedules_created,
        "obsolete_work_cancelled": cancelled_work,
    }
    logger.info("Staff task library seeded: %s", result)
    return result
