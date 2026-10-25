import os
import json
import math
import time
from typing import Optional
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.event_log import EventLog
from app.models.agent_action_log import AgentActionLog
from app.models.worker_memory import WorkerMemory
from app.models.employee import Employee
from app.models.task_master import TaskMaster as TM
from app.models.enums import (
    WorkQueueStatusEnum,
    AssignmentStatusEnum,
    AgentActionStatusEnum,
    PriorityEnum,
)
from app.agents.workforce_agent import get_candidate
from app.orchestrator.execution import AgentExecutionError
from app.orchestrator.constants import (
    WORKFORCE_AGENT,
    ASSIGNMENT_AGENT,
    ExecutionStatus,
    AssignmentTrigger,
)
from app.services.system_config_service import get_config_value
from app.services.worker_memory_service import get_or_create_worker_memory

load_dotenv()

# Reasoning Constants

NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
REASONING_MODEL = "nvidia/nemotron-3-super-120b-a12b"
REASONING_TIMEOUT = 15.0  # seconds
REASONING_TEMPERATURE = 0.1


def _supports_row_lock(db: Session) -> bool:
    """Return True if the database dialect is PostgreSQL to support SELECT FOR UPDATE."""
    return db.bind.dialect.name == "postgresql"



# Reasoning Helpers

def _build_reasoning_prompt(
    task_name: str,
    task_description: str,
    priority: str,
    candidates: list[dict],
) -> str:
    """
    Build a structured prompt for the reasoning model.

    Candidates are numbered 1..N to prevent hallucinated employee IDs.
    The model must return a candidate number, not an employee ID.
    match_source metadata is included when available to inform the model
    about how each candidate qualified (skill match vs historical experience).
    """

    candidate_lines = []
    for i, c in enumerate(candidates, start=1):
        match_info = ""
        match_source = c.get("match_source", "")
        if match_source == "STATIC_PROFILE":
            match_info = "\n  Match Type: Static skill match"
        elif match_source == "SIMILAR_SKILL":
            match_info = "\n  Match Type: Similar skill match (same/similar skill fallback)"
        elif match_source == "HISTORICAL_EXPERIENCE":
            match_info = "\n  Match Type: Historical experience (previously completed this task)"

        candidate_lines.append(
            f"Candidate {i}\n"
            f"  Employee ID: {c['employee_id']}\n"
            f"  Role: {c.get('role', 'N/A')}\n"
            f"  Skills: {c.get('skill', 'N/A')}\n"
            f"  Experience: {c.get('experience_years', 0)} years\n"
            f"  Active Tasks: {c.get('pending_task', 0)}\n"
            f"  Total Completed: {c.get('total_task_completed', 0)}"
            f"{match_info}"
        )

    candidates_block = "\n\n".join(candidate_lines)

    return (
        "You are the Assignment Agent for a hospital workforce management system.\n"
        "\n"
        "Your goal is to assign work fairly while maximizing hospital efficiency.\n"
        "\n"
        "Rules:\n"
        "- You MUST select from the provided candidates ONLY.\n"
        "- You may NOT add, remove, or override candidates.\n"
        "- Evaluate each candidate's listed role, skills, match type, and years of experience against the task requirements.\n"
        "- Never assign based on a skill or qualification that is not present in the candidate data.\n"
        "- Prefer lower workload.\n"
        "- Prefer higher completion rate.\n"
        "- If a candidate has a static skill match, prefer them over similar-skill or historical experience.\n"
        "- A similar-skill match is acceptable when the exact skill is unavailable, but prefer a same-skill match first.\n"
        "- Among candidates with equivalent task-skill eligibility and workload, prefer greater relevant experience.\n"
        "- Balance workload across employees.\n"
        "- Never invent information.\n"
        "- Only use the information provided below.\n"
        "- Do not assume experience, certifications, or availability unless explicitly listed.\n"
        "- Keep reasoning_rationale under 80 words. Be direct.\n"
        "- If two candidates are effectively equal, prefer the one with the lower active workload.\n"
        "- If workloads are equal, prefer the higher completion rate.\n"
        "- If still tied, prefer Candidate with the lowest candidate number.\n"
        "- Respond ONLY with valid JSON.\n"
        "\n"
        "Task:\n"
        f"  Name: {task_name}\n"
        f"  Description: {task_description or 'N/A'}\n"
        f"  Priority: {priority}\n"
        "\n"
        "Candidates:\n"
        "\n"
        f"{candidates_block}\n"
        "\n"
        "Return:\n"
        '{\n'
        '  "selected_candidate": <candidate number>,\n'
        '  "confidence": <float between 0.0 and 1.0>,\n'
        '  "reasoning_rationale": "<brief explanation, maximum 80 words>"\n'
        '}'
    )


