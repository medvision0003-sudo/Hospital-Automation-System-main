from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.agent_table import AgentTable
from app.schemas.agent_table import AgentTableCreate, AgentTableResponse

router = APIRouter(prefix="/agents", tags=["Admin - Agents"])


@router.post("/", response_model=AgentTableResponse, status_code=201)
def create_agent(agent_data: AgentTableCreate, db: Session = Depends(get_db)):
    new_agent = AgentTable(**agent_data.model_dump())
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    return new_agent
