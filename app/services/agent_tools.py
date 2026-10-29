"""Handlers for the tools the voice agent can call.

Each handler returns a plain dict that is JSON-encoded and handed back to the
LLM as the tool result. The wording of these results matters: the LLM reads
them and decides what to say, so errors name the exact field and tell the
agent what to do next, instead of returning generic failures.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import validators as v
from app.errors import NotFoundError
from app.models import Patient, Sex
from app.schemas import PatientCreate, PatientUpdate
from app.services import calls as call_svc
from app.services import patients as svc

log = logging.getLogger("app.agent_tools")

SYSTEM_ERROR = {
    "success": False,
    "error_type": "system",
    "message": (
        "The record could not be saved because of a system problem. Apologise, "
        "tell the caller their information was not saved, and offer to try again."
    ),
}


@dataclass
class CallContext:
    call_id: str | None
    caller_number: str | None


# --- helpers -----------------------------------------------------------------

def _field_errors(e: ValidationError) -> list[dict]:
    out = []
    for err in e.errors():
        field = ".".join(str(p) for p in err["loc"]) or None
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "missing":
            msg = "This field is required and was not provided."
        elif err["type"] == "extra_forbidden":
            msg = "Unknown field; do not send it."
        out.append({"field": field, "message": msg})
    return out


def _spoken_date(d: date) -> str:
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")  # "March 4, 1990"


def _spoken(field: str, value) -> str:
    if field in ("phone_number", "emergency_contact_phone"):
        return f"{value[:3]}-{value[3:6]}-{value[6:]}"
    if field == "date_of_birth":
        return _spoken_date(value)
    if field == "state":
        return f"{v.US_STATES[value]} ({value})"
    if isinstance(value, Sex):
        return value.value
    return str(value)


def _summary(p: Patient) -> dict:
    """What the agent may know about an existing patient. DOB is included so
    the agent can verify identity, but the prompt forbids reading it out:
    the caller must say it first."""
    return {
        "patient_id": str(p.patient_id),
        "first_name": p.first_name,
        "last_name": p.last_name,
        "date_of_birth_for_verification": p.date_of_birth.strftime("%m/%d/%Y"),
    }


def _clean_args(args: dict) -> dict:
    # LLMs sometimes send null or "" for fields the caller skipped.
    return {k: val for k, val in args.items() if val not in (None, "")}


# --- tools ---------------------------------------------------------------------

def lookup_patient(db: Session, args: dict, ctx: CallContext) -> dict:
    phone = args.get("phone_number") or ctx.caller_number
    if not phone:
        return {
            "found": False,
            "caller_id_available": False,
            "instruction": (
                "Caller ID is not available on this call, so you do not know the caller's "
                "phone number. If they say 'this number', ask them to say the digits. "
                "Never make up a number."
            ),
        }
    matches = svc.find_by_phone(db, phone)
    if not matches:
        return {"found": False}
    return {
        "found": True,
        "matches": [_summary(p) for p in matches[:3]],
        "instruction": (
            "Tell the caller you may already have a record for the first match by name "
            "and ask if they want to update it instead of registering again. Before "
            "changing anything, ask them to state their date of birth and compare it; "
            "never read the stored date of birth aloud."
        ),
    }


def validate_field(db: Session, args: dict, ctx: CallContext) -> dict:
    field = args.get("field")
    value = args.get("value")
    if field not in v.FIELD_VALIDATORS:
        return {"valid": False, "error": f"Unknown field '{field}'.", "allowed": sorted(v.FIELD_VALIDATORS)}
    if value in (None, ""):
        return {"valid": False, "field": field, "error": "No value was provided."}
    try:
        normalised = v.FIELD_VALIDATORS[field](value)
    except ValueError as e:
        return {"valid": False, "field": field, "error": str(e),
                "instruction": "Explain the problem briefly and ask for this field again."}
    out = normalised.strftime("%m/%d/%Y") if isinstance(normalised, date) else (
        normalised.value if isinstance(normalised, Sex) else normalised)
    result = {"valid": True, "field": field, "normalized": out, "say_back": _spoken(field, normalised)}
    if field == "phone_number":
        # Returning-caller check runs here, server-side, so it never depends on
        # the model remembering to call lookup_patient as a separate step.
        matches = svc.find_by_phone(db, out)
        if matches:
            result["existing_patients"] = [_summary(p) for p in matches[:3]]
            result["instruction"] = (
                "This number already has a patient record. Before continuing, tell the caller "
                "you may already have a record for the first match by name and ask if they want "
                "to update it instead. Verify by asking them to state their date of birth; never "
                "read the stored one aloud."
            )
    return result


def save_patient(db: Session, args: dict, ctx: CallContext) -> dict:
    log.info("save_patient payload call_id=%s data=%s", ctx.call_id, args)
    try:
        data = PatientCreate(**_clean_args(args))
    except ValidationError as e:
        return {
            "success": False,
            "error_type": "validation",
            "errors": _field_errors(e),
            "instruction": "Ask the caller to correct only these fields, then call save_patient again.",
        }
    try:
        # Idempotency: if this call already saved a patient (e.g. the LLM retried
        # after a slow response), update that record instead of duplicating it.
        existing_id = call_svc.patient_for_call(db, ctx.call_id) if ctx.call_id else None
        if existing_id:
            patient = svc.update_patient(db, existing_id, PatientUpdate(**data.model_dump()))
        else:
            patient = svc.create_patient(db, data)
        if ctx.call_id:
            call_svc.link_patient(db, ctx.call_id, patient.patient_id, ctx.caller_number)
    except (SQLAlchemyError, NotFoundError):
        log.exception("save_patient failed call_id=%s", ctx.call_id)
        db.rollback()
        return SYSTEM_ERROR
    log.info("save_patient ok call_id=%s patient_id=%s", ctx.call_id, patient.patient_id)
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name}


def update_patient(db: Session, args: dict, ctx: CallContext) -> dict:
    log.info("update_patient payload call_id=%s data=%s", ctx.call_id, args)
    args = _clean_args(args)
    patient_id = args.pop("patient_id", None)
    if not patient_id:
        return {"success": False, "error_type": "validation",
                "errors": [{"field": "patient_id", "message": "patient_id from lookup_patient is required."}]}
    if not args:
        return {"success": False, "error_type": "validation",
                "errors": [{"field": None, "message": "No fields to update were provided."}]}
    try:
        data = PatientUpdate(**args)
    except ValidationError as e:
        return {"success": False, "error_type": "validation", "errors": _field_errors(e),
                "instruction": "Ask the caller to correct only these fields, then call update_patient again."}
    try:
        pid = uuid.UUID(str(patient_id))
    except ValueError:
        return {"success": False, "error_type": "not_found",
                "message": "That patient_id is not valid. Call lookup_patient again to get it."}
    try:
        patient = svc.update_patient(db, pid, data)
        if ctx.call_id:
            call_svc.link_patient(db, ctx.call_id, patient.patient_id, ctx.caller_number)
    except NotFoundError:
        return {"success": False, "error_type": "not_found",
                "message": "No active patient with that patient_id. Offer to register them as new."}
    except (SQLAlchemyError, ValueError):
        log.exception("update_patient failed call_id=%s", ctx.call_id)
        db.rollback()
        return SYSTEM_ERROR
    log.info("update_patient ok call_id=%s patient_id=%s", ctx.call_id, patient.patient_id)
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name,
            "updated_fields": sorted(args)}


TOOLS = {
    "lookup_patient": lookup_patient,
    "validate_field": validate_field,
    "save_patient": save_patient,
    "update_patient": update_patient,
}