def _select_candidate_with_reasoning(
    task_name: str,
    task_description: str,
    priority: str,
    candidates: list[dict],
) -> dict:
    """
    Call the NVIDIA NIM reasoning model to select the best candidate.

    Returns dict with:
        selected_index (int):       1-based candidate index
        employee_id (int):          mapped from the candidate list
        confidence (float):         model confidence 0.0-1.0
        reasoning_rationale (str):  explanation (capped at 80 words)
        execution_time_ms (int):    wall-clock time for entire operation

    Raises ValueError on any failure (missing key, API error,
    invalid index, parse error). Caller must catch and fallback.
    """

    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise ValueError("NVIDIA_API_KEY not configured")

    prompt = _build_reasoning_prompt(task_name, task_description, priority, candidates)

    payload = {
        "model": REASONING_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": REASONING_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Start timing the entire reasoning operation
    start_time = time.perf_counter()

    response = requests.post(
        NVIDIA_NIM_URL,
        headers=headers,
        json=payload,
        timeout=REASONING_TIMEOUT,
    )
    response.raise_for_status()

    # Parse response
    response_data = response.json()
    content = response_data["choices"][0]["message"]["content"]
    result = json.loads(content)

    # Validate index
    selected_index = result["selected_candidate"]
    if not isinstance(selected_index, int) or selected_index < 1 or selected_index > len(candidates):
        raise ValueError(
            f"Invalid selected_candidate={selected_index}, "
            f"expected 1-{len(candidates)}"
        )

    # Stop timing after parsing + validation
    execution_time_ms = int((time.perf_counter() - start_time) * 1000)

    # Map index to employee
    selected_candidate = candidates[selected_index - 1]

    return {
        "selected_index": selected_index,
        "employee_id": selected_candidate["employee_id"],
        "confidence": result.get("confidence", 0.0),
        "reasoning_rationale": result.get("reasoning_rationale", ""),
        "execution_time_ms": execution_time_ms,
    }


# Preemption Helpers

# Priority ranking for preemption comparisons (higher = more urgent)
_PRIORITY_RANK = {
    PriorityEnum.LOW: 1,
    PriorityEnum.MEDIUM: 2,
    PriorityEnum.HIGH: 3,
    PriorityEnum.CRITICAL: 4,
}


def get_active_assignments_for_employee(employee_id: int, db: Session) -> list[dict]:
    """Return active assignments for an employee with priority context.

    Queries TaskAssignment rows in ASSIGNED or IN_PROGRESS status,
    joined to DepartmentWorkQueue and TaskMaster to include work queue
    priority, department_id, and required_skill.
    """
    rows = (
        db.query(TaskAssignment, DepartmentWorkQueue, TM)
        .join(DepartmentWorkQueue, TaskAssignment.work_id == DepartmentWorkQueue.work_id)
        .join(TM, DepartmentWorkQueue.task_id == TM.task_id)
        .filter(
            TaskAssignment.employee_id == employee_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .all()
    )
    result = []
    for assignment, work_item, task in rows:
        result.append({
            "assignment_id": assignment.assignment_id,
            "work_id": assignment.work_id,
            "assignment_status": assignment.assignment_status,
            "priority": work_item.priority,
            "department_id": work_item.department_id,
            "required_skill": task.required_skill,
        })
    return result


def can_preempt(incoming_priority: PriorityEnum, active_task_priority: PriorityEnum) -> bool:
    """Check whether an incoming task priority can preempt an active task.

    Rules:
      CRITICAL can preempt LOW and MEDIUM.
      HIGH can preempt LOW.
      MEDIUM and LOW cannot preempt anything.
    Only ASSIGNED status tasks are eligible (caller must filter).
    """
    if incoming_priority == PriorityEnum.CRITICAL:
        return active_task_priority in (PriorityEnum.LOW, PriorityEnum.MEDIUM)
    if incoming_priority == PriorityEnum.HIGH:
        return active_task_priority == PriorityEnum.LOW
    return False


def preempt_assignment(
    assignment_id: int,
    db: Session,
    reason: str,
    source_module: str = "ASSIGNMENT_AGENT",
) -> int:
    """Preempt a single assignment and return the freed work_id.

    Steps:
      1. Set assignment status to PREEMPTED.
      2. Revert the work queue item to PENDING_ASSIGNED.
      3. Recalculate the worker's pending_task in WorkerMemory.
      4. Write TASK_PREEMPTED EventLog and TASK_PREEMPTION AgentActionLog.
    """
    assignment = (
        db.query(TaskAssignment)
        .filter(TaskAssignment.assignment_id == assignment_id)
        .first()
    )
    if not assignment:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Assignment {assignment_id} not found for preemption.",
        )

    # Step 1: mark assignment as PREEMPTED
    assignment.assignment_status = AssignmentStatusEnum.PREEMPTED

    # Step 2: revert work queue item
    work_item = (
        db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == assignment.work_id)
        .first()
    )
    if work_item and work_item.queue_status == WorkQueueStatusEnum.ASSIGNED:
        work_item.queue_status = WorkQueueStatusEnum.PENDING_ASSIGNED
        # Reset created_at to current time to delay the staff shortage watcher from triggering immediately
        work_item.created_at = datetime.now()

    db.flush()

    # Step 3: recalculate pending_task from active assignments
    memory = get_or_create_worker_memory(db, assignment.employee_id)
    new_pending = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == assignment.employee_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .count()
    )
    memory.pending_task = new_pending

    # Step 4: audit trail
    event = EventLog(
        event_log="TASK_PREEMPTED",
        source_module=source_module,
        employee_id=assignment.employee_id,
        work_id=assignment.work_id,
        assignment_id=assignment_id,
    )
    db.add(event)
    db.flush()

    action = AgentActionLog(
        event_id=event.event_id,
        department_id=work_item.department_id if work_item else None,
        agent_id=2,
        action_type="TASK_PREEMPTION",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Preempted assignment_id={assignment_id} "
            f"(work_id={assignment.work_id}, employee_id={assignment.employee_id}). "
            f"Reason: {reason}"
        ),
    )
    db.add(action)

    # Queue WhatsApp notification for the preempted worker (caller owns commit and wake)
    from app.services.outbox_dispatcher import create_outbox_event
    from app.models.enums import HospitalEventEnum
    create_outbox_event(
        db=db,
        event_type=HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
        payload={
            "employee_id": assignment.employee_id,
            "work_id": assignment.work_id,
            "notification_type": "PREEMPTION",
        },
        dedupe_key=f"SEND_WHATSAPP_PREEMPTION:assignment_id={assignment_id}",
    )

    print(
        f"[{source_module}] Preempted assignment_id={assignment_id} "
        f"(work_id={assignment.work_id}) from employee {assignment.employee_id}. "
        f"Reason: {reason}"
    )

    return assignment.work_id


