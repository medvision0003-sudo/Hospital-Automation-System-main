
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.base import Base


class Department(Base):
    __tablename__ = "department"

    department_id = Column(Integer, primary_key=True)

    department_name = Column(String(100), unique=True, nullable=False)

    description = Column(Text)

    # Relationships
    employees = relationship(
        "Employee",
        back_populates="department"
    )

    tasks = relationship(
        "TaskMaster",
        back_populates="department"
    )

    shifts = relationship(
        "Shift",
        back_populates="department",
        cascade="all, delete-orphan",
    )

