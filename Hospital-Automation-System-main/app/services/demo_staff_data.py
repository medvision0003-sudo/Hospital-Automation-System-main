"""Seed clearly labeled development-only staff and roster data."""

import logging
import os
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.enums import EmploymentStatusEnum, GenderEnum, RosterStatusEnum
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.services.staff_task_library import TASK_LIBRARY

logger = logging.getLogger(__name__)

_INITIAL_DEMO_STAFF = (
    {
        "name": "Demo Asha Mehta",
        "department": "Nursing",
        "role": "NURSE",
        "skill": "VITAL_SIGNS",
        "experience_years": 6,
        "gender": GenderEnum.FEMALE,
    },
    {
        "name": "Demo Daniel Okafor",
        "department": "Ward",
        "role": "WARD STAFF",
        "skill": "WARD_INSPECTION",
        "experience_years": 4,
        "gender": GenderEnum.MALE,
    },
    {
        "name": "Demo Priya Nair",
        "department": "Pharmacy",
        "role": "PHARMACIST",
        "skill": "INVENTORY_CONTROL",
        "experience_years": 8,
        "gender": GenderEnum.FEMALE,
    },
    {
        "name": "Demo Miguel Santos",
        "department": "Laboratory",
        "role": "LAB TECHNICIAN",
        "skill": "SPECIMEN_LABELING",
        "experience_years": 5,
        "gender": GenderEnum.MALE,
    },
    {
        "name": "Demo Grace Kim",
        "department": "Reception",
        "role": "RECEPTIONIST",
        "skill": "PATIENT_REGISTRATION",
        "experience_years": 3,
        "gender": GenderEnum.FEMALE,
    },
    {
        "name": "Demo Samuel Patel",
        "department": "Housekeeping",
        "role": "HOUSEKEEPER",
        "skill": "HOSPITAL_CLEANING",
        "experience_years": 7,
        "gender": GenderEnum.MALE,
    },
)

_EXTRA_DEMO_NAMES = (
    "Amara Okoye", "Noah Bennett", "Leila Haddad", "Ethan Brooks", "Sofia Alvarez",
    "Arjun Kapoor", "Maya Thompson", "Daniel Mensah", "Iris Chen", "Omar Farouk",
    "Zoe Williams", "Mateo Rivera", "Priya Shah", "Lucas Martin", "Nia Johnson",
    "Ravi Desai", "Elena Petrova", "Samuel Green", "Amina Yusuf", "Theo Clarke",
    "Hana Suzuki", "David Mwangi", "Mila Novak", "Isaac Turner", "Fatima Rahman",
    "Gabriel Costa", "Anika Bose", "Caleb Foster", "Lina Haddad", "Joseph Kim",
    "Sara Lindholm", "Adrian Flores", "Mei Lin", "Peter Osei", "Nora Campbell",
    "Kofi Boateng", "Eva Schmidt", "Yusuf Ali", "Chloe Morgan", "Rohan Malhotra",
    "Layla Hassan", "Benjamin Scott", "Asha Iyer", "Marcus Hill", "Yuna Park",
    "Tariq Mahmoud", "Grace Edwards", "Emmanuel Diallo", "Clara Rossi", "Dev Patel",
)
_EXTRA_DEMO_DEPARTMENTS = (
    ("Nursing",) * 13
    + ("Ward",) * 9
    + ("Pharmacy",) * 7
    + ("Laboratory",) * 7
    + ("Reception",) * 7
    + ("Housekeeping",) * 7
)


def _all_demo_staff() -> tuple[dict, ...]:
    templates_by_department: dict[str, list[dict]] = {}
    for template in TASK_LIBRARY:
        templates_by_department.setdefault(template["department"], []).append(template)

    extras = []
    for index, (name, department) in enumerate(
        zip(_EXTRA_DEMO_NAMES, _EXTRA_DEMO_DEPARTMENTS)
    ):
        templates = templates_by_department[department]
        extras.append({
            "name": f"Demo {name}",
            "department": department,
            "role": templates[0]["required_role"],
            "skill": ",".join(sorted({
                template["required_skill"] for template in templates
                if template.get("required_skill")
            })),
            "experience_years": 1 + (index * 3) % 18,
            "gender": GenderEnum.FEMALE if index % 2 == 0 else GenderEnum.MALE,
        })
    return tuple(_INITIAL_DEMO_STAFF) + tuple(extras)


DEMO_STAFF = _all_demo_staff()

_SHIFT_TIMES = {
    "Demo Morning": (time(7, 0), time(15, 0)),
    "Demo Evening": (time(15, 0), time(23, 0)),
    "Demo Night": (time(23, 0), time(7, 0)),
}


