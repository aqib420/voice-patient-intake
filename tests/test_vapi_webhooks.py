"""Simulates the payloads Vapi sends, so the voice integration is tested
without placing a phone call."""
import json
from datetime import date, timedelta

AUTH = {"X-Vapi-Secret": "test-secret"}
CALLER = "+14155550123"


def tool_call(name, args, call_id="call-1", tool_id="tc-1", caller=CALLER):
    return {"message": {
        "type": "tool-calls",
        "call": {"id": call_id, "customer": {"number": caller}},
        "toolCallList": [{"id": tool_id, "type": "function",
                          "function": {"name": name, "arguments": args}}],
    }}


def run(client, name, args, **kw):
    r = client.post("/vapi/tools", json=tool_call(name, args, **kw), headers=AUTH)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["toolCallId"] == kw.get("tool_id", "tc-1")
    return json.loads(res["result"]) if "result" in res else res


SPOKEN_PATIENT = {
    "first_name": "Maria", "last_name": "Davis", "date_of_birth": "07/04/1990",
    "sex": "Female", "phone_number": "415 555 0123", "address_line_1": "500 Market St",
    "city": "San Francisco", "state": "California", "zip_code": "94105",
    "email": "", "insurance_provider": None,  # LLMs send blanks for skipped fields
}


# --- auth --------------------------------------------------------------------

def test_rejects_missing_secret(client):
    assert client.post("/vapi/tools", json=tool_call("lookup_patient", {})).status_code == 401


def test_accepts_bearer_secret(client):
    r = client.post("/vapi/tools", json=tool_call("lookup_patient", {}),
                    headers={"Authorization": "Bearer test-secret"})
    assert r.status_code == 200


# --- validate_field ----------------------------------------------------------

def test_validate_future_dob(client):
    future = (date.today() + timedelta(days=30)).strftime("%m/%d/%Y")
    out = run(client, "validate_field", {"field": "date_of_birth", "value": future})
    assert out["valid"] is False and "future" in out["error"]


def test_validate_dob_normalises(client):
    out = run(client, "validate_field", {"field": "date_of_birth", "value": "1990-03-04"})
    assert out == {"valid": True, "field": "date_of_birth", "normalized": "03/04/1990",
                   "say_back": "March 4, 1990"}


def test_validate_short_phone(client):
    out = run(client, "validate_field", {"field": "phone_number", "value": "555"})
    assert out["valid"] is False and "10-digit" in out["error"]


def test_validate_state_name(client):
    out = run(client, "validate_field", {"field": "state", "value": "texas"})
    assert out["normalized"] == "TX" and out["say_back"] == "Texas (TX)"


def test_validate_phone_flags_existing_patient(client):
    run(client, "save_patient", SPOKEN_PATIENT, call_id="call-A")
    out = run(client, "validate_field", {"field": "phone_number", "value": "415-555-0123"}, call_id="call-B")
    assert out["valid"] is True
    assert out["existing_patients"][0]["first_name"] == "Maria"


def test_validate_phone_new_number_has_no_matches(client):
    out = run(client, "validate_field", {"field": "phone_number", "value": "2125550100"})
    assert out["valid"] is True and "existing_patients" not in out


def test_validate_unknown_field(client):
    assert run(client, "validate_field", {"field": "shoe_size", "value": "9"})["valid"] is False


# --- save_patient ------------------------------------------------------------

def test_save_creates_and_links_call(client):
    out = run(client, "save_patient", SPOKEN_PATIENT)
    assert out["success"] is True and out["first_name"] == "Maria"
    p = client.get(f"/patients/{out['patient_id']}").json()["data"]
    assert (p["phone_number"], p["state"], p["email"]) == ("4155550123", "CA", None)


