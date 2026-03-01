from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import logging
from urllib import error, parse, request

from app.config import SmsConfig

logger = logging.getLogger("medvoice.twilio")


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
            and (
                self.config.twilio_from_number
                or self.config.twilio_messaging_service_sid
            )
        )

    def send_confirmation_sms(self, *, to_phone: str, body: str) -> SmsResult:
        preview = body[:120]
        if not self.enabled:
            return SmsResult(
                sid="mock-sms-disabled",
                status="queued",
                raw={
                    "mock": True,
                    "twilio_disabled": True,
                    "to": to_phone,
                    "body_preview": preview,
                },
            )

        if self._can_use_twilio_sdk():
            return self._send_via_sdk(to_phone=to_phone, body=body)
        return self._send_via_rest_api(to_phone=to_phone, body=body)

    @staticmethod
    def _can_use_twilio_sdk() -> bool:
        try:
            import twilio.rest  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def _send_via_sdk(self, *, to_phone: str, body: str) -> SmsResult:
        try:
            from twilio.rest import Client  # type: ignore

            client = Client(
                self.config.twilio_account_sid,
                self.config.twilio_auth_token,
            )
            kwargs = {
                "to": to_phone,
                "body": body,
            }
            if self.config.twilio_messaging_service_sid:
                kwargs["messaging_service_sid"] = self.config.twilio_messaging_service_sid
            else:
                kwargs["from_"] = self.config.twilio_from_number

            message = client.messages.create(**kwargs)
            status = str(getattr(message, "status", "") or "queued")
            sid = str(getattr(message, "sid", "") or "unknown")
            return SmsResult(
                sid=sid,
                status=status,
                raw={
                    "provider": "twilio-sdk",
                    "to": to_phone,
                    "from": self.config.twilio_from_number,
                    "messaging_service_sid": self.config.twilio_messaging_service_sid,
                    "body_preview": body[:120],
                    "status": status,
                },
            )
        except Exception as exc:
            logger.exception("Twilio SDK SMS send failed: %s", exc)
            return SmsResult(
                sid="sms-failed-sdk",
                status="failed",
                raw={
                    "provider": "twilio-sdk",
                    "error": str(exc),
                    "to": to_phone,
                    "body_preview": body[:120],
                },
            )

    def _send_via_rest_api(self, *, to_phone: str, body: str) -> SmsResult:
        account_sid = self.config.twilio_account_sid or ""
        auth_token = self.config.twilio_auth_token or ""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

        payload = {
            "To": to_phone,
            "Body": body,
        }
        if self.config.twilio_messaging_service_sid:
            payload["MessagingServiceSid"] = self.config.twilio_messaging_service_sid
        else:
            payload["From"] = self.config.twilio_from_number or ""

        encoded_payload = parse.urlencode(payload).encode("utf-8")
        req = request.Request(url=url, data=encoded_payload, method="POST")
        basic = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("utf-8")
        req.add_header("Authorization", f"Basic {basic}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with request.urlopen(req, timeout=20) as response:
                response_body = response.read().decode("utf-8")
            parsed_body = json.loads(response_body) if response_body else {}
            status = str(parsed_body.get("status") or "queued")
            sid = str(parsed_body.get("sid") or "unknown")
            return SmsResult(
                sid=sid,
                status=status,
                raw={
                    "provider": "twilio-rest",
                    "to": to_phone,
                    "from": self.config.twilio_from_number,
                    "messaging_service_sid": self.config.twilio_messaging_service_sid,
                    "body_preview": body[:120],
                    "status": status,
                },
            )
        except error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            logger.error("Twilio REST SMS failed status=%s detail=%s", exc.code, detail)
            return SmsResult(
                sid="sms-failed-rest",
                status="failed",
                raw={
                    "provider": "twilio-rest",
                    "http_status": exc.code,
                    "error": detail[:400],
                    "to": to_phone,
                    "body_preview": body[:120],
                },
            )
        except Exception as exc:
            logger.exception("Twilio REST SMS send failed: %s", exc)
            return SmsResult(
                sid="sms-failed-rest",
                status="failed",
                raw={
                    "provider": "twilio-rest",
                    "error": str(exc),
                    "to": to_phone,
                    "body_preview": body[:120],
                },
            )
