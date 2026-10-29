"""Two fictional demo patients, inserted only when the table is empty."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Patient
from app.schemas import PatientCreate

log = logging.getLogger("app.seed")

SEED_PATIENTS = [
    {
        "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/14/1985",
        "sex": "Female", "phone_number": "(512) 555-0142", "email": "jane.doe@example.com",
        "address_line_1": "1200 Congress Ave", "address_line_2": "Apt 4B",
        "city": "Austin", "state": "TX", "zip_code": "78701",
        "insurance_provider": "Blue Cross Blue Shield", "insurance_member_id": "BCX123456789",
        "emergency_contact_name": "John Doe", "emergency_contact_phone": "512-555-0199",
    },
    {
        "first_name": "Carlos", "last_name": "O'Neil-Garcia", "date_of_birth": "1972-11-02",
        "sex": "Male", "phone_number": "305-555-0177",
        "address_line_1": "88 Biscayne Blvd", "city": "Miami", "state": "Florida",
        "zip_code": "33132", "preferred_language": "Spanish",
    },
]


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Patient)):
        return
    for raw in SEED_PATIENTS:
        db.add(Patient(**PatientCreate(**raw).model_dump()))
    db.commit()
    log.info("Seeded %d demo patients", len(SEED_PATIENTS))