def _assign_task(
    work_id: int,
    db: Session,
    candidates_override: Optional[list[dict]] = None,
    allow_shift_end_buffer: bool = True,
    candidate_resolution: Optional[dict] = None,
    is_emergency: bool = False,
    same_event_work_ids: Optional[list[int]] = None,
    notification_delay_seconds: int = 0,
    workflow_id: Optional[str] = None,
    assignment_reason: Optional[str] = None,
) -> dict:
    """
    Single-task decision engine.

    Selects the best employee for a work item from a candidate list.
    When candidates_override is provided, uses that pre-filtered list
    directly. Otherwise queries the Workforce Agent.

    candidate_resolution is the raw dict returned by get_candidate().
    When present, _assign_task checks escalation_required before
    treating an empty candidates list as a capacity signal.
    This preserves the distinction between:
      - No candidates because fair-share capacity is full (return None)
      - No candidates because the task requires human review (raise error)

    Returns a dict summarising what was created, or raises
    AgentExecutionError on failure. Returns None if candidates_override
    is an empty list and no escalation is required (signals the cycle
    to stop gracefully).
    """

    # Step 1: load work item
    query = db.query(DepartmentWorkQueue).filter(DepartmentWorkQueue.work_id == work_id)
    if _supports_row_lock(db):
        query = query.with_for_update(of=DepartmentWorkQueue)
    work_item = query.first()
    if work_item is None:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Work queue item {work_id} not found.",
        )

    # Guard: only assign work items that are awaiting assignment
    if work_item.queue_status != WorkQueueStatusEnum.PENDING_ASSIGNED:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Work item {work_id} is not awaiting assignment "
            f"(current status: {work_item.queue_status.value}).",
        )

    # Guard: prevent duplicate active assignment for the same work item
    existing = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == work_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .first()
    )
    if existing is not None:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Work item {work_id} is already assigned "
            f"(assignment_id={existing.assignment_id}).",
        )

    # Step 2: Check escalation before resolving candidates
    # This must happen before the empty-candidates capacity check
    # so that HUMAN_REVIEW_REQUIRED is never silently swallowed.
    if candidate_resolution and candidate_resolution.get("escalation_required"):
        escalation_type = candidate_resolution.get("escalation_type", "UNKNOWN")
        reason = candidate_resolution.get("reason", "Escalation required.")
        required_skill = candidate_resolution.get("required_skill")

        # Record the escalation as a failed agent action
        action = AgentActionLog(
            event_id=None,
            department_id=work_item.department_id,
            agent_id=2,
            action_type="ESCALATION",
            execution_status=AgentActionStatusEnum.FAILED,
            decision_summary=(
                f"{escalation_type}: {reason} (work_id={work_id})"
            ),
            workflow_id=workflow_id,
        )
        db.add(action)
        db.flush()

        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            reason,
            metadata={
                "work_id": work_id,
                "escalation_required": True,
                "escalation_type": escalation_type,
                "required_skill": required_skill,
                "agent_action_id": action.agent_action_id,
            },
        )

    # Step 3: resolve candidate list
    if candidates_override is not None:
        candidates = candidates_override
    else:
        try:
            resolution = get_candidate(
                department_id=work_item.department_id,
                db=db,
                allow_shift_end_buffer=allow_shift_end_buffer,
                task_id=work_item.task_id,
            )
        except ValueError as exc:
            raise AgentExecutionError(
                WORKFORCE_AGENT,
                str(exc),
                metadata={"work_id": work_id},
            )

        # Re-check escalation from inline resolution
        if resolution.get("escalation_required"):
            escalation_type = resolution.get("escalation_type", "UNKNOWN")
            reason = resolution.get("reason", "Escalation required.")
            raise AgentExecutionError(
                ASSIGNMENT_AGENT,
                reason,
                metadata={
                    "work_id": work_id,
                    "escalation_required": True,
                    "escalation_type": escalation_type,
                    "required_skill": resolution.get("required_skill"),
                },
            )

        candidates = resolution.get("candidates", [])

    if not candidates:
        # When using candidates_override this signals the cycle engine
        # that all workers are at capacity -- return None gracefully.
        if candidates_override is not None:
            return None
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"No ACTIVE + CHECKED_IN employees found in "
            f"department {work_item.department_id}.",
            completed_steps=[{"agent": WORKFORCE_AGENT, "status": ExecutionStatus.SUCCESS}],
            metadata={"work_id": work_id},
        )

    # Step 3a: Relative capacity-aware preemption for HIGH/CRITICAL emergency tasks
    # For LOW/MEDIUM: use existing candidate ranking, no preemption.
    # For HIGH/CRITICAL emergency: compute a relative overload threshold from
    # the eligible candidate pool. Under-capacity workers get the task directly;
    # preemption only fires when all candidates are overworked.
    preempted_work_ids = []
    incoming_priority = work_item.priority
    is_urgent = is_emergency and (incoming_priority in (PriorityEnum.HIGH, PriorityEnum.CRITICAL))

    if is_urgent:
        # Filter out candidates that already have an active CRITICAL assignment.
        # This prevents piling emergencies onto workers handling the most
        # critical work. Applied only in the urgent/emergency path.
        filtered_candidates = []
        for c in candidates:
            active = get_active_assignments_for_employee(c["employee_id"], db)
            has_critical = any(
                a["priority"] == PriorityEnum.CRITICAL
                and a["assignment_status"] in (
                    AssignmentStatusEnum.ASSIGNED,
                    AssignmentStatusEnum.IN_PROGRESS,
                )
                and (same_event_work_ids is None or a["work_id"] not in same_event_work_ids)
                for a in active
            )
            if has_critical:
                print(
                    f"[ASSIGNMENT_AGENT] Skipping employee {c['employee_id']} "
                    f"for urgent work_id={work_id} -- already on a CRITICAL task."
                )
                continue
            # Stash active list and count for downstream partitioning
            c["_active_assignments"] = active
            c["_active_count"] = len(active)
            filtered_candidates.append(c)

        if not filtered_candidates:
            raise AgentExecutionError(
                ASSIGNMENT_AGENT,
                f"All eligible workers are currently assigned to CRITICAL tasks. "
                f"Cannot assign emergency work_id={work_id} "
                f"(priority={incoming_priority.value}). Escalating to human review.",
                metadata={
                    "work_id": work_id,
                    "escalation_required": True,
                    "escalation_type": "HUMAN_REVIEW_REQUIRED",
                },
            )

        candidates = filtered_candidates

        # Compute relative overload threshold from the eligible pool
        overload_threshold = get_config_value(db, "OVERLOAD_ABOVE_AVG_THRESHOLD", 3)
        total_active = sum(c["_active_count"] for c in candidates)
        avg_active = total_active / len(candidates)
        dynamic_limit = avg_active + overload_threshold
        print(
            f"[ASSIGNMENT_AGENT] Relative overload check for work_id={work_id}: "
            f"avg_active={avg_active:.1f}, dynamic_limit={dynamic_limit:.1f}"
        )

        # Partition candidates into under-capacity vs overworked
        not_overworked_candidates = []
        preemptible_overworked_candidates = []

        for c in candidates:
            active = c.pop("_active_assignments", [])
            active_count = c.pop("_active_count", 0)

            if active_count < dynamic_limit:
                not_overworked_candidates.append(c)
            else:
                # Overworked: check if any ASSIGNED task can be legally preempted
                preemptible_tasks = [
                    a for a in active
                    if a["assignment_status"] == AssignmentStatusEnum.ASSIGNED
                    and not a.get("required_skill")
                    and can_preempt(incoming_priority, a["priority"])
                ]
                if preemptible_tasks:
                    # Sort by priority rank ascending so we preempt the lowest first
                    preemptible_tasks.sort(key=lambda a: _PRIORITY_RANK.get(a["priority"], 0))
                    c["_preemptible_task"] = preemptible_tasks[0]
                    preemptible_overworked_candidates.append(c)

        if not_overworked_candidates:
            # Under-capacity candidates can take the task without preemption
            candidates = not_overworked_candidates
            print(
                f"[ASSIGNMENT_AGENT] {len(not_overworked_candidates)} under-capacity "
                f"candidate(s) available for urgent work_id={work_id}."
            )
        elif preemptible_overworked_candidates:
            # All candidates are overworked; preempt the lowest task from the best one
            best_preemptible = min(
                preemptible_overworked_candidates,
                key=lambda c: (
                    c.get("pending_task", 0),
                    -(c.get("experience_years") or 0),
                    c["employee_id"],
                ),
            )
            target_task = best_preemptible.pop("_preemptible_task")
            freed_work_id = preempt_assignment(
                assignment_id=target_task["assignment_id"],
                db=db,
                reason=(
                    f"Preempted for urgent {incoming_priority.value} task "
                    f"work_id={work_id}"
                ),
            )
            preempted_work_ids.append(freed_work_id)
            candidates = [best_preemptible]
            print(
                f"[ASSIGNMENT_AGENT] Preempted assignment_id={target_task['assignment_id']} "
                f"from employee {best_preemptible['employee_id']} "
                f"to assign urgent work_id={work_id}."
            )
        else:
            # All candidates overworked with non-preemptible tasks, escalate
            raise AgentExecutionError(
                ASSIGNMENT_AGENT,
                f"All eligible workers are overworked with non-preemptible tasks. "
                f"Cannot preempt for work_id={work_id} "
                f"(priority={incoming_priority.value}).",
                metadata={
                    "work_id": work_id,
                    "escalation_required": True,
                    "escalation_type": "HUMAN_REVIEW_REQUIRED",
                },
            )
    else:
        # Clean up any leftover _preemptible_task keys from previous iterations
        for c in candidates:
            c.pop("_preemptible_task", None)

    # Step 3b: select best candidate (reasoning with deterministic fallback)
    candidate_ids = [c["employee_id"] for c in candidates]
    engine_name = "DETERMINISTIC_FALLBACK"
    confidence = None
    reasoning_rationale = ""
    reasoning_time_ms = None

    # Resolve task context for the prompt
    task_obj = work_item.task  # SQLAlchemy relationship
    task_name = task_obj.task_name if task_obj else f"work_id_{work_id}"
    task_description = task_obj.description if task_obj else ""
    task_priority = work_item.priority.value if work_item.priority else "MEDIUM"

    # Try reasoning engine
    try:
        reasoning_result = _select_candidate_with_reasoning(
            task_name=task_name,
            task_description=task_description,
            priority=task_priority,
            candidates=candidates,
        )

        best_candidate = next(
            c for c in candidates
            if c["employee_id"] == reasoning_result["employee_id"]
        )
        engine_name = REASONING_MODEL
        confidence = reasoning_result["confidence"]
        reasoning_rationale = reasoning_result["reasoning_rationale"]
        reasoning_time_ms = reasoning_result["execution_time_ms"]

        print(
            f"[ASSIGNMENT_AGENT] Reasoning selection successful: "
            f"employee {best_candidate['employee_id']} ({best_candidate['name']}) "
            f"| confidence={confidence} | time={reasoning_time_ms}ms"
        )

    except Exception as exc:
        # Fallback to deterministic: min(pending, -experience, id)
        print(f"[ASSIGNMENT_AGENT] Reasoning fallback: {exc}")

        best_candidate = min(
            candidates,
            key=lambda c: (
                c.get("pending_task", 0),
                -(c.get("experience_years") or 0),
                c["employee_id"],
            ),
        )
        reasoning_rationale = f"Fallback: {exc}"

    print(
        f"[ASSIGNMENT_AGENT] Selected employee {best_candidate['employee_id']} "
        f"({best_candidate['name']}) for work_id {work_id}."
    )

    # Step 4: create TaskAssignment
    assignment = TaskAssignment(
        work_id=work_id,
        employee_id=best_candidate["employee_id"],
        assignment_status=AssignmentStatusEnum.ASSIGNED,
    )
    db.add(assignment)
    db.flush()  # get assignment_id before committing

    # Step 5: update work queue item status to ASSIGNED (atomic check)
    updated_rows = (
        db.query(DepartmentWorkQueue)
        .filter(
            DepartmentWorkQueue.work_id == work_id,
            DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED,
        )
        .update(
            {DepartmentWorkQueue.queue_status: WorkQueueStatusEnum.ASSIGNED},
            synchronize_session=False,
        )
    )
    if updated_rows == 0:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Work item {work_id} was already assigned by a concurrent transaction.",
        )
    db.refresh(work_item)

    # Step 6: log the event
    event = EventLog(
        event_log="TASK_ASSIGNED",
        source_module="ASSIGNMENT_AGENT",
        employee_id=best_candidate["employee_id"],
        work_id=work_id,
        assignment_id=assignment.assignment_id,
    )
    db.add(event)
    db.flush()  # get event_id before committing

    # Step 7: log the agent action with full audit trail
    confidence_str = f" | confidence={confidence}" if confidence is not None else ""
    decision_summary = (
        f"[{engine_name}] task_name={task_name} | priority={task_priority} | "
        f"candidates_considered={len(candidates)} (ids: {', '.join(str(i) for i in candidate_ids)}) | "
        f"selected=employee_id {best_candidate['employee_id']} ({best_candidate['name']})"
        f"{confidence_str} | "
        f"reason: {reasoning_rationale}"
        + (f" | reassignment_reason={assignment_reason}" if assignment_reason else "")
    )

    action = AgentActionLog(
        event_id=event.event_id,
        department_id=work_item.department_id,
        agent_id=2,
        action_type="ASSIGN_TASK",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=decision_summary,
        reasoning_engine=engine_name,
        execution_time_ms=reasoning_time_ms,
        workflow_id=workflow_id,
    )
    db.add(action)

    # Step 8: increment worker pending task count
    memory = get_or_create_worker_memory(db, best_candidate["employee_id"])
    memory.pending_task = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == best_candidate["employee_id"],
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .count()
    )

    # Step 9: Post-selection emergency overtime check
    # When an emergency task is assigned to a worker near shift end (within 15 min),
    # raise an EMERGENCY_OVERTIME_ASSIGNED escalation for supervisor awareness
    if is_emergency:
        from app.models.shift_roster import ShiftRoster
        from app.models.shift import Shift
        from app.models.enums import RosterStatusEnum

        emp_id = best_candidate["employee_id"]
        now = datetime.now() if not hasattr(_assign_task, '_test_now') else _assign_task._test_now

        roster = (
            db.query(ShiftRoster)
            .filter(
                ShiftRoster.employee_id == emp_id,
                ShiftRoster.work_date == datetime.now().date(),
                ShiftRoster.roster_status.in_([
                    RosterStatusEnum.CHECKED_IN,
                    RosterStatusEnum.HALF_DAY,
                ]),
            )
            .order_by(ShiftRoster.roster_id.desc())
            .first()
        )

        if roster and not roster.is_overtime:
            shift_obj = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
            if shift_obj:
                shift_end_dt = datetime.combine(roster.work_date, shift_obj.end_time)
                shift_start_dt = datetime.combine(roster.work_date, shift_obj.start_time)
                if shift_end_dt <= shift_start_dt:
                    shift_end_dt += timedelta(days=1)

                buffer_cutoff = now + timedelta(minutes=15)
                if shift_end_dt <= buffer_cutoff:
                    import json as _json
                    import uuid as _uuid
                    from app.models.approval_request import ApprovalRequest
                    from app.models.employee import Employee as _Emp

                    emp_obj = db.query(_Emp).filter(_Emp.employee_id == emp_id).first()
                    emp_name = emp_obj.name if emp_obj else f"employee_{emp_id}"

                    context = {
                        "roster_id": roster.roster_id,
                        "employee_id": emp_id,
                        "employee_name": emp_name,
                        "department_id": work_item.department_id,
                        "work_id": work_id,
                        "task_name": task_name,
                        "shift_end_time": shift_end_dt.isoformat(),
                        "assignment_id": assignment.assignment_id,
                    }

                    emergency_approval = ApprovalRequest(
                        workflow_id=str(_uuid.uuid4()),
                        sensitive_action="EMERGENCY_OVERTIME_ASSIGNED",
                        rationale=(
                            f"Emergency task '{task_name}' (work_id={work_id}) assigned to "
                            f"{emp_name} whose shift ends at {shift_end_dt.strftime('%H:%M')}. "
                            f"Worker is within 15-minute buffer. Overtime may be required."
                        ),
                        status="PENDING",
                        context_state_json=_json.dumps(context, default=str),
                    )
                    db.add(emergency_approval)
                    db.flush()
                    print(
                        f"[ASSIGNMENT_AGENT] EMERGENCY_OVERTIME_ASSIGNED: "
                        f"employee {emp_id} near shift end, approval_id={emergency_approval.approval_id}"
                    )

    # Queue WhatsApp notification outbox event (atomic with assignment)
    from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake
    from app.models.enums import HospitalEventEnum
    notif_available_after = None
    if notification_delay_seconds > 0:
        notif_available_after = datetime.now() + timedelta(seconds=notification_delay_seconds)
    create_outbox_event(
        db,
        event_type=HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
        payload={"employee_id": best_candidate["employee_id"], "work_id": work_id},
        dedupe_key=f"SEND_WHATSAPP_NOTIFICATION:assignment_id={assignment.assignment_id}",
        available_after=notif_available_after,
    )

    db.commit()
    signal_outbox_wake()

    print(
        f"[ASSIGNMENT_AGENT] Done. "
        f"assignment_id={assignment.assignment_id}, "
        f"event_id={event.event_id}, "
        f"agent_action_id={action.agent_action_id}"
    )

    return {
        "assignment_id": assignment.assignment_id,
        "event_id": event.event_id,
        "agent_action_id": action.agent_action_id,
        "employee_id": best_candidate["employee_id"],
        "employee_name": best_candidate["name"],
        "preempted_work_ids": preempted_work_ids,
        "workflow": [
            {"agent": WORKFORCE_AGENT, "status": ExecutionStatus.SUCCESS},
            {"agent": ASSIGNMENT_AGENT, "status": ExecutionStatus.SUCCESS},
        ],
    }


