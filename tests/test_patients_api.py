import uuid
from datetime import date, timedelta


def _create(client, body):
    r = client.post("/patients", json=body)
    assert r.status_code == 201, r.json()
    return r.json()["data"]


# --- create -----------------------------------------------------------------

def test_create_normalises_and_returns_envelope(client, valid_patient):
    r = client.post("/patients", json=valid_patient)
    assert r.status_code == 201
    body = r.json()
    assert body["error"] is None
    p = body["data"]
    uuid.UUID(p["patient_id"])
    assert p["phone_number"] == "4155550123"
    assert p["state"] == "CA"
    assert p["sex"] == "Female"
    assert p["date_of_birth"] == "07/04/1990"
    assert p["preferred_language"] == "English"
    assert p["created_at"] and p["updated_at"]


def test_create_missing_required_field_is_422(client, valid_patient):
    del valid_patient["last_name"]
    r = client.post("/patients", json=valid_patient)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert any(d["field"] == "last_name" for d in err["details"])


def test_future_dob_rejected(client, valid_patient):
    valid_patient["date_of_birth"] = (date.today() + timedelta(days=1)).strftime("%m/%d/%Y")
    r = client.post("/patients", json=valid_patient)
    assert r.status_code == 422
    assert "future" in r.json()["error"]["details"][0]["message"]


def test_impossible_dob_rejected(client, valid_patient):
    valid_patient["date_of_birth"] = "02/30/1990"
    assert client.post("/patients", json=valid_patient).status_code == 422


def test_short_phone_rejected(client, valid_patient):
    valid_patient["phone_number"] = "555"
    r = client.post("/patients", json=valid_patient)
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "phone_number"


def test_bad_state_zip_email_name(client, valid_patient):
    for field, bad in [("state", "ZZ"), ("zip_code", "1234"), ("email", "not-an-email"),
                       ("first_name", "R2D2"), ("sex", "banana")]:
        body = {**valid_patient, field: bad}
        r = client.post("/patients", json=body)
        assert r.status_code == 422, (field, r.json())


def test_names_with_hyphen_apostrophe_accent_ok(client, valid_patient):
    valid_patient.update(first_name="José", last_name="O'Brien-Smith")
    assert _create(client, valid_patient)["last_name"] == "O'Brien-Smith"


def test_unknown_field_rejected(client, valid_patient):
    valid_patient["frist_name"] = "x"
    assert client.post("/patients", json=valid_patient).status_code == 422


def test_malformed_json_is_400(client):
    r = client.post("/patients", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["data"] is None


def test_zip_plus_four_normalised(client, valid_patient):
    valid_patient["zip_code"] = "941051234"
    assert _create(client, valid_patient)["zip_code"] == "94105-1234"


# --- read / filter ----------------------------------------------------------

def test_get_by_id_and_404(client, valid_patient):
    p = _create(client, valid_patient)
    assert client.get(f"/patients/{p['patient_id']}").json()["data"]["first_name"] == "Maria"
    r = client.get(f"/patients/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_invalid_uuid_is_422(client):
    assert client.get("/patients/not-a-uuid").status_code == 422


def test_list_filters(client, valid_patient):
    _create(client, valid_patient)
    _create(client, {**valid_patient, "last_name": "Smith", "phone_number": "2125550100",
                     "date_of_birth": "1980-01-01"})
    assert len(client.get("/patients").json()["data"]) == 2
    assert len(client.get("/patients?last_name=davis").json()["data"]) == 1
    assert len(client.get("/patients?phone_number=212-555-0100").json()["data"]) == 1
    assert len(client.get("/patients?date_of_birth=01/01/1980").json()["data"]) == 1
    assert len(client.get("/patients?date_of_birth=1990-07-04").json()["data"]) == 1
    assert client.get("/patients?phone_number=12").status_code == 422


# --- update -----------------------------------------------------------------

def test_partial_update(client, valid_patient):
    p = _create(client, valid_patient)
    r = client.put(f"/patients/{p['patient_id']}", json={"last_name": "Davies", "city": "Oakland"})
    assert r.status_code == 200
    u = r.json()["data"]
    assert (u["last_name"], u["city"], u["first_name"]) == ("Davies", "Oakland", "Maria")
    assert u["updated_at"] > p["updated_at"]


def test_update_cannot_clear_required(client, valid_patient):
    p = _create(client, valid_patient)
    r = client.put(f"/patients/{p['patient_id']}", json={"first_name": None})
    assert r.status_code == 422


def test_update_validates(client, valid_patient):
    p = _create(client, valid_patient)
    assert client.put(f"/patients/{p['patient_id']}", json={"zip_code": "abc"}).status_code == 422


# --- soft delete ------------------------------------------------------------

def test_soft_delete_hides_record(client, valid_patient):
    p = _create(client, valid_patient)
    r = client.delete(f"/patients/{p['patient_id']}")
    assert r.status_code == 200 and r.json()["data"]["deleted_at"]
    assert client.get(f"/patients/{p['patient_id']}").status_code == 404
    assert client.get("/patients").json()["data"] == []
    assert client.delete(f"/patients/{p['patient_id']}").status_code == 404


def test_soft_delete_keeps_row(client, valid_patient):
    from sqlalchemy import text
    from app.db import engine
    p = _create(client, valid_patient)
    client.delete(f"/patients/{p['patient_id']}")
    with engine.connect() as c:
        n = c.execute(text("select count(*) from patients where deleted_at is not null")).scalar()
    assert n == 1


# --- DB constraint is a real backstop ---------------------------------------

def test_db_rejects_bad_row_even_without_schema():
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.db import engine
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text(
                "insert into patients (patient_id, first_name, last_name, date_of_birth, sex, "
                "phone_number, address_line_1, city, state, zip_code) values "
                "(gen_random_uuid(), 'A', 'B', '2999-01-01', 'Male', '4155550123', 'x', 'y', 'CA', '94105')"
            ))