def _current_demo_shift_name(now: datetime) -> str:
    current_time = now.time()
    if time(7, 0) <= current_time < time(15, 0):
        return "Demo Morning"
    if time(15, 0) <= current_time < time(23, 0):
        return "Demo Evening"
    return "Demo Night"


def demo_staff_data_enabled() -> bool:
    """Enable sample staff only for non-production deployments by default."""
    if os.getenv("APP_ENV", "development").strip().lower() == "production":
        return False
    enabled = os.getenv("DEMO_DATA_ENABLED")
    if enabled is not None:
        return enabled.strip().lower() in {"1", "true", "yes", "on"}
    return True


def seed_demo_staff_data(db: Session, start_date: date | None = None) -> dict[str, int]:
    """Idempotently add demo staff, two shifts, and a week of scheduled rosters."""
    now = datetime.now()
    first_day = start_date or now.date()
    today = date.today()
    departments = {
        department.department_name.casefold(): department
        for department in db.query(Department).all()
    }
    shifts: dict[tuple[int, str], Shift] = {}
    for staff in DEMO_STAFF:
        department = departments.get(staff["department"].casefold())
        if department is None:
            logger.warning(
                "Skipping demo staff for missing department %s",
                staff["department"],
            )
            continue
        for shift_name, (start_time, end_time) in _SHIFT_TIMES.items():
            shift = (
                db.query(Shift)
                .filter(
                    Shift.department_id == department.department_id,
                    Shift.shift_name == shift_name,
                )
                .first()
            )
            if shift is None:
                shift = Shift(
                    department_id=department.department_id,
                    shift_name=shift_name,
                    start_time=start_time,
                    end_time=end_time,
                )
                db.add(shift)
                db.flush()
            shifts[(department.department_id, shift_name)] = shift

    employees_created = 0
    rosters_created = 0
    employees_available = 0
    for staff in DEMO_STAFF:
        department = departments.get(staff["department"].casefold())
        if department is None:
            continue
        department_templates = [
            template for template in TASK_LIBRARY
            if template["department"].casefold() == staff["department"].casefold()
            and template["required_role"] == staff["role"]
            and template.get("required_skill")
        ]
        skills = ",".join(sorted({
            template["required_skill"] for template in department_templates
        }))
        employee = (
            db.query(Employee)
            .filter(
                Employee.department_id == department.department_id,
                Employee.name == staff["name"],
            )
            .first()
        )
        if employee is None:
            employee = Employee(
                department_id=department.department_id,
                name=staff["name"],
                role=staff["role"],
                skill=skills or staff["skill"],
                experience_years=staff["experience_years"],
                availability=EmploymentStatusEnum.ACTIVE,
                gender=staff["gender"],
            )
            db.add(employee)
            db.flush()
            employees_created += 1
        else:
            employee.role = staff["role"]
            employee.skill = skills or staff["skill"]
            employee.experience_years = staff["experience_years"]
            employee.availability = EmploymentStatusEnum.ACTIVE
            employee.gender = staff["gender"]
        employees_available += 1

        for day_offset in range(7):
            roster_date = first_day + timedelta(days=day_offset)
            shift_name = (
                _current_demo_shift_name(now)
                if roster_date == today
                else "Demo Morning" if day_offset % 2 == 0 else "Demo Evening"
            )
            shift = shifts[(department.department_id, shift_name)]
            existing_rosters = (
                db.query(ShiftRoster)
                .join(Shift, ShiftRoster.shift_id == Shift.shift_id)
                .filter(
                    ShiftRoster.employee_id == employee.employee_id,
                    ShiftRoster.work_date == roster_date,
                )
                .all()
            )
            roster = next(
                (entry for entry in existing_rosters if entry.shift.shift_name.startswith("Demo ")),
                None,
            )
            if not existing_rosters:
                db.add(ShiftRoster(
                    employee_id=employee.employee_id,
                    shift_id=shift.shift_id,
                    work_date=roster_date,
                    roster_status=RosterStatusEnum.SCHEDULED,
                ))
                rosters_created += 1
            elif roster is not None and (
                roster_date == today
                and roster.roster_status in (
                    RosterStatusEnum.SCHEDULED,
                    RosterStatusEnum.ABSENT,
                )
            ):
                roster.shift_id = shift.shift_id

    db.commit()
    result = {
        "employees_created": employees_created,
        "employees_available": employees_available,
        "rosters_created": rosters_created,
    }
    logger.info("Development demo staff data seeded: %s", result)
    return result
