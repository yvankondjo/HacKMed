#!/usr/bin/env python3
"""
Consultation Agent - LiveKit + Speechmatics STT
- The agent joins a LiveKit room.
- It creates 1 AgentSession per remote participant (multi-user transcriber pattern).
- Each final turn is stored, then:
  - Generates follow-up questions for the doctor (debounced).
  - Generates a SOAP summary when the frontend sends an "end_session" command.
"""

from __future__ import annotations

import asyncio
import json
import re
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    StopResponse,
    cli,
    inference,
    llm,
    room_io,
    utils,
)
from livekit.plugins import silero, speechmatics

try:
    from livekit.plugins.turn_detector.multilingual import MultilingualModel
except ImportError:
    # Fallback to EOVad if multilingual not available
    import livekit.plugins.turn_detector.eovad as eovad

    MultilingualModel = eovad.EOVad

load_dotenv()

logger = logging.getLogger("medvoice.consultation")

AGENT_NAME = os.getenv("AGENT_NAME", "medvoice-consultation")
SCRIBE_LLM_MODEL = os.getenv("SCRIBE_LLM_MODEL", "gpt-4o-mini")
SCRIBE_LANGUAGE = os.getenv("SCRIBE_LANGUAGE", "fr")

TOPIC_CONTROL = "clinic.control"  # frontend -> agent
TOPIC_SUGGESTIONS = "clinic.suggestions"  # agent -> frontend
TOPIC_SOAP = "clinic.soap"  # agent -> frontend
TOPIC_TRANSCRIPT = "clinic.transcript"  # agent -> frontend (parsed transcript)

# Mapping: Speechmatics assigns S1 to the first speaker detected, S2 to the second.
# Convention: S1 = Doctor (primary), S2 = Patient.
SPEAKER_ROLE_MAP: dict[str, str] = {
    "S1": "doctor",
    "S2": "patient",
}

_SPEAKER_TAG_RE = re.compile(r"<(S\d+)>(.*?)</\1>", re.DOTALL)


@dataclass
class Turn:
    ts: float
    speaker: str
    text: str


class ParticipantTranscriber(Agent):
    """
    Lightweight agent that ONLY:
    - listens to 1 participant
    - captures final text turn
    - passes to manager
    - stops generation (no conversational reply)
    """

    def __init__(self, *, participant_identity: str, manager: "ClinicScribeManager"):
        super().__init__(instructions="")
        self.participant_identity = participant_identity
        self.manager = manager

    async def on_user_turn_completed(
        self, chat_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ):
        text = (new_message.text_content or "").strip()
        if text:
            await self.manager.on_final_transcript(self.participant_identity, text)
        raise StopResponse()


