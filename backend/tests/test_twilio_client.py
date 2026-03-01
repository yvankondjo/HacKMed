import json

from app.config import SmsConfig
from app.integrations.twilio_client import SmsResult, TwilioSmsClient


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_send_confirmation_sms_disabled_returns_mock() -> None:
    client = TwilioSmsClient(
        SmsConfig(
            twilio_account_sid=None,
            twilio_auth_token=None,
            twilio_from_number=None,
            twilio_messaging_service_sid=None,
        )
    )

    result = client.send_confirmation_sms(to_phone="+33765540003", body="hello")
    assert result.sid == "mock-sms-disabled"
    assert result.status == "queued"
    assert result.raw["twilio_disabled"] is True


def test_send_confirmation_sms_rest_fallback_success(monkeypatch) -> None:
    client = TwilioSmsClient(
        SmsConfig(
            twilio_account_sid="ACtest",
            twilio_auth_token="secret",
            twilio_from_number="+12345678901",
            twilio_messaging_service_sid=None,
        )
    )

    monkeypatch.setattr(client, "_can_use_twilio_sdk", lambda: False)

    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = (req.data or b"").decode("utf-8")
        return _FakeHTTPResponse({"sid": "SM123", "status": "queued"})

    monkeypatch.setattr("app.integrations.twilio_client.request.urlopen", fake_urlopen)

    result = client.send_confirmation_sms(to_phone="+33765540003", body="Test SMS")
    assert result.sid == "SM123"
    assert result.status == "queued"
    assert seen["url"].endswith("/Messages.json")
    assert "To=%2B33765540003" in seen["body"]
    assert "From=%2B12345678901" in seen["body"]


def test_send_confirmation_sms_uses_sdk_when_available(monkeypatch) -> None:
    client = TwilioSmsClient(
        SmsConfig(
            twilio_account_sid="ACtest",
            twilio_auth_token="secret",
            twilio_from_number="+12345678901",
            twilio_messaging_service_sid=None,
        )
    )

    monkeypatch.setattr(client, "_can_use_twilio_sdk", lambda: True)
    monkeypatch.setattr(
        client,
        "_send_via_sdk",
        lambda **kwargs: SmsResult(sid="SMSDK", status="queued", raw={"provider": "twilio-sdk"}),
    )

    result = client.send_confirmation_sms(to_phone="+33765540003", body="Test SMS")
    assert result.sid == "SMSDK"
    assert result.status == "queued"
