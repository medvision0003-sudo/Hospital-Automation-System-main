from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.connection import get_db
from app.models.department import Department
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentResponse

router = APIRouter(prefix="/departments", tags=["Admin - Departments"])


@router.post("/", response_model=DepartmentResponse, status_code=201)
def create_department(department_data: DepartmentCreate, db: Session = Depends(get_db)):
    new_department = Department(**department_data.model_dump())
    db.add(new_department)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Department already exists")
    db.refresh(new_department)
    return new_department


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(department_id: int, department_data: DepartmentUpdate, db: Session = Depends(get_db)):
    department = db.query(Department).filter(
        Department.department_id == department_id
    ).first()

    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    update_fields = department_data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        setattr(department, key, value)

    db.commit()
    db.refresh(department)
    return department


@router.delete("/{department_id}", status_code=200)
def delete_department(department_id: int, db: Session = Depends(get_db)):
    department = db.query(Department).filter(
        Department.department_id == department_id
    ).first()

    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    db.delete(department)
    db.commit()
    return {"message": f"Department {department_id} deleted successfully"}
