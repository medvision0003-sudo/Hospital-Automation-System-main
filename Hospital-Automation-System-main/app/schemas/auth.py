from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from typing import Optional
import re

from app.models.enums import UserRoleEnum


# Signup Request

class UserSignUpRequest(BaseModel):
    """Request body for POST /auth/signup."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=128, description="Account password")
    role: UserRoleEnum = Field(..., description="System access role (SUPERVISOR or ADMIN)")
    employee_id_str: Optional[str] = Field(None, description="Optional employee ID string (e.g., EMP-101)")
    department_id: Optional[int] = Field(None, gt=0, description="Optional department association ID")
    department_name: Optional[str] = Field(None, description="Optional department name association")
    admin_id: Optional[str] = Field(None, description="Optional admin access key / identifier")

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """Enforce password complexity rules."""
        errors = []
        if not re.search(r"[A-Z]", v):
            errors.append("one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("one lowercase letter")
        if not re.search(r"[0-9]", v):
            errors.append("one digit")
        if not re.search(r"[@$!%*?&]", v):
            errors.append("one special character (@$!%*?&)")
        if errors:
            raise ValueError(
                "Password must contain at least "
                + ", ".join(errors) + "."
            )
        return v


# Login Request

class UserLoginRequest(BaseModel):
    """Request body for POST /auth/login."""
    username: str = Field(..., description="Email, employee ID string, or admin access key")
    password: str = Field(..., min_length=1, description="Account password")


# Token Response

class TokenResponse(BaseModel):
    """Response body returned after successful login."""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    email: str
    employee_id: Optional[int] = None
    admin_id: Optional[str] = None
    department_id: Optional[int] = None


# User Response

class UserResponse(BaseModel):
    """Public user profile response for GET /auth/me."""
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    role: str
    employee_id: Optional[int] = None
    admin_id: Optional[str] = None
    department_id: Optional[int] = None
    is_active: bool
