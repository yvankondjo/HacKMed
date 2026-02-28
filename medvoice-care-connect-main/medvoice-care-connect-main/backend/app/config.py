from __future__ import annotations

import os
from dataclasses import dataclass


def _read_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


@dataclass(frozen=True)
class CalendarConfig:
    calcom_api_key: str | None
    calcom_base_url: str
    calcom_event_type_id: int | None
    calcom_timezone: str


@dataclass(frozen=True)
class SmsConfig:
    twilio_account_sid: str | None
    twilio_auth_token: str | None
    twilio_from_number: str | None


def load_calendar_config() -> CalendarConfig:
    event_type_id_raw = _read_env("CALCOM_EVENT_TYPE_ID")
    event_type_id = int(event_type_id_raw) if event_type_id_raw else None
    return CalendarConfig(
        calcom_api_key=_read_env("CALCOM_API_KEY"),
        calcom_base_url=_read_env("CALCOM_BASE_URL", "https://api.cal.com/v2") or "https://api.cal.com/v2",
        calcom_event_type_id=event_type_id,
        calcom_timezone=_read_env("CALCOM_TIMEZONE", "Europe/Paris") or "Europe/Paris",
    )


def load_sms_config() -> SmsConfig:
    return SmsConfig(
        twilio_account_sid=_read_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_read_env("TWILIO_AUTH_TOKEN"),
        twilio_from_number=_read_env("TWILIO_FROM_NUMBER"),
    )