# Public API

def run_assignment_cycle(
    department_id: int,
    db: Session,
    trigger: str = AssignmentTrigger.NEW_TASK,
    shift_id: Optional[int] = None,
    work_ids: Optional[list[int]] = None,
    allow_shift_end_buffer: bool = True,
    workflow_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> dict:
    """
    Public assignment API: run a full allocation cycle for a department.

    Allocation Strategy:
        - WORKER_CHECKIN trigger:  Fair share mode. Computes a per-worker
          task cap based on (pending / checked-in workers) and filters candidates
          before passing them to _assign_task. Stops when all checked-in
          workers hit their cap.
        - All other triggers:  Unlimited mode. Assigns every pending
          item with no cap (existing behavior).

    Per-task candidate resolution:
        Each pending work item is resolved individually via get_candidate()
        with its task_id so that required_skill filtering applies per task.
        A shared pending_by_employee counter tracks assignments across
        the entire cycle to prevent double-counting in fair-share mode.

    Returns:
        A summary dict with status (SUCCESS/PARTIAL_SUCCESS/FAILED),
        successful assignments, failures, escalations, and cumulative
        workflow execution steps.
    """

    if isinstance(current_time, str):
        current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
    if current_time is not None and current_time.tzinfo is not None:
        current_time = current_time.astimezone().replace(tzinfo=None)

    print("=" * 60)
    print("  ASSIGNMENT AGENT -- run_assignment_cycle")
    print(f"  department_id = {department_id}")
    print(f"  trigger       = {trigger}")
    print("=" * 60)

    priority_order = case(
        (DepartmentWorkQueue.priority == PriorityEnum.CRITICAL, 1),
        (DepartmentWorkQueue.priority == PriorityEnum.HIGH, 2),
        (DepartmentWorkQueue.priority == PriorityEnum.MEDIUM, 3),
        (DepartmentWorkQueue.priority == PriorityEnum.LOW, 4),
        else_=5,
    )

    # Step 1: Fetch all pending work items for the department (priority-first, then FIFO)
    query = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.department_id == department_id,
        DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED,
    )
    if work_ids is not None:
        if not work_ids:
            return {
                "status": ExecutionStatus.SUCCESS,
                "department_id": department_id,
                "assigned": [],
                "failures": [],
                "escalations": [],
                "total_assigned": 0,
                "total_failed": 0,
                "workflow": [
                    {"agent": ASSIGNMENT_AGENT, "status": ExecutionStatus.SUCCESS},
                ],
            }
        query = query.filter(DepartmentWorkQueue.work_id.in_(work_ids))
    if shift_id is not None:
        query = query.filter(
            (DepartmentWorkQueue.shift_id == shift_id)
            | DepartmentWorkQueue.shift_id.is_(None)
        )
    if _supports_row_lock(db):
        query = query.with_for_update(of=DepartmentWorkQueue)
    pending_items = (
        query.order_by(
            priority_order.asc(),
            DepartmentWorkQueue.due_date.asc(),
            DepartmentWorkQueue.work_id.asc(),
        )
        .all()
    )

    if not pending_items:
        print("[ASSIGNMENT_AGENT] No pending work items found -- nothing to assign.")
        return {
            "status": ExecutionStatus.SUCCESS,
            "department_id": department_id,
            "assigned": [],
            "failures": [],
            "escalations": [],
            "total_assigned": 0,
            "total_failed": 0,
            "workflow": [
                {"agent": ASSIGNMENT_AGENT, "status": ExecutionStatus.SUCCESS},
            ],
        }

    pending_count = len(pending_items)
    print(f"\n[Step 1] Found {pending_count} pending work item(s)")
    for item in pending_items:
        print(f"         work_id={item.work_id}")

    # Step 2: Determine assignment mode
    fair_share_limit = None
    shift_name = None
    total_shift_rostered = None

    is_fair_share = (trigger == AssignmentTrigger.WORKER_CHECKIN and shift_id is not None)

    if is_fair_share:
        # Query shift context for fair share calculation (task_id=None here
        # because we only need roster/shift counts, not skill filtering)
        try:
            shift_context_result = get_candidate(
                department_id=department_id, db=db, shift_id=shift_id,
                allow_shift_end_buffer=allow_shift_end_buffer,
                current_time=current_time,
            )
        except ValueError as exc:
            print(f"[ASSIGNMENT_AGENT] Workforce Agent error: {exc}")
            return {
                "status": ExecutionStatus.FAILED,
                "department_id": department_id,
                "assigned": [],
                "failures": [{"reason": str(exc), "agent": WORKFORCE_AGENT}],
                "escalations": [],
                "total_assigned": 0,
                "total_failed": 0,
                "workflow": [
                    {"agent": WORKFORCE_AGENT, "status": ExecutionStatus.FAILED},
                ],
            }

        # If shift context itself is an escalation (no workers available),
        # return early with FAILED status
        if shift_context_result.get("escalation_required"):
            reason = shift_context_result.get("reason", "No available workers.")
            print(f"[ASSIGNMENT_AGENT] Shift context escalation: {reason}")
            return {
                "status": ExecutionStatus.FAILED,
                "department_id": department_id,
                "assigned": [],
                "failures": [{"reason": reason, "agent": WORKFORCE_AGENT}],
                "escalations": [],
                "total_assigned": 0,
                "total_failed": 0,
                "workflow": [
                    {"agent": WORKFORCE_AGENT, "status": ExecutionStatus.FAILED},
                ],
            }

        total_shift_rostered = shift_context_result.get("total_shift_rostered", 1)
        checked_in_count = shift_context_result.get("checked_in_count", 0)
        shift_name = shift_context_result.get("shift_name", f"shift_{shift_id}")

        # Lift the cap if all rostered workers are checked in
        if checked_in_count == total_shift_rostered:
            is_fair_share = False
            print()
            print("  " + "-" * 40)
            print(f"  [ASSIGNMENT_AGENT] Assignment Mode  : UNLIMITED (All workers checked in)")
            print(f"  [ASSIGNMENT_AGENT] Shift            : {shift_name}")
            print(f"  [ASSIGNMENT_AGENT] Pending Tasks    : {pending_count}")
            print(f"  [ASSIGNMENT_AGENT] Rostered Workers : {total_shift_rostered}")
            print("  " + "-" * 40)
        else:
            fair_share_limit = max(1, math.ceil(pending_count / max(checked_in_count, 1)))
            print()
            print("  " + "-" * 40)
            print(f"  [ASSIGNMENT_AGENT] Assignment Mode  : FAIR_SHARE")
            print(f"  [ASSIGNMENT_AGENT] Shift            : {shift_name}")
            print(f"  [ASSIGNMENT_AGENT] Pending Tasks    : {pending_count}")
            print(f"  [ASSIGNMENT_AGENT] Checked-in Workers: {checked_in_count}")
            print(f"  [ASSIGNMENT_AGENT] Fair Share Limit : {fair_share_limit}")
            print("  " + "-" * 40)
    else:
        print()
        print(f"  [ASSIGNMENT_AGENT] Assignment Mode  : UNLIMITED")
        print(f"  [ASSIGNMENT_AGENT] Trigger          : {trigger}")

    # Step 3: Per-task candidate resolution and assignment
    # Shared workload accounting: track assignments made in this cycle
    # so fair-share filtering stays accurate across work items.
    pending_by_employee = {}
    # Snapshot each employee's initial DB pending_task the first time
    # they appear in a candidate list. This avoids double-counting
    # because _assign_task flushes the DB (incrementing pending_task)
    # before the next iteration queries get_candidate again.
    initial_pending_by_employee = {}
    assigned_high_critical_in_cycle = {}
    is_worker_checkin_trigger = (trigger == AssignmentTrigger.WORKER_CHECKIN)
    assigned = []
    failures = []
    escalations = []
    cumulative_workflow = []
    all_preempted_work_ids = []

    for cycle_index, item in enumerate(pending_items):
        print(f"\n[Cycle] Assigning work_id={item.work_id}...")
        notif_delay = cycle_index * 2

        try:
            # Per-task candidate resolution: each task gets its own
            # get_candidate call with task_id for skill filtering
            candidate_result = get_candidate(
                department_id=department_id,
                db=db,
                task_id=item.task_id,
                shift_id=shift_id,
                allow_shift_end_buffer=allow_shift_end_buffer,
                current_time=current_time,
            )

            candidates = candidate_result.get("candidates", [])

            # Exclude workers who were previously preempted from this work_id
            # so the same task is never auto-assigned back to the same worker
            if candidates:
                preempted_employee_ids = {
                    row.employee_id for row in
                    db.query(TaskAssignment.employee_id).filter(
                        TaskAssignment.work_id == item.work_id,
                        TaskAssignment.assignment_status == AssignmentStatusEnum.PREEMPTED,
                    ).all()
                }
                if preempted_employee_ids:
                    candidates = [
                        c for c in candidates
                        if c["employee_id"] not in preempted_employee_ids
                    ]
                    print(
                        f"         [FILTER] Excluded {len(preempted_employee_ids)} "
                        f"previously-preempted worker(s) from candidates for "
                        f"work_id={item.work_id}: {preempted_employee_ids}"
                    )

            # Apply fair-share cap: use the initial DB snapshot plus
            # in-cycle assignments to avoid double-counting flushed DB values.
            if is_fair_share and candidates:
                for c in candidates:
                    eid = c["employee_id"]
                    if eid not in initial_pending_by_employee:
                        initial_pending_by_employee[eid] = c.get("pending_task", 0) or 0
                candidates = [
                    c for c in candidates
                    if (initial_pending_by_employee.get(c["employee_id"], 0) + pending_by_employee.get(c["employee_id"], 0)) < fair_share_limit
                ]
                if not candidates:
                    print(
                        f"         [STOP] All checked-in workers at capacity "
                        f"(fair_share_limit={fair_share_limit}). "
                        f"Remaining tasks stay PENDING."
                    )
                    break

            # Normalize priority for enum comparison
            priority = item.priority
            if isinstance(priority, str):
                priority = PriorityEnum(priority)

            # Round-robin HIGH/CRITICAL tasks during worker check-in
            if is_worker_checkin_trigger and priority in (PriorityEnum.HIGH, PriorityEnum.CRITICAL) and candidates:
                min_urgent = min(
                    assigned_high_critical_in_cycle.get(c["employee_id"], 0)
                    for c in candidates
                )
                candidates = [
                    c for c in candidates
                    if assigned_high_critical_in_cycle.get(c["employee_id"], 0) == min_urgent
                ]

            result = _assign_task(
                work_id=item.work_id,
                db=db,
                candidates_override=candidates if candidates else None,
                candidate_resolution=candidate_result,
                notification_delay_seconds=notif_delay,
                workflow_id=workflow_id,
                assignment_reason=(
                    "scheduled employee marked absent"
                    if trigger == "STAFF_ABSENT"
                    else None
                ),
            )

            if result is None:
                print(
                    f"         [STOP] _assign_task returned None. "
                    f"Stopping assignment cycle."
                )
                break

            # Update shared workload counters
            assigned_eid = result["employee_id"]
            pending_by_employee[assigned_eid] = (
                pending_by_employee.get(assigned_eid, 0) + 1
            )
            if priority in (PriorityEnum.HIGH, PriorityEnum.CRITICAL):
                assigned_high_critical_in_cycle[assigned_eid] = (
                    assigned_high_critical_in_cycle.get(assigned_eid, 0) + 1
                )

            assigned.append({
                "work_id": item.work_id,
                "assignment_id": result["assignment_id"],
                "employee_id": result["employee_id"],
                "employee_name": result["employee_name"],
            })
            cumulative_workflow.extend(result["workflow"])

            # Collect any preempted work_ids from this assignment
            task_preempted = result.get("preempted_work_ids", [])
            if task_preempted:
                all_preempted_work_ids.extend(task_preempted)

            print(f"         [OK] Assigned to {result['employee_name']}")

        except AgentExecutionError as exc:
            failure_entry = {
                "work_id": item.work_id,
                "reason": exc.message,
                "agent": exc.agent,
                "metadata": exc.metadata,
            }

            # Track escalations separately from regular failures
            if exc.metadata.get("escalation_required"):
                failure_entry["escalation_required"] = True
                failure_entry["escalation_type"] = exc.metadata.get("escalation_type")
                escalations.append(failure_entry)
                print(
                    f"         [ESCALATION] {exc.metadata.get('escalation_type')}: "
                    f"{exc.message}"
                )
            else:
                print(f"         [FAIL] {exc.message}")

            failures.append(failure_entry)
            cumulative_workflow.extend(exc.completed_steps)
            cumulative_workflow.append(
                {"agent": exc.agent, "status": ExecutionStatus.FAILED}
            )

    # Step 4: Determine cycle status
    if assigned and not failures:
        cycle_status = ExecutionStatus.SUCCESS
    elif assigned and failures:
        cycle_status = ExecutionStatus.PARTIAL_SUCCESS
    else:
        cycle_status = ExecutionStatus.FAILED

    # Step 5: Summary
    print()
    print("=" * 60)
    print("  ASSIGNMENT CYCLE RESULT")
    print("=" * 60)
    print(f"  status               : {cycle_status}")
    print(f"  trigger              : {trigger}")
    if is_fair_share:
        print(f"  mode                 : FAIR_SHARE")
        print(f"  fair_share_limit     : {fair_share_limit}")
    else:
        print(f"  mode                 : UNLIMITED")
    print(f"  total_assigned       : {len(assigned)}")
    print(f"  total_failed         : {len(failures)}")
    print(f"  total_escalations    : {len(escalations)}")
    print("=" * 60)

    return {
        "status": cycle_status,
        "department_id": department_id,
        "assigned": assigned,
        "failures": failures,
        "escalations": escalations,
        "total_assigned": len(assigned),
        "total_failed": len(failures),
        "preempted_work_ids": all_preempted_work_ids,
        "total_preempted": len(all_preempted_work_ids),
        "workflow": cumulative_workflow,
    }


