import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models.agent_table import AgentTable
from app.services.agent_registry_service import AGENT_DEFINITIONS, seed_agent_registry


def test_seed_agent_registry_is_idempotent_and_preserves_expected_ids():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            seed_agent_registry(db)
            seed_agent_registry(db)
            rows = db.query(AgentTable).order_by(AgentTable.agent_id).all()
            assert len(rows) == len(AGENT_DEFINITIONS)
            assert [
                (row.agent_id, row.agent_name)
                for row in rows
            ] == [
                (agent_id, agent_name)
                for agent_id, agent_name, _ in AGENT_DEFINITIONS
            ]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_seed_agent_registry_rejects_conflicting_ids():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(
                AgentTable(
                    agent_id=2,
                    agent_name="WRONG_AGENT",
                    agent_category="WRONG_AGENT",
                )
            )
            db.commit()
            with pytest.raises(RuntimeError, match="Agent ID 2 belongs"):
                seed_agent_registry(db)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