def test_save_returns_field_errors(client):
    bad = {**SPOKEN_PATIENT, "date_of_birth": "13/45/1990", "zip_code": "12"}
    out = run(client, "save_patient", bad)
    assert out["success"] is False and out["error_type"] == "validation"
    assert {e["field"] for e in out["errors"]} == {"date_of_birth", "zip_code"}
    assert client.get("/patients").json()["data"] == []


def test_save_missing_required(client):
    partial = {k: v for k, v in SPOKEN_PATIENT.items() if k != "city"}
    out = run(client, "save_patient", partial)
    assert out["errors"] == [{"field": "city", "message": "This field is required and was not provided."}]


def test_save_retry_in_same_call_does_not_duplicate(client):
    first = run(client, "save_patient", SPOKEN_PATIENT)
    second = run(client, "save_patient", {**SPOKEN_PATIENT, "last_name": "Davies"}, tool_id="tc-2")
    assert first["patient_id"] == second["patient_id"]
    rows = client.get("/patients").json()["data"]
    assert len(rows) == 1 and rows[0]["last_name"] == "Davies"


def test_save_db_failure_is_spoken_error(client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import patients as svc

    def boom(*a, **k):
        raise OperationalError("insert", {}, Exception("db down"))

    monkeypatch.setattr(svc, "create_patient", boom)
    out = run(client, "save_patient", SPOKEN_PATIENT)
    assert out["success"] is False and out["error_type"] == "system"


# --- returning caller ----------------------------------------------------------

def test_lookup_uses_caller_id(client):
    run(client, "save_patient", SPOKEN_PATIENT, call_id="call-A")
    out = run(client, "lookup_patient", {}, call_id="call-B")
    assert out["found"] is True
    assert out["matches"][0]["first_name"] == "Maria"


def test_lookup_not_found(client):
    assert run(client, "lookup_patient", {"phone_number": "2125550100"}) == {"found": False}


def test_update_existing(client):
    saved = run(client, "save_patient", SPOKEN_PATIENT, call_id="call-A")
    out = run(client, "update_patient", {"patient_id": saved["patient_id"], "city": "Oakland"},
              call_id="call-B")
    assert out["success"] is True and out["updated_fields"] == ["city"]
    assert client.get(f"/patients/{saved['patient_id']}").json()["data"]["city"] == "Oakland"


def test_update_bad_id(client):
    out = run(client, "update_patient", {"patient_id": "nope", "city": "Oakland"})
    assert out["error_type"] == "not_found"


def test_unknown_tool(client):
    r = client.post("/vapi/tools", json=tool_call("hack", {}), headers=AUTH)
    assert "error" in r.json()["results"][0]


# --- end-of-call report ------------------------------------------------------

def test_end_of_call_links_transcript(client):
    saved = run(client, "save_patient", SPOKEN_PATIENT, call_id="call-Z")
    report = {"message": {
        "type": "end-of-call-report", "endedReason": "assistant-ended-call",
        "call": {"id": "call-Z", "customer": {"number": CALLER}},
        "artifact": {"transcript": "AI: Hi...\nUser: I'm Maria"},
        "analysis": {"summary": "Registered Maria Davis."},
    }}
    assert client.post("/vapi/events", json=report, headers=AUTH).status_code == 200
    calls = client.get(f"/patients/{saved['patient_id']}/calls").json()["data"]
    assert calls[0]["summary"] == "Registered Maria Davis."
    assert calls[0]["ended_reason"] == "assistant-ended-call"


def test_dropped_call_logged_without_patient(client):
    report = {"message": {"type": "end-of-call-report", "endedReason": "customer-ended-call",
                          "call": {"id": "call-drop"}, "artifact": {"transcript": "AI: Hi"}}}
    assert client.post("/vapi/events", json=report, headers=AUTH).status_code == 200
    assert client.get("/patients").json()["data"] == []


def test_other_events_ignored(client):
    r = client.post("/vapi/events", json={"message": {"type": "status-update"}}, headers=AUTH)
    assert r.status_code == 200
