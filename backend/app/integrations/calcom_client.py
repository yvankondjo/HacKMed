from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
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

    async def get_available_slots(
        self,
        *,
        timezone: str | None = None,
        event_type_id: int | None = None,
        days_ahead: int = 10,
        limit: int = 5,
    ) -> list[str]:
        target_tz = timezone or self.config.calcom_timezone
        effective_event_type_id = event_type_id or self.config.calcom_event_type_id
        safe_days = min(max(days_ahead, 1), 30)
        safe_limit = min(max(limit, 1), 20)
        start_utc = datetime.now(dt_timezone.utc)
        end_utc = start_utc + timedelta(days=safe_days)

        if not self.enabled or not effective_event_type_id:
            # Local/dev fallback where Cal.com credentials are absent.
            anchor = start_utc.astimezone(ZoneInfo(target_tz)).isoformat()
            return self._candidate_starts(anchor, target_tz)[:safe_limit]

        headers = {
            "Authorization": f"Bearer {self.config.calcom_api_key}",
            # Slots endpoint expects 2024-09-04+ semantics.
            "cal-api-version": "2024-09-04",
        }
        params = {
            "eventTypeId": effective_event_type_id,
            "start": start_utc.isoformat().replace("+00:00", "Z"),
            "end": end_utc.isoformat().replace("+00:00", "Z"),
            "timeZone": target_tz,
        }

        url = f"{self.config.calcom_base_url.rstrip('/')}/slots"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Cal.com availability failed ({response.status_code}) for {url}: {response.text[:400]}"
                )
            body = response.json()

        slots = self._extract_slots_from_payload(body)
        return slots[:safe_limit]

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

    @classmethod
    def _extract_slots_from_payload(cls, payload: Any) -> list[str]:
        slots_root: Any = payload
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            data = payload.get("data")
            if isinstance(data, dict):
                slots_root = data.get("slots", data)
        elif isinstance(payload, dict):
            slots_root = payload.get("slots", payload)

        found: list[str] = []
        cls._walk_slots(slots_root, found)
        deduped = sorted({slot for slot in found if slot})
        return deduped

    @classmethod
    def _walk_slots(cls, node: Any, out: list[str]) -> None:
        if isinstance(node, str):
            if not node:
                return
            try:
                parsed = datetime.fromisoformat(node.replace("Z", "+00:00"))
            except ValueError:
                return
            out.append(parsed.isoformat())
            return

        if isinstance(node, dict):
            for key in ("time", "start", "startTime", "startsAt", "dateTime"):
                value = node.get(key)
                if isinstance(value, str):
                    try:
                        out.append(datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat())
                    except ValueError:
                        continue
            for value in node.values():
                cls._walk_slots(value, out)
            return

        if isinstance(node, list):
            for item in node:
                cls._walk_slots(item, out)
