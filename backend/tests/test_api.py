from fastapi.testclient import TestClient

from app.main import app
from app.service import service
from app.integrations.livekit_dispatcher import DispatchResult
from app.integrations.twilio_client import SmsResult


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
            {"speaker": "Patient", "text": "I have a sore throat and fever."},
            {"speaker": "Doctor", "text": "How long has it been going on?"},
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
            {"speaker": "Patient", "text": "I have throat pain."},
            {"speaker": "Doctor", "text": "Since when?"},
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
        "reason": "Mild chest pain",
        "startsAt": "2026-03-01T09:00:00+01:00",
        "timezone": "Europe/Paris",
    }
    response = client.post("/api/booking/calcom", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["appointmentId"], str)
    assert len(body["appointmentId"]) >= 8
    assert body["smsStatus"] in {"sent", "queued"}


def test_booking_calcom_availability_endpoint() -> None:
    response = client.get(
        "/api/booking/calcom/availability",
        params={"timezone": "Europe/Paris", "daysAhead": 7, "limit": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Europe/Paris"
    assert isinstance(body["slots"], list)
    assert body["count"] == len(body["slots"])
    if body["slots"]:
        assert "startsAt" in body["slots"][0]


def test_consultation_token_endpoint() -> None:
    original_url = service._livekit_url
    original_key = service._livekit_api_key
    original_secret = service._livekit_api_secret
    original_auto_dispatch = service._consultation_auto_dispatch
    try:
        service._livekit_url = "wss://example.livekit.cloud"
        service._livekit_api_key = "test-key"
        service._livekit_api_secret = "test-secret"
        service._consultation_auto_dispatch = False
        response = client.get(
            "/api/lifecycle/consultation/apt-99/token",
            params={
                "participantIdentity": "doc-apt-99",
                "participantName": "Doctor",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == "wss://example.livekit.cloud"
        assert body["roomName"] == "consultation-apt-99"
        assert body["participantIdentity"] == "doc-apt-99"
        assert isinstance(body["token"], str)
        assert len(body["token"]) > 20
    finally:
        service._livekit_url = original_url
        service._livekit_api_key = original_key
        service._livekit_api_secret = original_secret
        service._consultation_auto_dispatch = original_auto_dispatch


def test_followup_call_schedule_endpoint() -> None:
    class _MockDispatcher:
        async def dispatch_followup_call(self, *, metadata, room_name=None):
            return DispatchResult(
                status="queued",
                provider="livekit-dispatch",
                dispatch_id="disp-test-1",
                room_name=room_name or "followup-test-room",
                detail="ok",
            )

    class _MockSms:
        def send_confirmation_sms(self, *, to_phone: str, body: str) -> SmsResult:
            return SmsResult(sid="mock-sms", status="queued", raw={"to": to_phone, "body": body})

    original_dispatcher = service._outbound_dispatcher
    original_sms = service._sms_client
    try:
        service._outbound_dispatcher = _MockDispatcher()
        service._sms_client = _MockSms()

        response = client.post(
            "/api/reminder/followup-call",
            json={
                "appointmentId": "apt-followup-1",
                "patientId": "pat-followup-1",
                "patientName": "Test Patient",
                "patientPhone": "0784221830",
                "doctorName": "Dr. Test",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"queued", "mock", "failed"}
        assert body["followupCallId"].startswith("fup-")
        assert body["dialTo"].startswith("+")
    finally:
        service._outbound_dispatcher = original_dispatcher
        service._sms_client = original_sms


def test_followup_call_complete_endpoint() -> None:
    response = client.post(
        "/api/reminder/followup-call/complete",
        json={
            "followupCallId": "fup-test-1",
            "appointmentId": "apt-followup-1",
            "patientId": "pat-followup-1",
            "status": "completed",
            "durationSeconds": 65,
            "summary": "Patient confirms adherence and no new adverse effects.",
            "symptoms": ["Back pain"],
            "recommendations": ["Continue treatment"],
            "evolution": "improvement",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["followupCallId"] == "fup-test-1"