class ClinicScribeManager:
    """
    Manages:
    - session creation/closing per participant
    - transcript storage
    - debounced question generation
    - final SOAP generation on demand
    """

    def __init__(self, ctx: JobContext):
        self.ctx = ctx
        self.room = ctx.room

        self._sessions: dict[str, AgentSession] = {}
        self._tasks: set[asyncio.Task] = set()

        self._turns: list[Turn] = []
        self._roles: dict[str, str] = {}

        # Use LiveKit inference or direct OpenAI if configured
        import livekit.plugins.openai as openai_plugin

        self._llm = openai_plugin.LLM(model=SCRIBE_LLM_MODEL)

        self._suggest_task: asyncio.Task | None = None
        self._suggest_delay_s = 2.0

        self._active_text_tasks: set[asyncio.Task] = set()

    def start(self):
        self.room.on("participant_connected", self.on_participant_connected)
        self.room.on("participant_disconnected", self.on_participant_disconnected)
        self._register_control_handler()

    async def aclose(self):
        self.room.off("participant_connected", self.on_participant_connected)
        self.room.off("participant_disconnected", self.on_participant_disconnected)

        if self._suggest_task:
            self._suggest_task.cancel()
            await utils.aio.cancel_and_wait(self._suggest_task)
            self._suggest_task = None

        await utils.aio.cancel_and_wait(*self._tasks)
        await asyncio.gather(
            *[self._close_session(sess) for sess in self._sessions.values()],
            return_exceptions=True,
        )
        # LLM from OpenAI plugin doesn't need strict aclose, but good to have if inference plugin used

    def on_participant_connected(self, participant: rtc.RemoteParticipant):
        if participant.identity in self._sessions:
            return

        identity = participant.identity.lower()
        if "doc" in identity or "dr" in identity or "med" in identity:
            self._roles[participant.identity] = "doctor"
        elif "patient" in identity:
            self._roles[participant.identity] = "patient"
        else:
            self._roles[participant.identity] = "unknown"

        logger.info("Starting STT session for %s", participant.identity)
        task = asyncio.create_task(self._start_session(participant))
        self._tasks.add(task)

        def _done(t: asyncio.Task):
            try:
                self._sessions[participant.identity] = t.result()
            finally:
                self._tasks.discard(t)

        task.add_done_callback(_done)

    def on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        sess = self._sessions.pop(participant.identity, None)
        if not sess:
            return
        logger.info("Closing STT session for %s", participant.identity)
        task = asyncio.create_task(self._close_session(sess))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(t))

    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        stt = speechmatics.STT(
            language=SCRIBE_LANGUAGE,
            enable_diarization=True,
            speaker_active_format="<{speaker_id}>{text}</{speaker_id}>",
        )

        session = AgentSession(
            stt=stt,
            vad=self.ctx.proc.userdata["vad"],
            turn_detection=MultilingualModel(),
        )

        await session.start(
            agent=ParticipantTranscriber(
                participant_identity=participant.identity, manager=self
            ),
            room=self.room,
            room_options=room_io.RoomOptions(
                audio_input=True,
                audio_output=False,
                text_output=True,
                text_input=False,
                participant_identity=participant.identity,
            ),
        )
        return session

    async def _close_session(self, sess: AgentSession):
        await sess.drain()
        await sess.aclose()

    async def on_final_transcript(self, speaker_identity: str, text: str):
        # Parse diarization tags like <S1>Bonjour</S1> from Speechmatics
        speaker_id, clean_text = _parse_speaker_tag(text)

        if speaker_id:
            role = SPEAKER_ROLE_MAP.get(speaker_id, "unknown")
        else:
            # Fallback: use participant identity heuristic
            role = self._roles.get(speaker_identity, "unknown")
            clean_text = text

        self._turns.append(Turn(ts=time.time(), speaker=role, text=clean_text))

        logger.info(
            "[%s/%s] %s: %s", speaker_id or "?", role, speaker_identity, clean_text
        )
        self._trigger_suggestions()

        # Send parsed transcript entry to frontend so it knows the speaker role
        await self._send_json(
            topic=TOPIC_TRANSCRIPT,
            payload={
                "type": "transcript",
                "speaker": "Doctor" if role == "doctor" else "Patient",
                "text": clean_text,
                "speaker_id": speaker_id or "unknown",
                "timestamp": time.time(),
            },
        )

    def _trigger_suggestions(self):
        if self._suggest_task and not self._suggest_task.done():
            self._suggest_task.cancel()
        self._suggest_task = asyncio.create_task(self._suggestions_after_delay())

    async def _suggestions_after_delay(self):
        try:
            await asyncio.sleep(self._suggest_delay_s)
            payload = await self._generate_questions_payload()
            await self._send_json(topic=TOPIC_SUGGESTIONS, payload=payload)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("Suggestion generation failed: %s", e)

    async def _generate_questions_payload(self) -> dict[str, Any]:
        if len(self._turns) < 2:
            return {"type": "suggestions", "questions": [], "missing_info": []}

        recent = self._format_recent_turns(max_turns=14, max_chars=4000)

        system = (
            "You are an assistant helping a physician during a consultation.\\n"
            "Task: propose short, high-signal follow-up questions the physician may ask next.\\n"
            "Rules:\\n"
            "- Do NOT diagnose.\\n"
            "- Do NOT recommend medication.\\n"
            "- Keep it concise.\\n"
            "- Return STRICT JSON with keys: questions (array of strings), missing_info (array of strings).\\n"
        )

        user = f"Conversation so far:\\n{recent}\\n\\nReturn JSON."

        chat = (
            llm.ChatContext()
            .append(role="system", text=system)
            .append(role="user", text=user)
        )

        try:
            resp = await self._llm.chat(chat_ctx=chat).collect()
            # fallback basic parse
            text = resp.content or "{}"
            data = _safe_json(text) or {"questions": [], "missing_info": []}
        except Exception as e:
            logger.error(f"Failed to generate questions: {e}")
            data = {"questions": [], "missing_info": []}

        questions = [
            q.strip()
            for q in data.get("questions", [])
            if isinstance(q, str) and q.strip()
        ]
        missing = [
            m.strip()
            for m in data.get("missing_info", [])
            if isinstance(m, str) and m.strip()
        ]

        return {
            "type": "suggestions",
            "questions": questions[:5],
            "missing_info": missing[:5],
            "updated_at": time.time(),
        }

    def _format_recent_turns(self, *, max_turns: int, max_chars: int) -> str:
        turns = self._turns[-max_turns:]
        lines = [f"- {t.speaker}: {t.text}" for t in turns]
        s = "\\n".join(lines)
        return s[-max_chars:]

    async def finalize_and_send_soap(self):
        recent = self._format_recent_turns(max_turns=100, max_chars=12000)

        system = (
            "You are a medical scribe assistant.\\n"
            "Create a structured SOAP note from the transcript.\\n"
            "Rules:\\n"
            "- Do NOT diagnose.\\n"
            "- Do NOT prescribe or recommend new medications.\\n"
            "- You may list medications ONLY if explicitly mentioned in the transcript.\\n"
            "- Output STRICT JSON with keys:\\n"
            "  soap: {subjective, objective, assessment, plan}\\n"
            "  meds_mentioned: array of strings\\n"
            "  followups: array of strings\\n"
            "  safety_checks: array of strings\\n"
        )

        user = f"Transcript:\\n{recent}\\n\\nReturn JSON."
        chat = (
            llm.ChatContext()
            .append(role="system", text=system)
            .append(role="user", text=user)
        )

        resp = await self._llm.chat(chat_ctx=chat).collect()
        data = _safe_json(resp.content) or {}

        payload = {
            "type": "soap",
            "soap": data.get("soap", {}),
            "meds_mentioned": data.get("meds_mentioned", []),
            "followups": data.get("followups", []),
            "safety_checks": data.get("safety_checks", []),
            "updated_at": time.time(),
        }

        await self._send_json(topic=TOPIC_SOAP, payload=payload)

    def _register_control_handler(self):
        async def async_handle(reader, participant_identity: str):
            try:
                text = await reader.read_all()
                msg = _safe_json(text) or {}
                mtype = msg.get("type")

                if mtype == "end_session":
                    logger.info("Received end_session from %s", participant_identity)
                    await self.finalize_and_send_soap()

                elif mtype == "set_role":
                    identity = msg.get("identity")
                    role = msg.get("role")
                    if isinstance(identity, str) and role in (
                        "doctor",
                        "patient",
                        "unknown",
                    ):
                        self._roles[identity] = role
                        logger.info("Role updated: %s -> %s", identity, role)

            except Exception as e:
                logger.exception("control handler failed: %s", e)

        def handle(reader, participant_identity: str):
            task = asyncio.create_task(async_handle(reader, participant_identity))
            self._active_text_tasks.add(task)
            task.add_done_callback(lambda t: self._active_text_tasks.discard(t))

        self.room.register_text_stream_handler(TOPIC_CONTROL, handle)

    async def _send_json(self, *, topic: str, payload: dict[str, Any]):
        text = json.dumps(payload, ensure_ascii=False)
        await self.room.local_participant.send_text(text, topic=topic)


def _parse_speaker_tag(text: str) -> tuple[str | None, str]:
    """Extract speaker_id and clean text from '<S1>hello</S1>' format.

    Returns (speaker_id, clean_text). If no tag found, returns (None, original_text).
    """
    m = _SPEAKER_TAG_RE.search(text)
    if m:
        return m.group(1), m.group(2).strip()
    return None, text.strip()


def _safe_json(s: str) -> dict[str, Any] | None:
    s = (s or "").strip()
    if not s:
        return None
    if not s.startswith("{"):
        i = s.find("{")
        j = s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i : j + 1]
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name, "agent": AGENT_NAME}

    manager = ClinicScribeManager(ctx)
    manager.start()

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    for p in ctx.room.remote_participants.values():
        manager.on_participant_connected(p)

    async def _cleanup():
        await manager.aclose()

    ctx.add_shutdown_callback(_cleanup)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)