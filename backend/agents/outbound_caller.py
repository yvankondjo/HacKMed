#!/usr/bin/env python3
"""
Outbound follow-up caller agent.
Dispatches from backend metadata and dials the patient over LiveKit SIP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from livekit import agents, api
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, RunContext, WorkerOptions, function_tool
from livekit.plugins import openai, silero, speechmatics

load_dotenv()

logger = logging.getLogger("medvoice.outbound")
BACKEND_API_BASE_URL = os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTBOUND_AGENT_NAME = (os.getenv("LIVEKIT_OUTBOUND_AGENT_NAME") or "outbound-caller").strip()
FOLLOWUP_TEST_PHONE = (os.getenv("FOLLOWUP_TEST_PHONE") or "0765540003").strip()
SIP_OUTBOUND_TRUNK_ID = (os.getenv("SIP_OUTBOUND_TRUNK_ID") or "").strip()


def _read_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default=%s", name, raw, default)
        return default


def _to_e164_fr(phone: str) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return raw
    if raw.startswith("+"):
        return "+" + "".join(ch for ch in raw[1:] if ch.isdigit())
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if digits.startswith("33"):
        return f"+{digits}"
    if len(digits) == 10 and digits.startswith("0"):
        return f"+33{digits[1:]}"
    return f"+{digits}"


def _extract_job_metadata(ctx: JobContext) -> dict[str, Any]:
    for source in (getattr(ctx, "job", None), getattr(ctx, "dispatch", None), getattr(ctx, "info", None)):
        if not source:
            continue
        for attr in ("metadata",):
            raw = getattr(source, attr, None)
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    continue
    return {}


def _build_stt():
    language = (os.getenv("OUTBOUND_STT_LANGUAGE") or os.getenv("STT_LANGUAGE") or "en").strip()
    configured_domain = (os.getenv("OUTBOUND_STT_DOMAIN") or os.getenv("STT_DOMAIN") or "medical").strip().lower()
    domain = "medical"
    if configured_domain and configured_domain != "medical":
        logger.warning(
            "OUTBOUND_STT_DOMAIN=%s requested, but outbound caller is configured for Speechmatics medical domain only.",
            configured_domain,
        )
    operating_point = (os.getenv("OUTBOUND_STT_OPERATING_POINT") or os.getenv("STT_OPERATING_POINT") or "enhanced").strip().lower()
    max_delay_raw = _read_float_env("OUTBOUND_STT_MAX_DELAY", 0.7)
    max_delay = min(4.0, max(0.7, max_delay_raw))
    if max_delay != max_delay_raw:
        logger.warning(
            "OUTBOUND_STT_MAX_DELAY=%s is outside Speechmatics allowed range [0.7, 4.0]; clamped to %s.",
            max_delay_raw,
            max_delay,
        )
    silence_trigger = _read_float_env("OUTBOUND_EOU_SILENCE", 0.35)

    language_kwargs: list[dict[str, str]] = [{key: language} for key in ("language", "language_code")] if language else [{}]
    for lang_kwargs in language_kwargs:
        attempts: list[dict[str, Any]] = [
            {**lang_kwargs, "domain": domain, "operating_point": operating_point, "max_delay": max_delay, "end_of_utterance_silence_trigger": silence_trigger},
            {**lang_kwargs, "domain": domain, "operating_point": operating_point},
            {**lang_kwargs, "domain": domain},
        ]
        for kwargs in attempts:
            try:
                stt = speechmatics.STT(**kwargs)
                return stt
            except (TypeError, ValueError):
                continue
    raise RuntimeError(
        "Speechmatics STT medical domain is required but unsupported in this SDK version."
    )


def _build_tts():
    provider = (os.getenv("TTS_PROVIDER") or "speechmatics").strip().lower()
    if provider and provider != "speechmatics":
        logger.warning(
            "TTS_PROVIDER=%s requested, but outbound caller is configured for Speechmatics TTS only.",
            provider,
        )
    speechmatics_tts = getattr(speechmatics, "TTS", None)
    if speechmatics_tts:
        voice = (os.getenv("SPEECHMATICS_VOICE") or "megan").strip() or "megan"
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
    speed = _read_float_env("OPENAI_TTS_SPEED", 1.0)
    try:
        return openai.TTS(model=model, voice=voice, speed=speed)
    except TypeError:
        return openai.TTS(model=model, voice=voice)


def _detect_symptoms_from_text(text: str) -> list[str]:
    lowered = text.lower()
    rules = {
        "Back pain": ("back pain", "back hurts", "lower back"),
        "Headache": ("headache", "migraine"),
        "Fever": ("fever", "temperature"),
        "Nausea": ("nausea", "vomit"),
        "Shortness of breath": ("shortness of breath", "breathing", "dyspnea"),
        "Chest pain": ("chest pain", "chest tightness"),
    }
    symptoms: list[str] = []
    for label, keywords in rules.items():
        if any(keyword in lowered for keyword in keywords):
            symptoms.append(label)
    return symptoms


def _guess_evolution(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("worse", "worsening", "not better", "more pain", "stronger pain")):
        return "worsening"
    if any(token in lowered for token in ("better", "improved", "improving", "less pain")):
        return "improvement"
    return "stable"


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class OutboundCallState:
    ctx: JobContext
    followup_call_id: str
    followup_task_id: str | None
    appointment_id: str | None
    patient_id: str
    patient_phone: str
    patient_name: str
    doctor_name: str
    dial_to: str
    question_plan: list[str]
    next_appointment_at: str | None
    started_monotonic: float = field(default_factory=time.monotonic)
    connected_monotonic: float | None = None
    sip_identity: str | None = None
    status: str = "completed"
    transcript: list[dict[str, str]] = field(default_factory=list)
    completion_sent: bool = False

    @property
    def duration_seconds(self) -> int:
        start = self.connected_monotonic or self.started_monotonic
        return max(0, int(time.monotonic() - start))


def _build_instructions(metadata: dict[str, Any], state: OutboundCallState) -> str:
    allergies = metadata.get("allergies") if isinstance(metadata.get("allergies"), list) else []
    antecedents = metadata.get("antecedents") if isinstance(metadata.get("antecedents"), list) else []
    medications = metadata.get("prescription_medications") if isinstance(metadata.get("prescription_medications"), list) else []
    advice = metadata.get("prescription_advice") if isinstance(metadata.get("prescription_advice"), list) else []

    meds_lines: list[str] = []
    for med in medications[:5]:
        if not isinstance(med, dict):
            continue
        name = str(med.get("name") or "").strip()
        if not name:
            continue
        dosage = str(med.get("dosage") or "").strip()
        frequency = str(med.get("frequency") or "").strip()
        duration = str(med.get("duration") or "").strip()
        parts = [name]
        if dosage:
            parts.append(dosage)
        if frequency:
            parts.append(frequency)
        if duration:
            parts.append(duration)
        meds_lines.append(" - " + " | ".join(parts))

    checklist = "\n".join(f" - {line}" for line in state.question_plan)
    return (
        "You are MedVoice Care Connect, a clinical follow-up voice assistant.\n"
        "Speak naturally and briefly, one question at a time.\n"
        "Language policy: conduct this call in English only.\n"
        "If the caller speaks another language, say exactly: "
        "\"Sorry, I can continue only in English. Could you please speak English?\"\n"
        "If the caller still does not speak English after 2 reminders, close politely with: "
        "\"I'm sorry, I can't continue this call in another language. Thank you for understanding. Goodbye.\"\n"
        "Goal: run a post-consultation follow-up call for medication adherence and safety.\n"
        f"Doctor: {state.doctor_name}\n"
        f"Patient: {state.patient_name}\n"
        f"Known allergies: {', '.join(allergies) if allergies else 'None recorded'}\n"
        f"Known antecedents: {', '.join(antecedents) if antecedents else 'None recorded'}\n"
        "Prescription medications:\n"
        f"{chr(10).join(meds_lines) if meds_lines else ' - No structured medication list available'}\n"
        f"Prescription advice: {', '.join(advice) if advice else 'None'}\n"
        f"Next appointment: {state.next_appointment_at or 'not scheduled'}\n"
        "Follow-up checklist:\n"
        f"{checklist}\n"
        "Conversation rules:\n"
        " - Confirm identity quickly before medical questions.\n"
        " - Ask if patient is following prescription.\n"
        " - Ask for side effects/allergic reactions.\n"
        " - Ask for new or worsening symptoms.\n"
        " - If next appointment exists, remind date/time.\n"
        " - Keep answers concise and empathetic.\n"
        " - Use tool end_call only when patient confirms call can end.\n"
        " - Use tool detected_answering_machine only if voicemail is clearly detected."
    )


async def _remove_sip_participant(state: OutboundCallState) -> None:
    if not state.sip_identity:
        return
    try:
        await state.ctx.api.room.remove_participant(
            api.RoomParticipantIdentity(
                room=state.ctx.room.name,
                identity=state.sip_identity,
            )
        )
    except Exception as exc:
        logger.warning("Failed to remove SIP participant %s: %s", state.sip_identity, exc)


def _serialize_transcript(state: OutboundCallState) -> list[dict[str, str]]:
    return [
        {
            "speaker": row["speaker"],
            "text": row["text"],
            "timestamp": row["timestamp"],
        }
        for row in state.transcript
        if row.get("text")
    ]


def _build_completion_payload(state: OutboundCallState) -> dict[str, Any]:
    transcript_payload = _serialize_transcript(state)
    patient_text = " ".join(
        row["text"] for row in state.transcript if row.get("speaker") == "Patient"
    )
    summary = " ".join(
        f"{row['speaker']}: {row['text']}" for row in state.transcript[-12:]
    )[:3200]
    symptoms = _detect_symptoms_from_text(patient_text)
    evolution = _guess_evolution(patient_text)
    recommendations = [
        "Continue treatment plan as prescribed by the doctor.",
        "Report any side effects or worsening symptoms quickly.",
    ]
    if state.next_appointment_at:
        recommendations.append(f"Keep the next appointment: {state.next_appointment_at}.")

    return {
        "followupCallId": state.followup_call_id,
        "followupTaskId": state.followup_task_id,
        "appointmentId": state.appointment_id,
        "patientId": state.patient_id,
        "patientPhone": state.patient_phone,
        "status": state.status,
        "durationSeconds": state.duration_seconds,
        "summary": summary or f"Outbound follow-up call status={state.status}.",
        "symptoms": symptoms,
        "recommendations": recommendations,
        "evolution": evolution,
        "transcript": transcript_payload,
    }


async def _post_completion(state: OutboundCallState) -> None:
    if state.completion_sent:
        return
    payload = _build_completion_payload(state)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{BACKEND_API_BASE_URL}/api/reminder/followup-call/complete",
                json=payload,
            )
            if response.status_code >= 400:
                logger.error(
                    "Failed to persist outbound follow-up completion status=%s body=%s",
                    response.status_code,
                    response.text[:400],
                )
            else:
                logger.info(
                    "Posted outbound completion followup_call_id=%s status=%s duration=%ss",
                    state.followup_call_id,
                    state.status,
                    state.duration_seconds,
                )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to post outbound completion: %s", exc)
    finally:
        state.completion_sent = True


def _attach_transcript_logging(session: AgentSession, state: OutboundCallState) -> None:
    @session.on("conversation_item_added")
    def on_conversation_item_added(event) -> None:
        item = getattr(event, "item", None)
        if not item:
            return
        text = (getattr(item, "text_content", "") or "").strip()
        if not text:
            return
        role = str(getattr(item, "role", "unknown")).upper()
        speaker = "AI"
        if role == "USER":
            speaker = "Patient"
        elif role in {"ASSISTANT", "SYSTEM"}:
            speaker = "Doctor"

        state.transcript.append(
            {
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info("[OUTBOUND][%s] %s", speaker, text)


class OutboundFollowupAgent(Agent):
    def __init__(self, *, state: OutboundCallState, metadata: dict[str, Any]):
        super().__init__(instructions=_build_instructions(metadata, state))
        self._state = state

    @function_tool()
    async def end_call(self, context: RunContext) -> str:
        """End the call once the patient confirms the conversation is complete."""
        elapsed = time.monotonic() - self._state.started_monotonic
        if elapsed < 20:
            return "Continue for a bit longer before ending the call."
        self._state.status = "completed"
        await _remove_sip_participant(self._state)
        return "Call ended."

    @function_tool()
    async def detected_answering_machine(self, context: RunContext) -> str:
        """Use only if voicemail/answering machine is clearly detected."""
        elapsed = time.monotonic() - self._state.started_monotonic
        if elapsed < 20:
            return "Do not end for voicemail too early. Wait and verify first."
        self._state.status = "voicemail"
        await _remove_sip_participant(self._state)
        return "Voicemail detected. Ending call."


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    metadata = _extract_job_metadata(ctx)
    followup_call_id = str(metadata.get("followup_call_id") or f"fup-{uuid4().hex[:12]}")
    appointment_id = str(metadata.get("appointment_id") or "").strip() or None
    patient_id = str(metadata.get("patient_id") or metadata.get("patient_phone") or "unknown-patient")
    patient_phone = str(metadata.get("patient_phone") or patient_id)
    patient_name = str(metadata.get("patient_name") or "Patient")
    doctor_name = str(metadata.get("doctor_name") or "Doctor")
    dial_to_raw = str(metadata.get("dial_to") or FOLLOWUP_TEST_PHONE)
    dial_to = _to_e164_fr(dial_to_raw)
    question_plan = [
        str(item).strip()
        for item in (metadata.get("question_plan") or [])
        if str(item).strip()
    ]
    if not question_plan:
        question_plan = [
            "Are you following your prescribed treatment?",
            "Have you noticed any side effects or allergies?",
            "Do you have any new symptoms?",
        ]

    state = OutboundCallState(
        ctx=ctx,
        followup_call_id=followup_call_id,
        followup_task_id=str(metadata.get("followup_task_id") or "").strip() or None,
        appointment_id=appointment_id,
        patient_id=patient_id,
        patient_phone=patient_phone,
        patient_name=patient_name,
        doctor_name=doctor_name,
        dial_to=dial_to,
        question_plan=question_plan,
        next_appointment_at=(
            str(metadata.get("next_appointment_at") or "").strip() or None
        ),
    )
    max_stale_age = int(float(os.getenv("OUTBOUND_STALE_JOB_MAX_SECONDS", "180")))
    queued_at = _parse_iso_datetime(str(metadata.get("queued_at") or ""))
    if queued_at and max_stale_age > 0:
        age_seconds = max(0, int((datetime.now(timezone.utc) - queued_at).total_seconds()))
        if age_seconds > max_stale_age:
            state.status = "failed"
            state.transcript.append(
                {
                    "speaker": "AI",
                    "text": f"Skipped stale outbound job aged {age_seconds}s.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.info(
                "Skipping stale outbound job followup_call_id=%s age=%ss max=%ss",
                state.followup_call_id,
                age_seconds,
                max_stale_age,
            )
            await _post_completion(state)
            return
    logger.info(
        "Outbound job started followup_call_id=%s room=%s dial_to=%s patient=%s",
        state.followup_call_id,
        ctx.room.name,
        state.dial_to,
        state.patient_phone,
    )

    async def _cleanup():
        await _post_completion(state)

    ctx.add_shutdown_callback(_cleanup)

    sip_identity: str | None = None
    existing_remote = list(ctx.room.remote_participants.keys())
    if existing_remote:
        sip_identity = existing_remote[0]
        state.sip_identity = sip_identity
        state.connected_monotonic = time.monotonic()
        logger.info("Using existing remote participant for outbound call: %s", sip_identity)
    else:
        trunk_id = str(metadata.get("sip_trunk_id") or SIP_OUTBOUND_TRUNK_ID).strip()
        if not trunk_id:
            state.status = "failed"
            logger.warning(
                "Missing SIP_OUTBOUND_TRUNK_ID for followup_call_id=%s room=%s",
                state.followup_call_id,
                ctx.room.name,
            )
            state.transcript.append(
                {
                    "speaker": "AI",
                    "text": "Missing SIP_OUTBOUND_TRUNK_ID and no SIP participant found in room.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await _post_completion(state)
            return

        sip_identity = f"sip-{uuid4().hex[:10]}"
        state.sip_identity = sip_identity

        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=trunk_id,
                    sip_call_to=dial_to,
                    participant_identity=sip_identity,
                    participant_name=patient_name,
                    wait_until_answered=True,
                )
            )
            state.connected_monotonic = time.monotonic()
        except Exception as exc:
            state.status = "failed"
            logger.exception("Outbound dial failed for followup_call_id=%s: %s", state.followup_call_id, exc)
            state.transcript.append(
                {
                    "speaker": "AI",
                    "text": f"Outbound dial failed: {exc}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await _post_completion(state)
            return

    session = AgentSession(
        stt=_build_stt(),
        llm=openai.LLM(model=os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")),
        tts=_build_tts(),
        vad=silero.VAD.load(),
    )
    _attach_transcript_logging(session, state)
    await session.start(
        room=ctx.room,
        agent=OutboundFollowupAgent(state=state, metadata=metadata),
        room_input_options=RoomInputOptions(participant_identity=sip_identity),
    )

    greeting = (
        f"Hello {patient_name}, this is {doctor_name}'s MedVoice assistant for your follow-up. "
        "Is now a good time for a quick medical check-in?"
    )
    await session.say(greeting, allow_interruptions=False)

    disconnected = asyncio.Event()

    def _on_participant_disconnected(participant) -> None:
        if getattr(participant, "identity", None) == sip_identity:
            disconnected.set()

    ctx.room.on("participant_disconnected", _on_participant_disconnected)
    try:
        await disconnected.wait()
    finally:
        ctx.room.off("participant_disconnected", _on_participant_disconnected)

    await _post_completion(state)


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=OUTBOUND_AGENT_NAME,
        )
    )


if __name__ == "__main__":
    run()
