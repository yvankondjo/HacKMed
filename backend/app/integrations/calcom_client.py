from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import CalendarConfig


@dataclass(frozen=True)
class BookingResult:
    booking_id: str
    start_at: str
    end_at: str
    timezone: str
    meeting_url: str | None
    raw: dict


class CalComClient:
    def __init__(self, config: CalendarConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.calcom_api_key and self.config.calcom_event_type_id)

    async def create_booking(
        self,
        *,
        patient_name: str,
        patient_email: str,
        patient_phone: str,
        starts_at_iso: str,
        reason: str,
        timezone: str | None = None,
        event_type_id: int | None = None,
        duration_minutes: int = 20,
    ) -> BookingResult:
        target_tz = timezone or self.config.calcom_timezone
        effective_event_type_id = event_type_id or self.config.calcom_event_type_id
        if not self.enabled:
            # Fallback for local dev without external services.
            return self._build_mock_booking(
                patient_name=patient_name,
                starts_at_iso=starts_at_iso,
                timezone=target_tz,
                duration_minutes=duration_minutes,
            )
        if not effective_event_type_id:
            raise RuntimeError("CALCOM_EVENT_TYPE_ID is required")

        headers = {
            "Authorization": f"Bearer {self.config.calcom_api_key}",
            "Content-Type": "application/json",
            "cal-api-version": self.config.calcom_api_version,
        }
        payload = {
            "start": starts_at_iso,
            "eventTypeId": effective_event_type_id,
            "attendee": {
                "name": patient_name,
                "email": patient_email,
                "timeZone": target_tz,
                "phoneNumber": patient_phone,
            },
            "bookingFieldsResponses": {
                "notes": reason,
            },
        }

        url = f"{self.config.calcom_base_url.rstrip('/')}/bookings"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                lowered = response.text.lower()
                retryable = (
                    response.status_code == 400
                    and (
                        "not available" in lowered
                        or "already has booking" in lowered
                        or "in the past" in lowered
                    )
                )
                if retryable:
                    for candidate_start in self._candidate_starts(starts_at_iso, target_tz):
                        retry_payload = dict(payload)
                        retry_payload["start"] = candidate_start
                        retry_response = await client.post(url, headers=headers, json=retry_payload)
                        if retry_response.status_code < 400:
                            body = retry_response.json()
                            data = body.get("data", {})
                            return BookingResult(
                                booking_id=str(data.get("id") or ""),
                                start_at=data.get("start") or candidate_start,
                                end_at=data.get("end") or self._end_from_start(candidate_start, duration_minutes),
                                timezone=(data.get("timeZone") or target_tz),
                                meeting_url=data.get("meetingUrl"),
                                raw=body,
                            )
                raise RuntimeError(
                    f"Cal.com booking failed ({response.status_code}) for {url}: {response.text[:400]}"
                )
            body = response.json()

        data = body.get("data", {})
        return BookingResult(
            booking_id=str(data.get("id") or ""),
            start_at=data.get("start") or starts_at_iso,
            end_at=data.get("end") or self._end_from_start(starts_at_iso, duration_minutes),
            timezone=(data.get("timeZone") or target_tz),
            meeting_url=data.get("meetingUrl"),
            raw=body,
        )

    def _build_mock_booking(
        self,
        *,
        patient_name: str,
        starts_at_iso: str,
        timezone: str,
        duration_minutes: int,
    ) -> BookingResult:
        mock_id = f"mock-{patient_name.lower().replace(' ', '-')}"
        return BookingResult(
            booking_id=mock_id,
            start_at=starts_at_iso,
            end_at=self._end_from_start(starts_at_iso, duration_minutes),
            timezone=timezone,
            meeting_url="https://cal.local/mock-room",
            raw={"mock": True},
        )

    @staticmethod
    def _end_from_start(starts_at_iso: str, duration_minutes: int) -> str:
        try:
            base = datetime.fromisoformat(starts_at_iso.replace("Z", "+00:00"))
            return (base + timedelta(minutes=duration_minutes)).isoformat()
        except ValueError:
            return starts_at_iso

    @staticmethod
    def _candidate_starts(starts_at_iso: str, timezone_name: str) -> list[str]:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = ZoneInfo("UTC")
        try:
            base = datetime.fromisoformat(starts_at_iso.replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            base = datetime.now(tz)
        now = datetime.now(tz)
        start_anchor = base if base > now else now
        candidates: list[str] = []
        for day in range(1, 8):
            day_base = (start_anchor + timedelta(days=day))
            for hour in (9, 11, 14, 16):
                candidates.append(
                    day_base.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
                )
        return candidates
