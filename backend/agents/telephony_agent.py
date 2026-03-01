#!/usr/bin/env python3
"""
Telephony Voice Assistant - LiveKit SIP + Twilio + Speechmatics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions, RunContext, WorkerOptions, function_tool
from livekit.plugins import openai, silero, speechmatics

load_dotenv()

REQUIRED_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
BACKEND_API_BASE_URL = os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_TELEPHONY_WELCOME = (
    "Hello, welcome to MedVoice Care Connect. "
    "I can help schedule your consultation today. "
    "Are you already a patient with us, or is this your first visit?"
)
logger = logging.getLogger("medvoice.telephony")
CALL_TRANSCRIPTS: dict[str, list[dict[str, str]]] = defaultdict(list)
CALL_STARTED_AT: dict[str, str] = {}
CALL_PATIENT_CONTEXT: dict[str, dict[str, object]] = {}


def configure_logging() -> None:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default=%s", name, raw, default)
        return default


def utc_now_iso() -> str:
    return datetime.now(dt_timezone.utc).isoformat()


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def normalize_phone_digits(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits or "unknown"


def infer_patient_id(patient_phone: str) -> str:
    return f"pat-{normalize_phone_digits(patient_phone)}"


def infer_email(patient_phone: str, provided_email: str | None) -> str:
    if provided_email and "@" in provided_email:
        return provided_email.strip().lower()
    return f"patient_{normalize_phone_digits(patient_phone)}@medvoice.local"


def phone_lookup_candidates(phone: str) -> list[str]:
    raw_phone = (phone or "").strip()
    if not raw_phone:
        return []
    digits = normalize_phone_digits(raw_phone)

    candidates: list[str] = []
    for candidate in (raw_phone, f"+{digits}" if digits != "unknown" else "", digits):
        cleaned = candidate.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def compact_str_list(value: object, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    deduped: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text or text in deduped:
            continue
        deduped.append(text)
        if len(deduped) >= limit:
            break
    return deduped


def default_future_slot_iso(timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = dt_timezone.utc
    now_local = datetime.now(tz)
    candidate = now_local.replace(hour=10, minute=0, second=0, microsecond=0)
    if candidate <= now_local:
        candidate = candidate + timedelta(days=1)
        candidate = candidate.replace(hour=10, minute=0, second=0, microsecond=0)
    return candidate.isoformat()


def candidate_slots_iso(timezone_name: str, days_ahead: int = 7) -> list[str]:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = dt_timezone.utc
    base = datetime.now(tz)
    slots: list[str] = []
    for day in range(1, days_ahead + 1):
        for hour in (9, 11, 14, 16):
            slot = (base + timedelta(days=day)).replace(
                hour=hour,
                minute=0,
                second=0,
                microsecond=0,
            )
            slots.append(slot.isoformat())
    return slots


def format_slot_label(starts_at_iso: str, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = dt_timezone.utc
    parsed = parse_iso_datetime(starts_at_iso)
    if not parsed:
        return starts_at_iso
    local_dt = parsed.astimezone(tz)
    return local_dt.strftime("%A %d %B at %H:%M")


def booking_failure_message(status_code: int, body_text: str) -> str:
    lowered = body_text.lower()
    if "in the past" in lowered:
        return (
            "Booking could not be completed because the requested date/time is in the past. "
            "Please fetch live availability again and ask the patient to choose a later slot."
        )
    if "not available" in lowered or "already has booking" in lowered:
        return (
            "Booking could not be completed because that slot is unavailable. "
            "Please fetch live availability again, offer fresh options, and ask the patient to choose one."
        )
    return (
        f"Booking failed with status {status_code}. "
        "Please fetch live availability again and retry with a newly selected slot."
    )


def validate_required_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")


def load_agent_prompt() -> str:
    agent_file = Path(__file__).parent.parent / "assets" / "agent.md"
    if agent_file.exists():
        return agent_file.read_text(encoding="utf-8")
    return (
        "You are MedVoice's clinical voice assistant. "
        "Always respond in English, ask one concise medical intake question at a time, "
        "and escalate urgent red-flag symptoms immediately."
    )


def load_welcome_message() -> str:
    value = (os.getenv("TELEPHONY_WELCOME_MESSAGE") or "").strip()
    return value or DEFAULT_TELEPHONY_WELCOME


def build_stt():
    language = os.getenv("STT_LANGUAGE", "en").strip()
    domain = (os.getenv("STT_DOMAIN", "medical") or "").strip().lower()
    operating_point = (os.getenv("STT_OPERATING_POINT", "enhanced") or "").strip().lower()

    # Speechmatics plugin argument names can vary across SDK versions.
    # Try medical+enhanced first, then progressively relax to stay compatible.
    language_kwargs: list[dict[str, str]] = []
    if language:
        language_kwargs = [{key: language} for key in ("language", "language_code")]
    else:
        language_kwargs = [{}]

    for lang_kwargs in language_kwargs:
        attempts: list[dict[str, str]] = []
        if domain and operating_point:
            attempts.append({**lang_kwargs, "domain": domain, "operating_point": operating_point})
        if domain:
            attempts.append({**lang_kwargs, "domain": domain})
        if operating_point:
            attempts.append({**lang_kwargs, "operating_point": operating_point})
        attempts.append(dict(lang_kwargs))

        for kwargs in attempts:
            try:
                return speechmatics.STT(**kwargs)
            except TypeError:
                continue

    logger.warning(
        "speechmatics.STT in this SDK version does not accept language/domain/operating_point overrides; "
        "falling back to default STT settings."
    )
    return speechmatics.STT()


def build_tts():
    provider = os.getenv("TTS_PROVIDER", "openai").strip().lower()
    if provider == "speechmatics":
        speechmatics_tts = getattr(speechmatics, "TTS", None)
        if speechmatics_tts:
            voice = os.getenv("SPEECHMATICS_VOICE", "megan")
            return speechmatics_tts(voice=voice)
        logger.warning("speechmatics.TTS is unavailable in this SDK version; falling back to OpenAI TTS.")

    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "ash")
    speed = read_float_env("OPENAI_TTS_SPEED", 1.25)
    try:
        return openai.TTS(model=model, voice=voice, speed=speed)
    except TypeError:
        logger.warning(
            "openai.TTS in this SDK version has no speed argument; "
            "falling back without speed override."
        )
        return openai.TTS(model=model, voice=voice)


class VoiceAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=load_agent_prompt())

    @function_tool()
    async def load_patient_context_by_phone(
        self,
        context: RunContext,
        patient_phone: str,
    ) -> str:
        """Load patient context by phone and prepare identity confirmation."""
        room_name = _extract_room_name(context)
        candidates = phone_lookup_candidates(patient_phone)
        if not candidates:
            CALL_PATIENT_CONTEXT.pop(room_name, None)
            return json.dumps(
                {
                    "found": False,
                    "reason": "invalid_phone",
                    "message": "No valid phone number provided. Continue as new patient.",
                },
                ensure_ascii=True,
            )

        payload: dict | None = None
        matched_phone: str | None = None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                for candidate in candidates:
                    response = await client.get(
                        f"{BACKEND_API_BASE_URL}/api/dashboard/patients/{quote(candidate, safe='')}"
                    )
                    if response.status_code == 404:
                        continue
                    if response.status_code >= 400:
                        return json.dumps(
                            {
                                "found": False,
                                "reason": "history_unavailable",
                                "message": "Patient history is unavailable right now. Continue intake without history.",
                            },
                            ensure_ascii=True,
                        )
                    payload = response.json()
                    matched_phone = candidate
                    break
        except Exception as exc:  # pragma: no cover
            logger.warning("Patient context lookup failed for %s: %s", patient_phone, exc)
            return json.dumps(
                {
                    "found": False,
                    "reason": "history_unavailable",
                    "message": "Patient history is unavailable right now. Continue intake without history.",
                },
                ensure_ascii=True,
            )

        if not payload:
            CALL_PATIENT_CONTEXT.pop(room_name, None)
            return json.dumps(
                {
                    "found": False,
                    "reason": "not_found",
                    "message": "No existing patient profile found for this phone. Continue as first visit.",
                },
                ensure_ascii=True,
            )

        patient = payload.get("patient") or {}
        appointments = payload.get("appointments") or []
        calls = payload.get("calls") or []
        first_name = str(patient.get("firstName") or "").strip()
        last_name = str(patient.get("lastName") or "").strip()
        patient_name = f"{first_name} {last_name}".strip() or "this patient"
        allergies = compact_str_list(patient.get("allergies"))
        conditions = compact_str_list(patient.get("antecedents"))
        context_profile = {
            "patient_id": str(patient.get("id") or matched_phone or patient_phone),
            "phone": str(patient.get("phone") or matched_phone or patient_phone),
            "name": patient_name,
            "allergies": allergies,
            "conditions": conditions,
            "last_appointment_date": patient.get("lastAppointmentDate"),
            "last_appointment_motif": patient.get("lastAppointmentMotif"),
            "upcoming_count": int(patient.get("upcomingAppointmentsCount") or 0),
        }
        CALL_PATIENT_CONTEXT[room_name] = context_profile

        appointment_hints = [
            {
                "date": item.get("date"),
                "motif": item.get("motif"),
                "doctor": item.get("doctor"),
            }
            for item in appointments[:3]
        ]
        call_hints = [
            {
                "date": item.get("date"),
                "motif": item.get("motif"),
                "summary": str(item.get("summary") or "")[:140],
            }
            for item in calls[:3]
        ]
        return json.dumps(
            {
                "found": True,
                "matchedPhone": matched_phone or patient_phone,
                "patientName": patient_name,
                "patientId": context_profile["patient_id"],
                "identityConfirmationRequired": True,
                "identityConfirmationQuestion": (
                    f"I found a profile for {patient_name}. Can you confirm this is you?"
                ),
                "knownAllergies": allergies,
                "knownConditions": conditions,
                "lastAppointmentDate": context_profile["last_appointment_date"],
                "lastAppointmentMotif": context_profile["last_appointment_motif"],
                "upcomingAppointmentsCount": context_profile["upcoming_count"],
                "recentAppointments": appointment_hints,
                "recentCalls": call_hints,
            },
            ensure_ascii=True,
        )

    @function_tool()
    async def propose_consultation_slots(
        self,
        timezone: str = "Europe/Paris",
        count: int = 3,
        days_ahead: int = 10,
    ) -> str:
        """Return real-time available slots from Cal.com to offer the patient."""
        safe_count = min(max(count, 2), 5)
        safe_days = min(max(days_ahead, 1), 30)
        availability_payload: dict | None = None

        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(
                    f"{BACKEND_API_BASE_URL}/api/booking/calcom/availability",
                    params={
                        "timezone": timezone,
                        "daysAhead": safe_days,
                        "limit": safe_count,
                    },
                )
                if response.status_code >= 400:
                    logger.error(
                        "Availability endpoint failed status=%s body=%s",
                        response.status_code,
                        response.text[:300],
                    )
                    return (
                        "I could not fetch live availability right now. "
                        "Please try again in a moment or offer manual callback scheduling."
                    )
                availability_payload = response.json()
        except Exception as exc:  # pragma: no cover
            logger.warning("Cal.com availability lookup failed: %s", exc)
            return (
                "I could not fetch live availability right now. "
                "Please try again in a moment or offer manual callback scheduling."
            )

        slots = availability_payload.get("slots") if isinstance(availability_payload, dict) else []
        options: list[dict[str, str]] = []
        if isinstance(slots, list):
            for item in slots[:safe_count]:
                starts_at_iso = str((item or {}).get("startsAt") or "").strip()
                if not starts_at_iso:
                    continue
                options.append(
                    {
                        "starts_at_iso": starts_at_iso,
                        "label": format_slot_label(starts_at_iso, timezone),
                    }
                )

        if not options:
            return (
                "No live slot is available in the selected range. "
                "Ask the patient for a wider date range or another preferred day."
            )

        return json.dumps(
            {
                "timezone": timezone,
                "options": options,
                "source": (availability_payload or {}).get("source", "calcom"),
                "agent_instruction": (
                    "Read the options to the patient, ask them to pick one, "
                    "then ask explicit confirmation before booking."
                ),
            },
            ensure_ascii=True,
        )

    @function_tool()
    async def book_consultation_with_confirmation(
        self,
        context: RunContext,
        patient_name: str,
        patient_phone: str,
        patient_id: str | None = None,
        patient_email: str | None = None,
        reason: str = "General medical consultation",
        starts_at_iso: str | None = None,
        timezone: str = "Europe/Paris",
        symptoms: list[str] | None = None,
        conditions: list[str] | None = None,
        allergies: list[str] | None = None,
        conversation_summary: str | None = None,
    ) -> str:
        """Create booking in Cal.com, send SMS confirmation, and persist call medical context."""
        room_name = _extract_room_name(context)
        known_context = CALL_PATIENT_CONTEXT.get(room_name, {})
        transcript = _build_transcript_payload(room_name)
        requested_slot = (starts_at_iso or "").strip()
        if not requested_slot:
            return (
                "Booking was not executed because no specific slot was selected. "
                "Please offer schedule options, ask the patient to choose one, and confirm before booking."
            )
        effective_patient_id = (patient_id or "").strip() or str(known_context.get("patient_id") or "")
        if not effective_patient_id:
            effective_patient_id = infer_patient_id(patient_phone)
        effective_email = infer_email(patient_phone, patient_email)
        effective_starts = requested_slot
        parsed_start = parse_iso_datetime(effective_starts)
        if not parsed_start:
            return (
                "Booking was not executed because the selected date/time was invalid. "
                "Please ask for a valid date/time and confirm again."
            )
        if parsed_start <= datetime.now(dt_timezone.utc):
            return (
                "Booking was not executed because the selected date/time is in the past. "
                "Please ask the patient to choose a later slot."
            )
        effective_conditions = conditions if conditions is not None else compact_str_list(known_context.get("conditions"))
        effective_allergies = allergies if allergies is not None else compact_str_list(known_context.get("allergies"))

        payload = {
            "patientId": effective_patient_id,
            "patientName": patient_name,
            "patientPhone": patient_phone,
            "patientEmail": effective_email,
            "reason": reason,
            "startsAt": effective_starts,
            "timezone": timezone,
            "symptoms": symptoms or [],
            "conditions": effective_conditions,
            "allergies": effective_allergies,
            "conversationSummary": conversation_summary,
            "transcript": transcript,
            "callStartedAt": CALL_STARTED_AT.get(room_name),
            "callEndedAt": utc_now_iso(),
            "createdVia": "livekit_tool",
        }

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(f"{BACKEND_API_BASE_URL}/api/booking/calcom", json=payload)
                if response.status_code >= 400:
                    return booking_failure_message(response.status_code, response.text)
                else:
                    body = response.json()
        except Exception as exc:  # pragma: no cover
            return f"Booking failed: {exc}"
        finally:
            if room_name in CALL_TRANSCRIPTS:
                CALL_TRANSCRIPTS.pop(room_name, None)
            CALL_STARTED_AT.pop(room_name, None)
            CALL_PATIENT_CONTEXT.pop(room_name, None)

        appointment_id = body.get("appointmentId", "unknown")
        sms_status = body.get("smsStatus", "unknown")
        meeting_url = body.get("meetingUrl")
        link_part = f" Meeting link: {meeting_url}." if meeting_url else ""
        return (
            f"Booking completed. Appointment ID: {appointment_id}. "
            f"SMS status: {sms_status}.{link_part}"
        )


def _extract_room_name(context: RunContext) -> str:
    room = getattr(context, "room", None)
    if room and getattr(room, "name", None):
        return str(room.name)
    value = getattr(context, "room_name", None)
    return str(value or "unknown-room")


def _build_transcript_payload(room_name: str) -> list[dict[str, str]]:
    transcript: list[dict[str, str]] = []
    for item in CALL_TRANSCRIPTS.get(room_name, []):
        role = item.get("role", "").upper()
        if role == "ASSISTANT":
            speaker = "AI"
        elif role == "DOCTOR":
            speaker = "Doctor"
        else:
            speaker = "Patient"
        transcript.append(
            {
                "speaker": speaker,
                "text": item.get("text", ""),
                "timestamp": item.get("timestamp"),
            }
        )
    return transcript


def attach_session_logging(session: AgentSession, room_name: str) -> None:
    @session.on("conversation_item_added")
    def on_conversation_item_added(event) -> None:
        item = getattr(event, "item", None)
        if not item:
            return
        text = (getattr(item, "text_content", "") or "").strip()
        if not text:
            return
        role = str(getattr(item, "role", "unknown")).upper()
        interrupted = bool(getattr(item, "interrupted", False))
        logger.info("[TRANSCRIPT][%s][interrupted=%s] %s", role, interrupted, text)
        CALL_TRANSCRIPTS[room_name].append(
            {
                "role": role,
                "text": text,
                "timestamp": utc_now_iso(),
            }
        )

    @session.on("error")
    def on_error(event) -> None:
        error = getattr(event, "error", None)
        source = getattr(event, "source", "unknown")
        logger.error("Agent session error from %s: %s", source, error)


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    room_name = ctx.room.name if ctx.room and ctx.room.name else "unknown-room"
    CALL_TRANSCRIPTS.pop(room_name, None)
    CALL_PATIENT_CONTEXT.pop(room_name, None)
    CALL_STARTED_AT[room_name] = utc_now_iso()

    session = AgentSession(
        stt=build_stt(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=build_tts(),
        vad=silero.VAD.load(),
    )
    attach_session_logging(session, room_name)

    await session.start(
        room=ctx.room,
        agent=VoiceAssistant(),
        room_input_options=RoomInputOptions(),
    )

    # Keep the first utterance deterministic and non-interruptible so callers always hear the full greeting.
    await session.say(load_welcome_message(), allow_interruptions=False)


def run() -> None:
    configure_logging()
    validate_required_env()
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="medvoice-telephony",
        )
    )


if __name__ == "__main__":
    run()
