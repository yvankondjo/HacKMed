from __future__ import annotations

from dataclasses import dataclass

from app.config import SmsConfig


@dataclass(frozen=True)
class SmsResult:
    sid: str
    status: str
    raw: dict


class TwilioSmsClient:
    def __init__(self, config: SmsConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.twilio_account_sid
            and self.config.twilio_auth_token
            and self.config.twilio_from_number
        )

    def send_confirmation_sms(self, *, to_phone: str, body: str) -> SmsResult:
        # POC mode: Twilio calls are intentionally disabled.
        # Keep this method deterministic so booking flow continues to work.
        return SmsResult(
            sid="mock-sms-disabled",
            status="sent",
            raw={
                "mock": True,
                "twilio_disabled": True,
                "to": to_phone,
                "body_preview": body[:80],
            },
        )
