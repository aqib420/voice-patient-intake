"""Tests run against a real Postgres (the CHECK constraints and regexes are
Postgres-specific). Point TEST_DATABASE_URL at a throwaway database; every
test starts from empty tables."""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/patients_test"
)
os.environ["SEED_DATA"] = "false"
os.environ["VAPI_WEBHOOK_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def valid_patient():
    return {
        "first_name": "Maria",
        "last_name": "Davis",
        "date_of_birth": "07/04/1990",
        "sex": "female",
        "phone_number": "(415) 555-0123",
        "address_line_1": "500 Market St",
        "city": "San Francisco",
        "state": "California",
        "zip_code": "94105",
    }
