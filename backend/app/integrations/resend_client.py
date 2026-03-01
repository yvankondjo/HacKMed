from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from urllib import error, request

from app.config import EmailConfig

logger = logging.getLogger("medvoice.resend")


@dataclass(frozen=True)
class EmailSendResult:
    message_id: str
    status: str
    raw: dict


class ResendEmailClient:
    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.resend_api_key and self.config.resend_from_email)

    def send_prescription_email(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> EmailSendResult:
        if not self.enabled:
            return EmailSendResult(
                message_id="mock-email-disabled",
                status="disabled",
                raw={
                    "mock": True,
                    "provider": "resend",
                    "to": to_email,
                    "subject": subject,
                    "resend_disabled": True,
                },
            )

        payload: dict[str, object] = {
            "from": self.config.resend_from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        if self.config.resend_reply_to:
            payload["reply_to"] = self.config.resend_reply_to

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url="https://api.resend.com/emails",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.config.resend_api_key}")
        req.add_header("User-Agent", "MedVoice/1.0")

        try:
            with request.urlopen(req, timeout=20) as response:
                body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            message_id = str(parsed.get("id") or "unknown")
            return EmailSendResult(
                message_id=message_id,
                status="sent",
                raw={
                    "provider": "resend",
                    "to": to_email,
                    "subject": subject,
                    "id": message_id,
                },
            )
        except error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            logger.error("Resend email failed status=%s detail=%s", exc.code, detail[:500])
            return EmailSendResult(
                message_id="email-failed-http",
                status="failed",
                raw={
                    "provider": "resend",
                    "http_status": exc.code,
                    "error": detail[:500],
                    "to": to_email,
                    "subject": subject,
                },
            )
        except Exception as exc:
            logger.exception("Resend email send failed: %s", exc)
            return EmailSendResult(
                message_id="email-failed",
                status="failed",
                raw={
                    "provider": "resend",
                    "error": str(exc),
                    "to": to_email,
                    "subject": subject,
                },
            )
