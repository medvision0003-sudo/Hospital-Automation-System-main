import logging
from sqlalchemy import text, inspect

logger = logging.getLogger(__name__)


def run_migrations(engine):
    """Safely add missing columns to existing tables and backfill historical data.

    Supports both PostgreSQL and SQLite dialects.
    Skips columns that already exist to support idempotent restarts.
    """
    inspector = inspect(engine)
    dialect = engine.dialect.name

    _migrate_agent_action_log(engine, inspector, dialect)
    _migrate_orchestrator_trace(engine, inspector)
    _migrate_users(engine, inspector, dialect)
    _migrate_employee_experience(engine, inspector)
    _migrate_staff_automation_rules(engine, inspector)
    _migrate_task_proof(engine, inspector, dialect)
    _migrate_task_master(engine, inspector, dialect)
    _migrate_department_work_queue(engine, inspector)


def _migrate_task_master(engine, inspector, dialect):
    """Add task role and proof requirements while preserving existing templates."""
    if not inspector.has_table("task_master"):
        return
    existing = {col["name"] for col in inspector.get_columns("task_master")}
    missing_columns = []
    if "required_role" not in existing:
        missing_columns.append("ALTER TABLE task_master ADD COLUMN required_role VARCHAR(100)")
    if "requires_proof" not in existing:
        default = "FALSE" if dialect == "postgresql" else "0"
        missing_columns.append(
            "ALTER TABLE task_master ADD COLUMN requires_proof "
            f"BOOLEAN NOT NULL DEFAULT {default}"
        )
    if "suggested_start_time" not in existing:
        missing_columns.append(
            "ALTER TABLE task_master ADD COLUMN suggested_start_time TIME"
        )
    if "due_time" not in existing:
        missing_columns.append("ALTER TABLE task_master ADD COLUMN due_time TIME")
    if missing_columns:
        with engine.begin() as conn:
            for statement in missing_columns:
                conn.execute(text(statement))
        for column in (
            "required_role",
            "requires_proof",
            "suggested_start_time",
            "due_time",
        ):
            if column not in existing:
                logger.info("Added column task_master.%s", column)


def _migrate_department_work_queue(engine, inspector):
    """Persist the shift context for generated work without rewriting history."""
    if not inspector.has_table("department_work_queue"):
        return
    existing = {
        col["name"] for col in inspector.get_columns("department_work_queue")
    }
    if "shift_id" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE department_work_queue ADD COLUMN shift_id "
                "INTEGER REFERENCES shift(shift_id)"
            ))
        logger.info("Added column department_work_queue.shift_id")


def _migrate_agent_action_log(engine, inspector, dialect):
    """Add resolution tracking columns to agent_action_log and backfill old resolved rows."""
    existing = {col["name"] for col in inspector.get_columns("agent_action_log")}

    # Use dialect-appropriate boolean default
    bool_default = "DEFAULT FALSE" if dialect == "postgresql" else "DEFAULT 0"
    bool_true = "TRUE" if dialect == "postgresql" else "1"
    bool_false = "FALSE" if dialect == "postgresql" else "0"
    ts_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    new_columns = [
        ("is_resolved", f"BOOLEAN {bool_default} NOT NULL"),
        ("resolved_at", ts_type),
        ("supervisor_id", "INTEGER"),
        ("supervisor_notes", "TEXT"),
        ("resolution_action", "TEXT"),
        ("workflow_id", "VARCHAR(36)"),
    ]

    with engine.begin() as conn:
        for col_name, col_def in new_columns:
            if col_name not in existing:
                stmt = f"ALTER TABLE agent_action_log ADD COLUMN {col_name} {col_def}"
                conn.execute(text(stmt))
                logger.info("Added column agent_action_log.%s", col_name)

        # Backfill: mark old escalation rows that were previously resolved via string markers
        conn.execute(text(
            f"UPDATE agent_action_log SET is_resolved = {bool_true} "
            f"WHERE is_resolved = {bool_false} "
            "AND ("
            "  action_type IN ('ESCALATION', 'PROOF_REVIEW_REQUIRED') "
            "  OR decision_summary LIKE '%HUMAN_REVIEW_REQUIRED%' "
            ") "
            "AND ("
            "  decision_summary LIKE '%[RESOLVED%' "
            "  OR execution_status = 'SUCCESS' "
            ")"
        ))
        logger.info("Backfilled agent_action_log.is_resolved for historical rows")


def _migrate_orchestrator_trace(engine, inspector):
    """Add paused workflow state columns if they do not exist yet."""
    if not inspector.has_table("orchestrator_trace"):
        return
    existing = {col["name"] for col in inspector.get_columns("orchestrator_trace")}

    new_columns = [
        ("remaining_steps_json", "TEXT"),
        ("context_state_json", "TEXT"),
    ]

    with engine.begin() as conn:
        for col_name, col_def in new_columns:
            if col_name not in existing:
                stmt = f"ALTER TABLE orchestrator_trace ADD COLUMN {col_name} {col_def}"
                conn.execute(text(stmt))
                logger.info("Added column orchestrator_trace.%s", col_name)


def _migrate_users(engine, inspector, dialect):
    """Add admin_id column to users if it doesn't exist."""
    if not inspector.has_table("users"):
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    if "admin_id" not in existing:
        with engine.begin() as conn:
            # SQLite does not support ADD COLUMN UNIQUE directly in ALTER TABLE.
            # We add it as a normal VARCHAR column and optionally add UNIQUE for PG.
            col_def = "VARCHAR(100) UNIQUE" if dialect == "postgresql" else "VARCHAR(100)"
            stmt = f"ALTER TABLE users ADD COLUMN admin_id {col_def}"
            conn.execute(text(stmt))
            logger.info("Added column users.admin_id")


def _migrate_employee_experience(engine, inspector):
    """Add experience_years column to employee if it doesn't exist."""
    if not inspector.has_table("employee"):
        return
    existing = {col["name"] for col in inspector.get_columns("employee")}
    if "experience_years" not in existing:
        with engine.begin() as conn:
            stmt = "ALTER TABLE employee ADD COLUMN experience_years INTEGER DEFAULT 0 NOT NULL"
            conn.execute(text(stmt))
            logger.info("Added column employee.experience_years")


def _migrate_staff_automation_rules(engine, inspector):
    """Add the approval-time employee identity to existing learned-rule tables."""
    if not inspector.has_table("automation_rule"):
        return
    existing = {col["name"] for col in inspector.get_columns("automation_rule")}
    if "approved_employee_id" not in existing:
        with engine.begin() as conn:
            stmt = (
                "ALTER TABLE automation_rule ADD COLUMN approved_employee_id "
                "INTEGER REFERENCES employee(employee_id)"
            )
            conn.execute(text(stmt))
            logger.info("Added column automation_rule.approved_employee_id")


def _migrate_task_proof(engine, inspector, dialect):
    """Add AI and reviewer metadata without replacing existing proof records."""
    if not inspector.has_table("task_proof"):
        return

    existing = {col["name"] for col in inspector.get_columns("task_proof")}
    timestamp_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    columns = [
        ("employee_id", "INTEGER REFERENCES employee(employee_id)"),
        ("ai_decision", "VARCHAR(30)"),
        ("verification_attempts", "INTEGER NOT NULL DEFAULT 1"),
        ("verified_at", timestamp_type),
        ("reviewer_user_id", "INTEGER REFERENCES users(user_id)"),
    ]
    with engine.begin() as conn:
        for name, definition in columns:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE task_proof ADD COLUMN {name} {definition}"))
                logger.info("Added column task_proof.%s", name)
