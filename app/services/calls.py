"""Call log persistence. A row is created as soon as a call saves or updates a
patient (so the transcript can be linked later) and completed when Vapi's
end-of-call report arrives."""
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import CallLog


def link_patient(db: Session, call_id: str, patient_id: uuid.UUID, caller_number: str | None) -> None:
    stmt = insert(CallLog).values(call_id=call_id, patient_id=patient_id, caller_number=caller_number)
    stmt = stmt.on_conflict_do_update(index_elements=[CallLog.call_id], set_={"patient_id": patient_id})
    db.execute(stmt)
    db.commit()


def patient_for_call(db: Session, call_id: str) -> uuid.UUID | None:
    return db.scalar(select(CallLog.patient_id).where(CallLog.call_id == call_id))


def record_end_of_call(
    db: Session,
    call_id: str,
    caller_number: str | None,
    ended_reason: str | None,
    summary: str | None,
    transcript: str | None,
    raw: dict,
) -> None:
    values = dict(
        caller_number=caller_number, ended_reason=ended_reason,
        summary=summary, transcript=transcript, raw=raw,
    )
    stmt = insert(CallLog).values(call_id=call_id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[CallLog.call_id], set_=values)
    db.execute(stmt)
    db.commit()


def calls_for_patient(db: Session, patient_id: uuid.UUID) -> list[CallLog]:
    return list(db.scalars(
        select(CallLog).where(CallLog.patient_id == patient_id).order_by(CallLog.created_at.desc())
    ))




def recent_calls(db: Session, limit: int = 50) -> list[CallLog]:
    return list(db.scalars(select(CallLog).order_by(CallLog.created_at.desc()).limit(limit)))