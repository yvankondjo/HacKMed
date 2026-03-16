#!/usr/bin/env python3
"""
Telephony Voice Assistant - LiveKit SIP + Twilio + Speechmatics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import logging
import time
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
TEST_BOOKING_PHONE = (os.getenv("TELEPHONY_TEST_BOOKING_PHONE") or os.getenv("FOLLOWUP_TEST_PHONE") or "").strip()
DEFAULT_TELEPHONY_WELCOME = (
    "Hello, thank you for calling MedVoice Care Connect. Are you calling for a first visit or a follow-up appointment?"
)
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
        template = agent_file.read_text(encoding="utf-8")
        today_date = datetime.now(dt_timezone.utc).date().isoformat()
        return template.replace("{{TODAY_DATE}}", today_date)
    return (
        "You are MedVoice's clinical voice assistant. "
        "Always respond in English. If the caller speaks another language, ask them to switch to English: "
        "\"Sorry, I can continue only in English. Could you please speak English?\" "
        "Ask one concise medical intake question at a time, and escalate urgent red-flag symptoms immediately."
    )


def load_welcome_message() -> str:
    configured = (os.getenv("TELEPHONY_WELCOME_MESSAGE") or "").strip()
    if configured:
        return configured
    return DEFAULT_TELEPHONY_WELCOME


def resolve_inference_llm_model() -> str:
    configured = (os.getenv("LIVEKIT_INFERENCE_LLM_MODEL") or "").strip()
    if configured:
        return configured
    return "openai/gpt-4.1-mini"


def build_stt():
    language = os.getenv("STT_LANGUAGE", "en").strip()
    configured_domain = (os.getenv("STT_DOMAIN", "medical") or "").strip().lower()
    domain = "medical"
    if configured_domain and configured_domain != "medical":
        logger.warning(
            "STT_DOMAIN=%s requested, but this agent is configured for Speechmatics medical domain only.",
            configured_domain,
        )
    operating_point = (os.getenv("STT_OPERATING_POINT", "enhanced") or "").strip().lower()
    max_delay = read_float_env("STT_MAX_DELAY", 0.7)
    silence_trigger = read_float_env("STT_EOU_SILENCE", 0.35)

    # Speechmatics plugin argument names can vary across SDK versions.
    # Try medical+enhanced first, then progressively relax to stay compatible.
    language_kwargs: list[dict[str, str]] = []
    if language:
        language_kwargs = [{key: language} for key in ("language", "language_code")]
    else:
        language_kwargs = [{}]

    for lang_kwargs in language_kwargs:
        attempts: list[dict[str, str | float]] = []
        if operating_point:
            attempts.append(
                {
                    **lang_kwargs,
                    "domain": domain,
                    "operating_point": operating_point,
                    "max_delay": max_delay,
                    "end_of_utterance_silence_trigger": silence_trigger,
                }
            )
            attempts.append({**lang_kwargs, "domain": domain, "operating_point": operating_point})
        attempts.append({**lang_kwargs, "domain": domain})

        for kwargs in attempts:
            try:
                return speechmatics.STT(**kwargs)
            except TypeError:
                continue

    logger.warning(
        "speechmatics.STT in this SDK version does not accept medical-domain overrides."
    )
    raise RuntimeError(
        "Speechmatics STT medical domain is required but unsupported in this SDK version."
    )


def build_tts():
    provider = os.getenv("TTS_PROVIDER", "speechmatics").strip().lower()
    if provider and provider != "speechmatics":
        logger.warning(
            "TTS_PROVIDER=%s requested, but this agent is configured for Speechmatics TTS only.",
            provider,
        )
    speechmatics_tts = getattr(speechmatics, "TTS", None)
    if speechmatics_tts:
        voice = os.getenv("SPEECHMATICS_VOICE", "megan")
        return speechmatics_tts(voice=voice)

    strict_tts = (os.getenv("SPEECHMATICS_TTS_REQUIRED", "false") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if strict_tts:
        raise RuntimeError(
            "Speechmatics TTS is required but unavailable in this SDK version."
        )

    logger.warning(
        "Speechmatics TTS is unavailable in this SDK version; falling back to OpenAI TTS. "
        "Set SPEECHMATICS_TTS_REQUIRED=true to fail fast."
    )
    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "ash")
    speed = read_float_env("OPENAI_TTS_SPEED", 1.0)
    try:
        return openai.TTS(model=model, voice=voice, speed=speed)
    except TypeError:
        return openai.TTS(model=model, voice=voice)


class VoiceAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=load_agent_prompt())

    @function_tool()
    async def propose_consultation_slots(
        self,
        timezone: str = "Europe/Paris",
        count: int = 3,
        days_ahead: int = 10,
    ) -> str:
        """Return real-time available slots from Cal.com to offer the patient."""
        tool_started = time.perf_counter()
        try:
            logger.info(
                "Tool call: propose_consultation_slots timezone=%s count=%s days_ahead=%s",
                timezone,
                count,
                days_ahead,
            )
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
                    logger.info(
                        "Tool result: propose_consultation_slots source=%s slots=%s",
                        (availability_payload or {}).get("source"),
                        len((availability_payload or {}).get("slots") or []),
                    )
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
        finally:
            elapsed_ms = int((time.perf_counter() - tool_started) * 1000)
            logger.info("Tool latency: propose_consultation_slots duration_ms=%s", elapsed_ms)

    @function_tool()
    async def book_consultation_with_confirmation(
        self,
        context: RunContext,
        patient_name: str,
        patient_phone: str | None = None,
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
        tool_started = time.perf_counter()
        try:
            room_name = _extract_room_name(context)
            logger.info(
                "Tool call: book_consultation_with_confirmation room=%s patient_name=%s starts_at_iso=%s timezone=%s",
                room_name,
                patient_name,
                starts_at_iso,
                timezone,
            )
            transcript = _build_transcript_payload(room_name)
            clean_name = (patient_name or "").strip()
            if not clean_name:
                return (
                    "Booking was not executed because patient full name is missing. "
                    "Please ask the caller full name, confirm it, then retry booking."
                )
            requested_slot = (starts_at_iso or "").strip()
            if not requested_slot:
                return (
                    "Booking was not executed because no specific slot was selected. "
                    "Please offer schedule options, ask the patient to choose one, and confirm before booking."
                )
            forced_phone = TEST_BOOKING_PHONE
            if not forced_phone:
                return (
                    "Booking was not executed because TELEPHONY_TEST_BOOKING_PHONE is not configured. "
                    "Set TELEPHONY_TEST_BOOKING_PHONE or FOLLOWUP_TEST_PHONE in the environment, then retry."
                )
            effective_patient_id = (patient_id or "").strip()
            if not effective_patient_id:
                effective_patient_id = infer_patient_id(forced_phone)
            effective_email = infer_email(forced_phone, patient_email)
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
            effective_conditions = compact_str_list(conditions or [])
            effective_allergies = compact_str_list(allergies or [])

            payload = {
                "patientId": effective_patient_id,
                "patientName": clean_name,
                "patientPhone": forced_phone,
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
                        logger.error(
                            "Tool result: book_consultation_with_confirmation failed status=%s body=%s",
                            response.status_code,
                            response.text[:300],
                        )
                        return booking_failure_message(response.status_code, response.text)
                    else:
                        body = response.json()
                        logger.info(
                            "Tool result: book_consultation_with_confirmation success appointment_id=%s sms_status=%s",
                            body.get("appointmentId"),
                            body.get("smsStatus"),
                        )
            except Exception as exc:
                logger.exception("Tool exception: book_consultation_with_confirmation failed: %s", exc)
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
        finally:
            elapsed_ms = int((time.perf_counter() - tool_started) * 1000)
            logger.info("Tool latency: book_consultation_with_confirmation duration_ms=%s", elapsed_ms)


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

    @session.on("metrics_collected")
    def on_metrics_collected(event) -> None:
        metrics = getattr(event, "metrics", None)
        if not metrics:
            return
        metric_type = getattr(metrics, "type", "unknown")
        duration = getattr(metrics, "duration", None)
        ttft = getattr(metrics, "ttft", None)
        ttfb = getattr(metrics, "ttfb", None)
        eou_delay = getattr(metrics, "end_of_utterance_delay", None)
        logger.info(
            "Metrics: type=%s duration_ms=%s ttft_ms=%s ttfb_ms=%s eou_delay_ms=%s",
            metric_type,
            int(duration * 1000) if isinstance(duration, (int, float)) else None,
            int(ttft * 1000) if isinstance(ttft, (int, float)) else None,
            int(ttfb * 1000) if isinstance(ttfb, (int, float)) else None,
            int(eou_delay * 1000) if isinstance(eou_delay, (int, float)) else None,
        )


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    room_name = ctx.room.name if ctx.room and ctx.room.name else "unknown-room"
    CALL_TRANSCRIPTS.pop(room_name, None)
    CALL_STARTED_AT[room_name] = utc_now_iso()

    llm_model = resolve_inference_llm_model()
    logger.info("Using LiveKit Inference LLM model=%s", llm_model)
    session = AgentSession(
        stt=build_stt(),
        llm=llm_model,
        tts=build_tts(),
        vad=silero.VAD.load(),
        preemptive_generation=True,
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
