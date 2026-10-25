
from sqlalchemy import Column, Integer, String, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import EmploymentStatusEnum, GenderEnum


class Employee(Base):
    __tablename__ = "employee"

    employee_id = Column(Integer, primary_key=True)

    department_id = Column(
        Integer,
        ForeignKey("department.department_id")
    )

    name = Column(String(100), nullable=False)

    role = Column(String(100), nullable=False)

    phone = Column(String(10))

    availability = Column(Enum(EmploymentStatusEnum), default=EmploymentStatusEnum.ACTIVE, nullable=False)

    gender = Column(Enum(GenderEnum), nullable=False)

    skill = Column(String(255), nullable=True)

    experience_years = Column(Integer, default=0, server_default="0", nullable=False)

    # Relationships
    department = relationship(
        "Department",
        back_populates="employees"
    )

    worker_memory = relationship(
        "WorkerMemory",
        back_populates="employee",
        uselist=False,
        cascade="all, delete-orphan",
    )

    checkins = relationship(
        "WorkerCheckin",
        back_populates="employee"
    )

    assignments = relationship(
        "TaskAssignment",
        back_populates="employee"
    )

    # ShiftRoster maps to the "shift_scheduler" table, representing scheduler entries
    roster_entries = relationship(
        "ShiftRoster",
        back_populates="employee",
        cascade="all, delete-orphan",
    )
