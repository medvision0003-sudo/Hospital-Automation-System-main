from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user import User
from app.models.employee import Employee
from app.models.department import Department
from app.models.enums import UserRoleEnum
from app.schemas.auth import (
    UserSignUpRequest,
    UserLoginRequest,
    TokenResponse,
    UserResponse,
)
from app.core.security import hash_password, verify_password, create_access_token
from app.core.dependencies import get_current_user, require_roles

router = APIRouter(prefix="/auth", tags=["Authentication"])


from app.models.event_log import EventLog


@router.post("/signup", response_model=UserResponse, status_code=201)
def signup(data: UserSignUpRequest, db: Session = Depends(get_db)):
    """Register a new SUPERVISOR or ADMIN user account.

    Validates:
    - Email uniqueness.
    - For SUPERVISOR: Parses employee_id_str, validates existence and uniqueness.
    - For ADMIN: Validates presence and uniqueness of admin_id.
    - Resolves department_id from department_name if necessary.
    """
    # Normalize email to lowercase
    email = str(data.email).strip().lower()

    # Check email uniqueness
    existing_email = db.query(User).filter(User.email == email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    resolved_employee_id = None
    resolved_department_id = data.department_id

    # 1. Handle Role Specific Validations
    if data.role == UserRoleEnum.SUPERVISOR:
        if not data.employee_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee ID is required for Supervisor registration",
            )
        
        # Clean employee_id_str by keeping only digits
        digits_only = "".join(filter(str.isdigit, data.employee_id_str))
        if not digits_only:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee ID must contain numeric digits (e.g. EMP-101)",
            )
        resolved_employee_id = int(digits_only)

        # Validate employee exists
        employee = db.query(Employee).filter(
            Employee.employee_id == resolved_employee_id
        ).first()
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee with ID {resolved_employee_id} does not exist",
            )

        # Validate employee is not already linked
        existing_link = db.query(User).filter(
            User.employee_id == resolved_employee_id
        ).first()
        if existing_link:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This Employee ID is already linked to another user account",
            )

        # Resolve department from name if not provided by ID
        if resolved_department_id is None and data.department_name:
            dept = db.query(Department).filter(
                Department.department_name.ilike(data.department_name.strip())
            ).first()
            if dept:
                resolved_department_id = dept.department_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Department '{data.department_name}' does not exist",
                )

    elif data.role == UserRoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account creation via registration is disabled",
        )

    # Set is_active based on role: Supervisors require Admin approval (is_active=False)
    is_active_flag = True if data.role == UserRoleEnum.ADMIN else False

    new_user = User(
        email=email,
        hashed_password=hash_password(data.password),
        role=data.role,
        employee_id=resolved_employee_id,
        admin_id=data.admin_id.strip() if data.admin_id else None,
        department_id=resolved_department_id,
        is_active=is_active_flag,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    try:
        event = EventLog(
            event_log=f"Supervisor Registration Request: {data.email} (Emp ID: {resolved_employee_id})",
            source_module="AUTH",
            employee_id=resolved_employee_id,
        )
        db.add(event)
        db.commit()
    except Exception:
        db.rollback()

    return new_user


@router.post("/login", response_model=TokenResponse)
def login(data: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate a user via email, employee ID (e.g. EMP-101), or admin ID."""
    user = None
    input_username = data.username.strip()

    # 1. Try email lookup if contains '@'
    if "@" in input_username:
        input_username = input_username.lower()
        user = db.query(User).filter(User.email == input_username).first()

    # 2. Try exact admin ID lookup first
    if not user:
        user = db.query(User).filter(User.admin_id == input_username).first()

    # 3. Try employee ID lookup (clean any "EMP-" or non-digit prefix)
    if not user and not input_username.upper().startswith("ADMIN"):
        digits_only = "".join(filter(str.isdigit, input_username))
        if digits_only:
            parsed_emp_id = int(digits_only)
            user = db.query(User).filter(User.employee_id == parsed_emp_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supervisor account is pending Admin approval. Please contact an Administrator.",
        )
    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token = create_access_token(user.user_id, user.role.value)

    return TokenResponse(
        access_token=access_token,
        user_id=user.user_id,
        role=user.role.value,
        email=user.email,
        employee_id=user.employee_id,
        admin_id=user.admin_id,
        department_id=user.department_id,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user


@router.get("/pending-supervisors", dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))])
def get_pending_supervisors(db: Session = Depends(get_db)):
    """List all supervisor registration requests pending admin approval."""
    pending_users = db.query(User).filter(
        User.role == UserRoleEnum.SUPERVISOR,
        User.is_active == False
    ).all()
    
    res = []
    for u in pending_users:
        dept_name = u.department.department_name if u.department else None
        emp_name = u.employee.name if u.employee else None
        res.append({
            "user_id": u.user_id,
            "email": u.email,
            "employee_id": u.employee_id,
            "employee_name": emp_name,
            "department_id": u.department_id,
            "department_name": dept_name,
            "role": u.role.value,
            "status": "PENDING_APPROVAL"
        })
    return res


@router.post("/approve-supervisor/{user_id}", dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))])
def approve_supervisor(user_id: int, db: Session = Depends(get_db)):
    """Approve a supervisor user account."""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    try:
        event = EventLog(
            event_log=f"Supervisor Approved: {user.email}"[:255],
            source_module="AUTH",
            employee_id=user.employee_id,
        )
        db.add(event)
    except Exception:
        pass
    db.commit()
    return {"message": f"Supervisor {user.email} approved successfully", "user_id": user_id}


@router.post("/reject-supervisor/{user_id}", dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))])
def reject_supervisor(user_id: int, db: Session = Depends(get_db)):
    """Reject and remove a pending supervisor account."""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        event = EventLog(
            event_log=f"Supervisor Rejected: {user.email}"[:255],
            source_module="AUTH",
            employee_id=user.employee_id,
        )
        db.add(event)
    except Exception:
        pass
    db.delete(user)
    db.commit()
    return {"message": f"Supervisor {user.email} registration rejected", "user_id": user_id}


@router.get("/departments")
def get_auth_departments(db: Session = Depends(get_db)):
    """Fetch department list for registration (unauthenticated)."""
    return [
        {"department_id": d.department_id, "department_name": d.department_name}
        for d in db.query(Department).all()
    ]

