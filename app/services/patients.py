"""Patient business logic. Both the REST routes and the Vapi tool webhook call
these functions, so validation and persistence behave identically whether a
record arrives over HTTP or over the phone."""
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import validators as v
from app.errors import DomainValidationError, NotFoundError
from app.models import Patient
from app.schemas import PatientCreate, PatientUpdate

log = logging.getLogger("app.patients")


def _active():
    return select(Patient).where(Patient.deleted_at.is_(None))


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.scalar(_active().where(Patient.patient_id == patient_id))
    if patient is None:
        raise NotFoundError()
    return patient


def list_patients(
    db: Session,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    q = _active()
    if last_name:
        q = q.where(func.lower(Patient.last_name) == last_name.strip().lower())
    if date_of_birth:
        q = q.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        q = q.where(Patient.phone_number == phone_number)
    q = q.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(q))


def find_by_phone(db: Session, raw_phone: str) -> list[Patient]:
    """Returning-caller lookup. Returns [] for unparseable numbers instead of
    raising, because caller ID can be withheld or international."""
    try:
        digits = v.phone(raw_phone)
    except ValueError:
        return []
    return list(db.scalars(_active().where(Patient.phone_number == digits).order_by(Patient.created_at.desc())))


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    log.info("patient_created", extra={"patient_id": str(patient.patient_id)})
    return patient


def update_patient(db: Session, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = get_patient(db, patient_id)
    try:
        changes = data.changes()
    except ValueError as e:
        raise DomainValidationError(str(e)) from None
    for field, value in changes.items():
        setattr(patient, field, value)
    patient.updated_at = datetime.now(timezone.utc)  # bump even if values are unchanged
    db.commit()
    db.refresh(patient)
    log.info("patient_updated", extra={"patient_id": str(patient_id), "fields": list(changes)})
    return patient


def soft_delete_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = get_patient(db, patient_id)
    now = datetime.now(timezone.utc)
    patient.deleted_at = now
    patient.updated_at = now
    db.commit()
    log.info("patient_deleted", extra={"patient_id": str(patient_id)})
    return patient
