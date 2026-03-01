import json

from app.config import EmailConfig
from app.integrations.resend_client import ResendEmailClient


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_send_prescription_email_disabled_returns_mock() -> None:
    client = ResendEmailClient(
        EmailConfig(
            resend_api_key=None,
            resend_from_email="onboarding@resend.dev",
            resend_reply_to=None,
        )
    )
    result = client.send_prescription_email(
        to_email="patient@example.com",
        subject="Ordonnance",
        html_body="<p>hello</p>",
        text_body="hello",
    )
    assert result.status == "disabled"
    assert result.raw["resend_disabled"] is True


def test_send_prescription_email_success(monkeypatch) -> None:
    client = ResendEmailClient(
        EmailConfig(
            resend_api_key="re_test_123",
            resend_from_email="onboarding@resend.dev",
            resend_reply_to=None,
        )
    )

    seen: dict[str, str] = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization") or ""
        seen["content_type"] = req.get_header("Content-Type") or req.get_header("Content-type") or ""
        seen["body"] = (req.data or b"").decode("utf-8")
        return _FakeHTTPResponse({"id": "email_123"})

    monkeypatch.setattr("app.integrations.resend_client.request.urlopen", fake_urlopen)

    result = client.send_prescription_email(
        to_email="patient@example.com",
        subject="Ordonnance",
        html_body="<p>hello</p>",
        text_body="hello",
    )
    assert result.status == "sent"
    assert result.message_id == "email_123"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["auth"] == "Bearer re_test_123"
    assert seen["content_type"] == "application/json"
    assert '"subject": "Ordonnance"' in seen["body"]
