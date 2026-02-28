from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lifecycle_stages_endpoint() -> None:
    response = client.get("/api/lifecycle/stages")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["stages"], list)
    assert body["stages"][0]["id"] == "patient-call"


def test_consultation_summary_endpoint() -> None:
    payload = {
        "appointmentId": "apt-1",
        "patientId": "pat-1",
        "transcript": [
            {"speaker": "Patient", "text": "J'ai mal a la gorge et de la fievre."},
            {"speaker": "Doctor", "text": "Depuis combien de temps ?"},
        ],
    }
    response = client.post("/api/consultation/summary", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "summary" in body
    assert "prescription" in body


def test_suggest_questions_endpoint() -> None:
    payload = {
        "appointmentId": "apt-1",
        "patientId": "pat-1",
        "transcript": [
            {"speaker": "Patient", "text": "J'ai une douleur a la gorge."},
            {"speaker": "Doctor", "text": "Depuis quand ?"},
        ],
    }
    response = client.post("/api/consultation/suggest-questions", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["questions"], list)
    assert "askedTopics" in body


def test_consultation_state_endpoint() -> None:
    start_payload = {"appointmentId": "apt-state-1", "patientId": "pat-1"}
    start_response = client.post("/api/lifecycle/consultation/start", json=start_payload)
    assert start_response.status_code == 200

    response = client.get("/api/lifecycle/consultation/apt-state-1/state")
    assert response.status_code == 200
    assert response.json()["state"]["status"] == "active"


def test_booking_calcom_endpoint_mock_mode() -> None:
    payload = {
        "patientId": "pat-22",
        "patientName": "Jean Martin",
        "patientPhone": "+33612345678",
        "patientEmail": "jean@example.com",
        "reason": "Douleur thoracique legere",
        "startsAt": "2026-03-01T09:00:00+01:00",
        "timezone": "Europe/Paris",
    }
    response = client.post("/api/booking/calcom", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["appointmentId"].startswith("apt-")
    assert body["smsStatus"] in {"sent", "queued"}
