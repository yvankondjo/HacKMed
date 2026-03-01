#!/usr/bin/env python3
"""
Telephony Voice Assistant - LiveKit SIP + Twilio + Speechmatics.
"""

from __future__ import annotations

import os
from pathlib import Path
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions, RunContext, WorkerOptions, function_tool
from livekit.plugins import openai, silero, speechmatics

load_dotenv()

REQUIRED_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
BACKEND_API_BASE_URL = os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
logger = logging.getLogger("medvoice.telephony")
CALL_TRANSCRIPTS: dict[str, list[dict[str, str]]] = defaultdict(list)
CALL_STARTED_AT: dict[str, str] = {}


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


def booking_failure_message(status_code: int, body_text: str) -> str:
    lowered = body_text.lower()
    if "in the past" in lowered:
        return (
            "Booking could not be completed because the requested date/time is in the past. "
            "Please ask the patient for a later date/time."
        )
    if "not available" in lowered or "already has booking" in lowered:
        return (
            "Booking could not be completed because that slot is unavailable. "
            "Please ask the patient for another time."
        )
    return (
        f"Booking failed with status {status_code}. "
        "Please ask the patient for an alternative date/time and try again."
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


def build_stt():
    language = os.getenv("STT_LANGUAGE", "en").strip()
    if not language:
        return speechmatics.STT()

    # Speechmatics plugin argument names can vary across SDK versions.
    for language_arg in ("language", "language_code"):
        try:
            return speechmatics.STT(**{language_arg: language})
        except TypeError:
            continue

    logger.warning(
        "speechmatics.STT in this SDK version has no language argument; "
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
        transcript = _build_transcript_payload(room_name)
        effective_patient_id = (patient_id or "").strip() or infer_patient_id(patient_phone)
        effective_email = infer_email(patient_phone, patient_email)
        effective_starts = (starts_at_iso or "").strip() or default_future_slot_iso(timezone)
        parsed_start = parse_iso_datetime(effective_starts)
        if not parsed_start or parsed_start <= datetime.now(dt_timezone.utc):
            effective_starts = default_future_slot_iso(timezone)

        payload = {
            "patientId": effective_patient_id,
            "patientName": patient_name,
            "patientPhone": patient_phone,
            "patientEmail": effective_email,
            "reason": reason,
            "startsAt": effective_starts,
            "timezone": timezone,
            "symptoms": symptoms or [],
            "conditions": conditions or [],
            "allergies": allergies or [],
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
                    lowered = response.text.lower()
                    if "in the past" in lowered or "not available" in lowered or "already has booking" in lowered:
                        for candidate in candidate_slots_iso(timezone):
                            payload["startsAt"] = candidate
                            retry_response = await client.post(
                                f"{BACKEND_API_BASE_URL}/api/booking/calcom",
                                json=payload,
                            )
                            if retry_response.status_code < 400:
                                body = retry_response.json()
                                break
                        else:
                            return booking_failure_message(response.status_code, response.text)
                    else:
                        return booking_failure_message(response.status_code, response.text)
                else:
                    body = response.json()
        except Exception as exc:  # pragma: no cover
            return f"Booking failed: {exc}"
        finally:
            if room_name in CALL_TRANSCRIPTS:
                CALL_TRANSCRIPTS.pop(room_name, None)
            CALL_STARTED_AT.pop(room_name, None)

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

    await session.generate_reply(
        instructions=(
            "Say a short hello in English, identify MedVoice, "
            "and ask one medical intake question."
        )
    )


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
