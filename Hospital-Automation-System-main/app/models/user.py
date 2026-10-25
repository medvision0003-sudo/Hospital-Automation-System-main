from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import UserRoleEnum


class User(Base):
    """Stores authenticated user accounts for system access.

    System access role (User.role) is decoupled from hospital job role
    (Employee.role). Only SUPERVISOR and ADMIN roles are permitted.
    The employee_id link is optional and nullable-unique: multiple NULL
    values are allowed, but non-null employee links must be unique.
    """
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)

    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id"),
        nullable=True,
        unique=True,
    )

    admin_id = Column(String(100), unique=True, nullable=True)

    email = Column(String(255), unique=True, index=True, nullable=False)

    hashed_password = Column(String(255), nullable=False)

    role = Column(
        Enum(UserRoleEnum),
        nullable=False,
    )

    department_id = Column(
        Integer,
        ForeignKey("department.department_id"),
        nullable=True,
    )

    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    employee = relationship("Employee", backref="user_account", uselist=False)
    department = relationship("Department", backref="user_accounts")
