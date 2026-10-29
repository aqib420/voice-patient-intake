import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import validators as v
from app.db import get_db
from app.errors import DomainValidationError, ok
from app.schemas import PatientCreate, PatientOut, PatientUpdate
from app.services import patients as svc

router = APIRouter(prefix="/patients", tags=["patients"])


def _out(p) -> dict:
    return PatientOut.model_validate(p).model_dump(mode="json")


@router.get("")
def list_patients(
    last_name: str | None = Query(None, max_length=50),
    date_of_birth: str | None = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: str | None = Query(None, description="Any format; digits are extracted"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    dob = phone = None
    try:
        if date_of_birth:
            dob = v.date_of_birth(date_of_birth)
        if phone_number:
            phone = v.phone(phone_number)
    except ValueError as e:
        field = "date_of_birth" if date_of_birth and dob is None else "phone_number"
        raise DomainValidationError("Invalid query parameter.", [{"field": field, "message": str(e)}]) from None
    rows = svc.list_patients(db, last_name, dob, phone, limit, offset)
    return ok([_out(p) for p in rows])


@router.get("/{patient_id}")
def get_patient(patient_id: uuid.UUID, db: Session = Depends(get_db)):
    return ok(_out(svc.get_patient(db, patient_id)))


@router.post("", status_code=201)
def create_patient(body: PatientCreate, db: Session = Depends(get_db)):
    return ok(_out(svc.create_patient(db, body)), status_code=201)


@router.put("/{patient_id}")
def update_patient(patient_id: uuid.UUID, body: PatientUpdate, db: Session = Depends(get_db)):
    return ok(_out(svc.update_patient(db, patient_id, body)))


@router.delete("/{patient_id}")
def delete_patient(patient_id: uuid.UUID, db: Session = Depends(get_db)):
    p = svc.soft_delete_patient(db, patient_id)
    return ok({"patient_id": p.patient_id, "deleted_at": p.deleted_at})
