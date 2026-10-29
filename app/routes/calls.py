"""Read-only access to call transcripts linked to patients."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ok
from app.services import calls as call_svc
from app.services import patients as svc

router = APIRouter(tags=["calls"])


def _call_out(c) -> dict:
    return {
        "call_id": c.call_id,
        "patient_id": c.patient_id,
        "caller_number": c.caller_number,
        "ended_reason": c.ended_reason,
        "summary": c.summary,
        "transcript": c.transcript,
        "created_at": c.created_at,
    }


@router.get("/calls")
def recent_calls(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Most recent calls, including ones that ended without saving a patient."""
    return ok([_call_out(c) for c in call_svc.recent_calls(db, limit)])


@router.get("/patients/{patient_id}/calls")
def patient_calls(patient_id: uuid.UUID, db: Session = Depends(get_db)):
    svc.get_patient(db, patient_id)  # 404 if missing or deleted
    return ok([_call_out(c) for c in call_svc.calls_for_patient(db, patient_id)])
