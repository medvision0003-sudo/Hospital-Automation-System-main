from datetime import datetime

import pytest
import langchain
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.task_verification_agent import verify_task_proof
from app.orchestrator.graphs.langgraph_adapter import run_langgraph_proof_verification
from app.database.base import Base
from app.models.agent_table import AgentTable
from app.models.department import Department
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.employee import Employee
from app.models.enums import (
    AssignmentStatusEnum,
    EmploymentStatusEnum,
    GenderEnum,
    PriorityEnum,
    TaskProofStatusEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    WorkQueueStatusEnum,
)
from app.models.system_config import SystemConfig
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.task_proof import TaskProof
from app.services import gemini_proof_verifier


@pytest.fixture
def proof_session(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    monkeypatch.chdir(tmp_path)

    with session_local() as db:
        department = Department(department_name="Proof Verification Test")
        db.add(department)
        db.flush()
        employee = Employee(
            department_id=department.department_id,
            name="Proof Worker",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        task = TaskMaster(
            task_state=TaskStatusEnum.ACTIVE,
            department_id=department.department_id,
            task_name="Clean ICU Bed 12",
            description="Clean and sanitize the bed and immediate area.",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.EVENT_TEMPLATE,
        )
        agent = AgentTable(
            agent_id=7,
            agent_name="TASK_VERIFICATION_AGENT",
            agent_category="TASK_VERIFICATION_AGENT",
        )
        db.add_all([employee, task, agent])
        db.flush()
        work_item = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=department.department_id,
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work_item)
        db.flush()
        assignment = TaskAssignment(
            work_id=work_item.work_id,
            employee_id=employee.employee_id,
            assignment_status=AssignmentStatusEnum.IN_PROGRESS,
        )
        proof_path = f"uploads/{work_item.work_id}/proof.jpg"
        proof = TaskProof(
            work_id=work_item.work_id,
            employee_id=employee.employee_id,
            proof_image_path=proof_path,
            verification_status=TaskProofStatusEnum.PENDING,
            submitted_at=datetime.now(),
        )
        db.add_all([assignment, proof])
        db.add_all(
            [
                SystemConfig(
                    config_key="MIN_VERIFICATION_CONFIDENCE_SCORE",
                    config_value="0.70",
                    value_type="float",
                ),
                SystemConfig(
                    config_key="ENABLE_AUTOMATED_PROOF_APPROVAL",
                    config_value="false",
                    value_type="boolean",
                ),
            ]
        )
        db.commit()

        image = tmp_path / proof_path
        image.parent.mkdir(parents=True)
        image.write_bytes(b"test image bytes")

        yield db, proof, work_item

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_high_confidence_ai_result_is_visible_but_requires_review_by_default(
    proof_session,
    monkeypatch,
):
    db, proof, work_item = proof_session
    monkeypatch.setattr(
        gemini_proof_verifier,
        "analyze_task_proof",
        lambda *args: {
            "decision": "VERIFIED",
            "confidence": 0.91,
            "reason": "The image shows the requested bed area.",
        },
    )

    result = verify_task_proof(
        work_id=work_item.work_id,
        proof_image_path=proof.proof_image_path,
        db=db,
    )

    assert result["decision"] == "VERIFIED"
    assert result["review_required"] is True
    assert result["verification_confidence"] == 0.91
    assert proof.ai_decision == "VERIFIED"
    assert proof.verification_status == TaskProofStatusEnum.PENDING
    assert "requested bed area" in proof.verification_rationale


def test_low_confidence_result_is_routed_to_human_review(
    proof_session,
    monkeypatch,
):
    db, proof, work_item = proof_session
    monkeypatch.setattr(
        gemini_proof_verifier,
        "analyze_task_proof",
        lambda *args: {
            "decision": "VERIFIED",
            "confidence": 0.45,
            "reason": "The room is partly visible.",
        },
    )

    result = verify_task_proof(
        work_id=work_item.work_id,
        proof_image_path=proof.proof_image_path,
        db=db,
    )

    assert result["decision"] == "NEEDS_REVIEW"
    assert result["review_required"] is True
    assert proof.ai_decision == "NEEDS_REVIEW"
    assert proof.verification_status == TaskProofStatusEnum.PENDING
    assert "below the configured threshold" in proof.verification_rationale


def test_uncertain_verification_returns_needs_review_from_workflow(
    proof_session,
    monkeypatch,
):
    db, proof, work_item = proof_session
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    monkeypatch.setattr(
        gemini_proof_verifier,
        "analyze_task_proof",
        lambda *args: {
            "decision": "VERIFIED",
            "confidence": 0.45,
            "reason": "The room is partly visible.",
        },
    )

    result = run_langgraph_proof_verification(
        db=db,
        work_id=work_item.work_id,
        proof_image_path=proof.proof_image_path,
    )

    assert result["decision"] == "NEEDS_REVIEW"
    assert result["review_required"] is True
    assert proof.verification_status == TaskProofStatusEnum.PENDING


def test_opted_in_high_confidence_verification_persists_approval(
    proof_session,
    monkeypatch,
):
    db, proof, work_item = proof_session
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    db.query(SystemConfig).filter(
        SystemConfig.config_key == "ENABLE_AUTOMATED_PROOF_APPROVAL"
    ).one().config_value = "true"
    monkeypatch.setattr(
        gemini_proof_verifier,
        "analyze_task_proof",
        lambda *args: {
            "decision": "VERIFIED",
            "confidence": 0.95,
            "reason": "The image provides clear evidence of the completed task.",
        },
    )

    result = run_langgraph_proof_verification(
        db=db,
        work_id=work_item.work_id,
        proof_image_path=proof.proof_image_path,
    )

    assert result["proof_verified"] is True
    assert result["decision"] == "APPROVED"
    assert proof.verification_status == TaskProofStatusEnum.VERIFIED
    assert proof.ai_decision == "VERIFIED"
    assert proof.verification_confidence == 0.95
    assert proof.verified_at is not None


def test_high_confidence_rejection_does_not_approve_task(
    proof_session,
    monkeypatch,
):
    db, proof, work_item = proof_session
    monkeypatch.setattr(langchain, "debug", False, raising=False)
    monkeypatch.setattr(
        gemini_proof_verifier,
        "analyze_task_proof",
        lambda *args: {
            "decision": "REJECTED",
            "confidence": 0.93,
            "reason": "The image does not show the assigned ICU bed.",
        },
    )

    result = run_langgraph_proof_verification(
        db=db,
        work_id=work_item.work_id,
        proof_image_path=proof.proof_image_path,
    )

    assert result["proof_verified"] is False
    assert result["decision"] == "REJECTED"
    assert proof.verification_status == TaskProofStatusEnum.REJECTED
    assert proof.ai_decision == "REJECTED"
    assert "automated verification" in proof.verification_rationale
    assert work_item.queue_status == WorkQueueStatusEnum.ASSIGNED