def automate_work_item_assignment(
    work_id: int,
    db: Session,
    workflow_id: Optional[str] = None,
    trigger: str = "AUTOMATIC_RECOVERY",
    reassign_unstarted: bool = False,
) -> dict:
    """Assign or safely reassign one work item using normal eligibility rules."""
    if workflow_id:
        prior_outcome = (
            db.query(AgentActionLog)
            .filter(
                AgentActionLog.workflow_id == workflow_id,
                AgentActionLog.action_type.in_([
                    "AUTOMATIC_REASSIGNMENT",
                    "AUTOMATIC_ASSIGNMENT",
                    "ESCALATION",
                ]),
                AgentActionLog.decision_summary.contains(f"work_id={work_id}"),
            )
            .order_by(AgentActionLog.agent_action_id.desc())
            .first()
        )
        if prior_outcome is not None:
            return {
                "action": "ALREADY_PROCESSED",
                "status": ExecutionStatus.SUCCESS,
                "assigned": [],
                "failures": [],
                "total_assigned": 0,
                "total_failed": 0,
                "agent_action_id": prior_outcome.agent_action_id,
            }

    query = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.work_id == work_id
    )
    if _supports_row_lock(db):
        query = query.with_for_update(of=DepartmentWorkQueue)
    work_item = query.first()
    if work_item is None:
        raise AgentExecutionError(
            ASSIGNMENT_AGENT,
            f"Work queue item {work_id} not found.",
        )

    active_assignments = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == work_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .all()
    )
    in_progress = [
        assignment for assignment in active_assignments
        if assignment.assignment_status == AssignmentStatusEnum.IN_PROGRESS
    ]
    if in_progress:
        return {
            "action": "IN_PROGRESS_RETAINED",
            "status": ExecutionStatus.PARTIAL_SUCCESS,
            "assigned": [],
            "failures": [],
            "total_assigned": 0,
            "total_failed": 0,
            "reason": "Work is already in progress and was not interrupted.",
        }

    if active_assignments and not reassign_unstarted:
        return {
            "action": "ALREADY_ASSIGNED",
            "status": ExecutionStatus.SUCCESS,
            "assigned": [],
            "failures": [],
            "total_assigned": 0,
            "total_failed": 0,
        }

    if work_item.queue_status not in (
        WorkQueueStatusEnum.PENDING_ASSIGNED,
        WorkQueueStatusEnum.ASSIGNED,
    ):
        return {
            "action": "NO_PENDING_WORK",
            "status": ExecutionStatus.SUCCESS,
            "assigned": [],
            "failures": [],
            "total_assigned": 0,
            "total_failed": 0,
        }

    for assignment in active_assignments:
        preempt_assignment(
            assignment.assignment_id,
            db,
            reason=f"Automatic recovery: {trigger}.",
            source_module="ASSIGNMENT_AGENT",
        )

    if work_item.queue_status == WorkQueueStatusEnum.ASSIGNED:
        work_item.queue_status = WorkQueueStatusEnum.PENDING_ASSIGNED
        db.flush()

    result = run_assignment_cycle(
        department_id=work_item.department_id,
        db=db,
        trigger=trigger,
        shift_id=work_item.shift_id,
        work_ids=[work_id],
        workflow_id=workflow_id,
    )
    return {"action": "ASSIGNMENT_ATTEMPTED", **result}


