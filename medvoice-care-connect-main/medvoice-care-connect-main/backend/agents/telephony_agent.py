#!/usr/bin/env python3
"""
Telephony Voice Assistant - LiveKit SIP + Twilio + Speechmatics.
"""

from __future__ import annotations

import os
from pathlib import Path
import logging

import httpx
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions, RunContext, WorkerOptions, function_tool
from livekit.plugins import openai, silero, speechmatics

load_dotenv()

REQUIRED_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
BACKEND_API_BASE_URL = os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
logger = logging.getLogger("medvoice.telephony")


def validate_required_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")


def load_agent_prompt() -> str:
    agent_file = Path(__file__).parent.parent / "assets" / "agent.md"
    if agent_file.exists():
        return agent_file.read_text(encoding="utf-8")
    return "You are a helpful voice assistant. Be concise and friendly."


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
    return openai.TTS(model=model, voice=voice)


class VoiceAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=load_agent_prompt())

    @function_tool()
    async def book_consultation_with_confirmation(
        self,
        context: RunContext,
        patient_id: str,
        patient_name: str,
        patient_phone: str,
        patient_email: str,
        reason: str,
        starts_at_iso: str,
        timezone: str = "Europe/Paris",
    ) -> str:
        """Create a consultation booking in Cal.com and send Twilio SMS confirmation."""
        payload = {
            "patientId": patient_id,
            "patientName": patient_name,
            "patientPhone": patient_phone,
            "patientEmail": patient_email,
            "reason": reason,
            "startsAt": starts_at_iso,
            "timezone": timezone,
        }

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(f"{BACKEND_API_BASE_URL}/api/booking/calcom", json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:  # pragma: no cover
            return f"Booking failed: {exc}"

        appointment_id = body.get("appointmentId", "unknown")
        sms_status = body.get("smsStatus", "unknown")
        meeting_url = body.get("meetingUrl")
        link_part = f" Meeting link: {meeting_url}." if meeting_url else ""
        return (
            f"Booking completed. Appointment ID: {appointment_id}. "
            f"SMS status: {sms_status}.{link_part}"
        )


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()

    session = AgentSession(
        stt=speechmatics.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=build_tts(),
        vad=silero.VAD.load(),
    )

    await session.start(
        room=ctx.room,
        agent=VoiceAssistant(),
        room_input_options=RoomInputOptions(),
    )

    await session.generate_reply(
        instructions="Say a short hello, identify MedVoice, and ask how you can help."
    )


def run() -> None:
    validate_required_env()
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="medvoice-telephony",
        )
    )


if __name__ == "__main__":
    run()
