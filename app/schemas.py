"""Request/response models. Every field runs through app.validators."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app import validators as v
from app.models import Sex

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)


class _PatientFields(BaseModel):
    """Validation shared by create and update. Unknown keys are rejected so a
    typo like "frist_name" fails loudly instead of being silently dropped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _validate(cls, val, info):
        val = v.blank_to_none(val)  # "" from a form or the LLM means "not given"
        if val is None:
            return None
        return v.FIELD_VALIDATORS[info.field_name](val)


class PatientCreate(_PatientFields):
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @field_validator("preferred_language", mode="after")
    @classmethod
    def _default_language(cls, val):
        return val or "English"


class PatientUpdate(_PatientFields):
    """Partial update: only fields present in the request are changed."""

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    def changes(self) -> dict:
        data = self.model_dump(exclude_unset=True)
        cleared = [f for f in REQUIRED_FIELDS if f in data and data[f] is None]
        if cleared:
            raise ValueError(f"Required fields can't be cleared: {', '.join(cleared)}")
        if "preferred_language" in data and data["preferred_language"] is None:
            data["preferred_language"] = "English"
        return data


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("date_of_birth")
    def _dob(self, d: date) -> str:
        return d.strftime("%m/%d/%Y")  # spec format