def assign_emergency_work_items(work_ids: list[int], db: Session) -> dict:
    """Resilient per-item assignment for emergency work items.

    Loops over work_ids, assigns each via _assign_task, and catches
    per-item failures so remaining items can still be assigned.

    If any preemption occurs, collects affected department IDs and
    triggers run_assignment_cycle for those departments to immediately
    reroute preempted tasks back to available workers.
    """
    assignments = []
    assignment_failures = []
    local_workflow = []
    all_preempted_work_ids = []
    affected_departments = set()

    if not work_ids:
        return {
            "assignments": assignments,
            "assignment_failures": assignment_failures,
            "preempted_work_ids": all_preempted_work_ids,
            "workflow": local_workflow,
        }

    print(f"[ASSIGNMENT_AGENT] Running emergency assignment for {len(work_ids)} task(s)...")

    for work_id in work_ids:
        try:
            result = _assign_task(
                work_id=work_id,
                db=db,
                allow_shift_end_buffer=False,
                is_emergency=True,
                same_event_work_ids=work_ids,
            )
            if result is None:
                continue

            local_workflow.extend(result["workflow"])
            assignments.append({
                "work_id": work_id,
                "assignment_id": result["assignment_id"],
                "employee_id": result["employee_id"],
                "employee_name": result["employee_name"],
            })

            # Track preemptions and their departments for rerouting
            task_preempted = result.get("preempted_work_ids", [])
            if task_preempted:
                all_preempted_work_ids.extend(task_preempted)
                # Look up department_id for each preempted work item
                for pw_id in task_preempted:
                    pw = (
                        db.query(DepartmentWorkQueue)
                        .filter(DepartmentWorkQueue.work_id == pw_id)
                        .first()
                    )
                    if pw:
                        affected_departments.add(pw.department_id)

            print(f"[ASSIGNMENT_AGENT] Assigned work_id={work_id} to {result['employee_name']}")

        except AgentExecutionError as exc:
            local_workflow.extend(exc.completed_steps)
            status = ExecutionStatus.PARTIAL_SUCCESS if "HUMAN_REVIEW_REQUIRED" in str(exc.message) else ExecutionStatus.FAILED
            local_workflow.append({
                "agent": exc.agent,
                "status": status,
            })
            assignment_failures.append({
                "work_id": work_id,
                "reason": exc.message,
            })
            print(f"[ASSIGNMENT_AGENT] Assignment FAILED for work_id={work_id}: {exc.message}")

    # Reroute preempted tasks in affected departments
    if affected_departments:
        print(
            f"[ASSIGNMENT_AGENT] Rerouting preempted tasks in "
            f"{len(affected_departments)} department(s): {affected_departments}"
        )
        for dept_id in affected_departments:
            try:
                reroute_result = run_assignment_cycle(
                    department_id=dept_id,
                    db=db,
                    trigger=AssignmentTrigger.NEW_TASK,
                )
                local_workflow.extend(reroute_result.get("workflow", []))
            except Exception as exc:
                print(
                    f"[ASSIGNMENT_AGENT] Reroute failed for "
                    f"department {dept_id}: {exc}"
                )

    return {
        "assignments": assignments,
        "assignment_failures": assignment_failures,
        "preempted_work_ids": all_preempted_work_ids,
        "workflow": local_workflow,
    }


