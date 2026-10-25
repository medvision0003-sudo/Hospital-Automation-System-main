"""
Communication Agent (Agent ID 8)

High-level business workflow for WhatsApp task notifications,
inbound command parsing, and image proof handling.

This agent owns:
  AgentActionLog entries (agent_id=8)
  EventLog entries for TASK_STARTED
  Command routing (help, tasks, start, image proof)

Low-level channel delivery is delegated to whatsapp_service.py.
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.event_log import EventLog
from app.models.agent_action_log import AgentActionLog
from app.models.enums import (
    AssignmentStatusEnum,
    AgentActionStatusEnum,
    WorkQueueStatusEnum,
)
from app.services.whatsapp_service import (
    deliver_whatsapp_message,
    log_inbound,
    find_employee_by_phone,
    get_active_tasks,
    download_meta_media,
    is_whatsapp_mock_mode,
)

COMMUNICATION_AGENT_ID = 8

CHAT_RULES_TEXT = (
    "Hospital Task Bot - Commands:\n"
    "  tasks - List your active tasks\n"
    "  start <number or name> - Start a task\n"
    "  help - Show this guide\n"
    "  Send an image to submit proof for your current task"
)


def send_whatsapp_task_notification(
    db: Session,
    employee_id: int,
    work_id: int,
    notification_type: str = "ASSIGNMENT",
    reason: str = None,
    workflow_id: str = None,
) -> dict:
    """Send a WhatsApp task notification to the assigned worker.

    Called by the orchestrator adapter when processing
    SEND_WHATSAPP_NOTIFICATION outbox events.

    Supported notification_type values:
        ASSIGNMENT     - new task assigned (default)
        PREEMPTION     - task removed from worker
        PROOF_REJECTED - submitted proof was rejected
        PROOF_APPROVED - submitted proof was approved
    """
    # Validate notification_type, fallback to ASSIGNMENT for unknown values
    VALID_TYPES = {"ASSIGNMENT", "PREEMPTION", "PROOF_REJECTED", "PROOF_APPROVED"}
    if notification_type not in VALID_TYPES:
        print(f"[COMMUNICATION_AGENT] Unknown notification_type '{notification_type}', falling back to ASSIGNMENT")
        notification_type = "ASSIGNMENT"

    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        print(f"[COMMUNICATION_AGENT] Employee {employee_id} not found, skipping notification")
        return {"message_id": None, "status": "FAILED"}

    work_item = (
        db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item:
        print(f"[COMMUNICATION_AGENT] Work item {work_id} not found, skipping notification")
        return {"message_id": None, "status": "FAILED"}

    task = db.query(TaskMaster).filter(TaskMaster.task_id == work_item.task_id).first()
    task_name = task.task_name.replace("_", " ") if task and task.task_name else f"Task #{work_item.task_id}"

    # Build message body based on notification type
    if notification_type == "PREEMPTION":
        body = (
            f"Task Removed:\n"
            f"  Task: {task_name}\n"
            f"  Work ID: {work_id}\n\n"
            f"This task has been removed from your assignments.\n"
            f"Reply 'tasks' to see your current tasks."
        )
        action_type = "WHATSAPP_PREEMPTION_NOTIFICATION"

    elif notification_type == "PROOF_REJECTED":
        body = (
            f"Proof Rejected!\n"
            f"Your proof for task '{task_name}' (Work ID: {work_id}) was rejected by the supervisor.\n"
            f"Reason: {reason or 'No reason provided'}\n\n"
            f"Please reply with a valid image attachment to submit a new proof."
        )
        action_type = "WHATSAPP_PROOF_REJECTED_NOTIFICATION"

    elif notification_type == "PROOF_APPROVED":
        body = (
            f"Proof Approved!\n"
            f"Your proof for task '{task_name}' (Work ID: {work_id}) was approved by the supervisor."
        )
        action_type = "WHATSAPP_PROOF_APPROVED_NOTIFICATION"

    else:
        # Default: ASSIGNMENT
        due_str = work_item.due_date.strftime("%Y-%m-%d %H:%M") if work_item.due_date else "No due date"
        priority = work_item.priority.value if work_item.priority else "MEDIUM"
        body = (
            f"New Task Assigned:\n"
            f"  Task: {task_name}\n"
            f"  Priority: {priority}\n"
            f"  Due: {due_str}\n"
            f"  Work ID: {work_id}\n\n"
            f"Reply 'start {work_id}' to begin or 'tasks' to see all your tasks."
        )
        action_type = "WHATSAPP_TASK_NOTIFICATION"

    msg = deliver_whatsapp_message(db, employee_id, employee.phone, body, work_id=work_id)
    msg_status = msg.status if msg else "FAILED"

    event = EventLog(
        event_log="WHATSAPP_NOTIFICATION_ATTEMPTED",
        source_module="COMMUNICATION_AGENT",
        employee_id=employee_id,
        work_id=work_id,
    )
    db.add(event)
    db.flush()

    action = AgentActionLog(
        event_id=event.event_id,
        agent_id=COMMUNICATION_AGENT_ID,
        action_type=action_type,
        action_timestamp=datetime.now(),
        execution_status=AgentActionStatusEnum.SUCCESS if msg_status != "FAILED" else AgentActionStatusEnum.FAILED,
        decision_summary=f"Processed {notification_type} notification for work_id={work_id} to employee {employee_id} with delivery status {msg_status}",
        workflow_id=workflow_id,
    )
    db.add(action)

    db.commit()

    return {
        "message_id": msg.message_id if msg else None,
        "status": msg_status,
        "event_id": event.event_id,
        "agent_action_id": action.agent_action_id,
    }



def send_chat_rules(db: Session, employee_id: int, phone: str = None):
    """Send the command guidance welcome message."""
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    phone = phone or (employee.phone if employee else None)

    msg = deliver_whatsapp_message(db, employee_id, phone, CHAT_RULES_TEXT)

    # Log agent action
    action = AgentActionLog(
        event_id=None,
        agent_id=COMMUNICATION_AGENT_ID,
        action_type="WHATSAPP_CHAT_RULES",
        action_timestamp=datetime.now(),
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=f"Sent chat rules to employee {employee_id}",
    )
    db.add(action)

    return msg


def process_whatsapp_inbound_from_meta_payload(db: Session, payload: dict):
    """Parse a Meta webhook payload and route each message through the agent.

    Encapsulates all Meta-specific payload structure so the route
    never touches whatsapp_service.py directly.
    """
    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                sender = msg.get("from", "")
                msg_type = msg.get("type", "")
                text = ""
                file_content = None
                file_ext = None

                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type == "image":
                    text = msg.get("image", {}).get("caption", "")
                    media_id = msg.get("image", {}).get("id")
                    if media_id and not is_whatsapp_mock_mode():
                        file_content, file_ext = download_meta_media(media_id)

                process_whatsapp_inbound(
                    db=db,
                    sender_phone=sender,
                    message_text=text,
                    file_content=file_content,
                    file_extension=file_ext,
                    raw_payload=msg,
                )


def process_whatsapp_inbound(
    db: Session,
    sender_phone: str,
    message_text: str = None,
    file_content: bytes = None,
    file_extension: str = None,
    raw_payload: dict = None,
) -> str:
    """Process an inbound WhatsApp message and return a reply string.

    Handles command parsing (help, tasks, start) and image proof submission.
    All database changes are committed atomically at the end.
    """
    employee = find_employee_by_phone(db, sender_phone)
    employee_id = employee.employee_id if employee else None

    # Log the inbound message
    log_inbound(db, employee_id, sender_phone, message_text, raw_payload=raw_payload)

    if not employee:
        reply = "Phone number not recognized. Please contact your supervisor."
        deliver_whatsapp_message(db, None, sender_phone, reply)
        db.commit()
        return reply

    text = (message_text or "").strip().lower()

    # Image proof submission
    if file_content and file_extension:
        reply = _handle_image_proof(db, employee, file_content, file_extension)
        deliver_whatsapp_message(db, employee_id, sender_phone, reply)
        db.commit()
        return reply

    # Command parsing
    if text in ("help", "hello", "hi", "hey"):
        send_chat_rules(db, employee_id, sender_phone)
        db.commit()
        return CHAT_RULES_TEXT

    if text in ("tasks", "list"):
        reply = _handle_tasks_command(db, employee)
        deliver_whatsapp_message(db, employee_id, sender_phone, reply)
        db.commit()
        return reply

    if text.startswith("start"):
        reply = _handle_start_command(db, employee, text)
        deliver_whatsapp_message(db, employee_id, sender_phone, reply)
        db.commit()
        return reply

    # Unrecognized command: send rules
    send_chat_rules(db, employee_id, sender_phone)
    db.commit()
    return CHAT_RULES_TEXT


def _handle_tasks_command(db: Session, employee) -> str:
    """Return a numbered list of active tasks."""
    tasks = get_active_tasks(db, employee.employee_id)
    if not tasks:
        return "You have no active tasks right now."

    lines = ["Your active tasks:"]
    for t in tasks:
        lines.append(
            f"  {t['index']}. [{t['status']}] {t['task_name']} "
            f"(Priority: {t['priority']}, Due: {t['due']}, ID: {t['work_id']})"
        )
    return "\n".join(lines)


def _handle_start_command(db: Session, employee, text: str) -> str:
    """Parse start command and transition task to IN_PROGRESS."""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: start <task number, name, or work ID>"

    identifier = parts[1].strip()
    tasks = get_active_tasks(db, employee.employee_id)

    if not tasks:
        return "You have no active tasks to start."

    target = None
    if identifier.isdigit():
        idx = int(identifier)
        # Match by work_id only (since notifications use work_id)
        for t in tasks:
            if t["work_id"] == idx:
                target = t
                break
        if not target:
            return f"Could not find any active task with Work ID '{identifier}'. Reply 'tasks' to see all your active tasks."
    else:
        # Try matching by task name (partial, case-insensitive)
        for t in tasks:
            if identifier.lower() in t["task_name"].lower():
                target = t
                break
        if not target:
            return f"Could not find task matching '{identifier}'. Reply 'tasks' to see your list."

    if target["status"] == AssignmentStatusEnum.IN_PROGRESS.value:
        return f"Task '{target['task_name']}' is already in progress."

    # Transition assignment to IN_PROGRESS
    assignment = (
        db.query(TaskAssignment)
        .filter(TaskAssignment.assignment_id == target["assignment_id"])
        .first()
    )
    if assignment:
        assignment.assignment_status = AssignmentStatusEnum.IN_PROGRESS

    # Log TASK_STARTED event
    event = EventLog(
        event_log="TASK_STARTED",
        source_module="COMMUNICATION_AGENT",
        employee_id=employee.employee_id,
        work_id=target["work_id"],
        assignment_id=target["assignment_id"],
    )
    db.add(event)
    db.flush()

    # Log agent action under Communication Agent
    action = AgentActionLog(
        event_id=event.event_id,
        agent_id=COMMUNICATION_AGENT_ID,
        action_type="WHATSAPP_TASK_STARTED",
        action_timestamp=datetime.now(),
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Task '{target['task_name']}' (work_id={target['work_id']}) "
            f"started by employee {employee.employee_id} via WhatsApp"
        ),
    )
    db.add(action)

    return f"Started task: {target['task_name']} (Work ID: {target['work_id']})"


def _handle_image_proof(db: Session, employee, file_content: bytes, file_extension: str) -> str:
    """Auto-detect the target task and save proof using the shared service."""
    tasks = get_active_tasks(db, employee.employee_id)

    if not tasks:
        return "You have no active tasks to submit proof for."

    # Find the single IN_PROGRESS task, or auto-start a single ASSIGNED task
    in_progress = [t for t in tasks if t["status"] == AssignmentStatusEnum.IN_PROGRESS.value]
    assigned_only = [t for t in tasks if t["status"] == AssignmentStatusEnum.ASSIGNED.value]

    target = None
    if len(in_progress) == 1:
        target = in_progress[0]
    elif len(in_progress) == 0 and len(assigned_only) == 1:
        # Auto-start the single assigned task
        target = assigned_only[0]
        assignment = (
            db.query(TaskAssignment)
            .filter(TaskAssignment.assignment_id == target["assignment_id"])
            .first()
        )
        if assignment:
            assignment.assignment_status = AssignmentStatusEnum.IN_PROGRESS
    else:
        return (
            "Multiple tasks detected. Please start a specific task first "
            "using 'start <number>' before sending proof."
        )

    if not target:
        return "Could not determine which task to submit proof for."

    # Save proof using shared service (commit=False, we commit at the end)
    from app.services.task_proof_service import save_task_proof
    filename = f"whatsapp_proof{file_extension}"

    try:
        result = save_task_proof(
            db=db,
            work_id=target["work_id"],
            file_content=file_content,
            filename=filename,
            employee_id=employee.employee_id,
            commit=False,
        )
    except Exception as exc:
        return f"Could not save proof: {str(exc)}"

    return (
        f"Proof received for task: {target['task_name']} "
        f"(Work ID: {target['work_id']}). Verification in progress."
    )


def send_proof_rejection_notification(db: Session, employee_id: int, work_id: int, task_name: str, reason: str):
    """Send a WhatsApp message notifying the worker that their proof was rejected."""
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee or not employee.phone:
        print(f"[COMMUNICATION_AGENT] Cannot send proof rejection: employee {employee_id} or phone not found")
        return

    # Log agent action (Agent ID 8)
    action = AgentActionLog(
        agent_id=COMMUNICATION_AGENT_ID,
        action_type="WHATSAPP_PROOF_REJECTED_NOTIFICATION",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Sent proof rejection notification to worker {employee_id} "
            f"(phone: {employee.phone}) for work_id {work_id}. "
            f"Reason: {reason}"
        ),
    )
    db.add(action)
    db.flush()

    message = (
        f" Proof Rejected!\n"
        f"Your proof for task '{task_name}' (Work ID: {work_id}) was rejected by the supervisor.\n"
        f"Reason: {reason}\n\n"
        f"Please reply with a valid image attachment to submit a new proof."
    )

    deliver_whatsapp_message(db, employee_id, str(employee.phone), message, work_id=work_id)


def send_proof_approval_notification(db: Session, employee_id: int, work_id: int, task_name: str):
    """Send a WhatsApp message notifying the worker that their proof was approved."""
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee or not employee.phone:
        print(f"[COMMUNICATION_AGENT] Cannot send proof approval: employee {employee_id} or phone not found")
        return

    # Log agent action (Agent ID 8)
    action = AgentActionLog(
        agent_id=COMMUNICATION_AGENT_ID,
        action_type="WHATSAPP_PROOF_APPROVED_NOTIFICATION",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Sent proof approval notification to worker {employee_id} "
            f"(phone: {employee.phone}) for work_id {work_id}."
        ),
    )
    db.add(action)
    db.flush()

    message = (
        f" Proof Approved!\n"
        f"Your proof for task '{task_name}' (Work ID: {work_id}) was approved by the supervisor. "
    )

    deliver_whatsapp_message(db, employee_id, str(employee.phone), message, work_id=work_id)
