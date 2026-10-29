"""Database tables.

Constraints here are the last line of defence: the Pydantic schemas already
validate and normalise input, but the DB refuses bad rows even if some future
code path skips the schemas.
"""
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Sex(str, enum.Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE = "Decline to Answer"


# Postgres POSIX regex. [[:alpha:]] is Unicode-aware, so "José" passes.
NAME_RE = r"^[[:alpha:]]+([ '-][[:alpha:]]+)*$"
PHONE_RE = r"^[2-9][0-9]{9}$"


def _sql(s: str) -> str:
    """Quote a Python string as a SQL string literal."""
    return "'" + s.replace("'", "''") + "'"


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, name="sex_enum", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    address_line_1: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)
    insurance_provider: Mapped[str | None] = mapped_column(String(100))
    insurance_member_id: Mapped[str | None] = mapped_column(String(30))
    preferred_language: Mapped[str] = mapped_column(
        String(50), nullable=False, default="English", server_default="English"
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"first_name ~ {_sql(NAME_RE)}", name="ck_first_name"),
        CheckConstraint(f"last_name ~ {_sql(NAME_RE)}", name="ck_last_name"),
        CheckConstraint("date_of_birth <= CURRENT_DATE AND date_of_birth >= DATE '1900-01-01'", name="ck_dob_range"),
        CheckConstraint(f"phone_number ~ '{PHONE_RE}'", name="ck_phone"),
        CheckConstraint(
            f"emergency_contact_phone IS NULL OR emergency_contact_phone ~ '{PHONE_RE}'",
            name="ck_emergency_phone",
        ),
        CheckConstraint("state ~ '^[A-Z]{2}$'", name="ck_state"),
        CheckConstraint(r"zip_code ~ '^[0-9]{5}(-[0-9]{4})?$'", name="ck_zip"),
        CheckConstraint("email IS NULL OR email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'", name="ck_email"),
        CheckConstraint("char_length(city) BETWEEN 1 AND 100", name="ck_city_len"),
        CheckConstraint(
            "insurance_member_id IS NULL OR insurance_member_id ~ '^[A-Z0-9]{1,30}$'",
            name="ck_member_id",
        ),
        # Lookups used by the API filters and returning-caller detection.
        # Phone is deliberately NOT unique: family members often share a number.
        Index("ix_patients_phone", "phone_number"),
        Index("ix_patients_last_name_lower", func.lower(last_name)),
        Index("ix_patients_dob", "date_of_birth"),
    )


class CallLog(Base):
    """One row per phone call, written from Vapi's end-of-call report."""

    __tablename__ = "call_logs"

    call_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), index=True
    )
    caller_number: Mapped[str | None] = mapped_column(String(20))
    ended_reason: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