# Overload Rebalancing

def rebalance_overloaded_worker(employee_id: int, db: Session) -> dict:
    """Rebalance an overloaded worker by preempting non-specialized tasks.

    Called when the outbox WORKER_OVERLOAD_DETECTED event fires.
    Releases ASSIGNED-status tasks of LOW or MEDIUM priority that
    do not require the employee's specialized skills, returning them
    to the queue for rerouting.

    Only preempts ASSIGNED tasks (not IN_PROGRESS) to avoid
    interrupting physically started work.
    """
    print("=" * 60)
    print("  ASSIGNMENT AGENT -- rebalance_overloaded_worker")
    print(f"  employee_id = {employee_id}")
    print("=" * 60)

    # Step 1: Load employee and normalize their skills
    employee = (
        db.query(Employee)
        .filter(Employee.employee_id == employee_id)
        .first()
    )
    if not employee:
        raise ValueError(f"employee_id={employee_id} not found")

    worker_skills = set()
    if employee.skill:
        worker_skills = {s.strip().upper() for s in employee.skill.split(",") if s.strip()}

    department_id = employee.department_id
    print(f"  Worker skills: {worker_skills or 'none'}")

    # Step 2: Get active ASSIGNED assignments
    active = get_active_assignments_for_employee(employee_id, db)
    assigned_tasks = [
        a for a in active
        if a["assignment_status"] == AssignmentStatusEnum.ASSIGNED
    ]

    if not assigned_tasks:
        print("  No ASSIGNED tasks to rebalance.")
        return {
            "department_id": department_id,
            "preempted_work_ids": [],
            "total_preempted": 0,
            "action": "rebalanced_workload",
        }

    # Step 3: Filter to LOW/MEDIUM tasks without required_skill
    # Tasks with required_skill are never auto-preempted
    preempted_work_ids = []
    for task_info in assigned_tasks:
        priority = task_info["priority"]
        if priority not in (PriorityEnum.LOW, PriorityEnum.MEDIUM):
            continue

        # Never preempt a task that requires a specialized skill
        if task_info.get("required_skill"):
            print(
                f"  Keeping assignment_id={task_info['assignment_id']} "
                f"(requires specialized skill: {task_info['required_skill']})"
            )
            continue

        # Preempt this task
        freed_work_id = preempt_assignment(
            assignment_id=task_info["assignment_id"],
            db=db,
            reason=(
                f"Worker overload rebalancing for employee_id={employee_id}. "
                f"Task priority={priority.value}, no specialized skill match."
            ),
            source_module="ASSIGNMENT_AGENT",
        )
        preempted_work_ids.append(freed_work_id)

    db.commit()
    if preempted_work_ids:
        from app.services.outbox_dispatcher import signal_outbox_wake
        signal_outbox_wake()

    print(f"  Preempted {len(preempted_work_ids)} task(s): {preempted_work_ids}")
    print("=" * 60)

    return {
        "department_id": department_id,
        "preempted_work_ids": preempted_work_ids,
        "total_preempted": len(preempted_work_ids),
        "action": "rebalanced_workload",
    }
