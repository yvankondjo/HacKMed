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
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomOutputOptions,
    StopResponse,
    WorkerOptions,
    cli,
    llm,
    utils,
)
from livekit.plugins import silero, speechmatics

load_dotenv()

logger = logging.getLogger("medvoice.consultation")

AGENT_NAME = os.getenv("AGENT_NAME", "medvoice-consultation")
SCRIBE_LLM_MODEL = os.getenv("SCRIBE_LLM_MODEL", "gpt-4o-mini")
SCRIBE_LANGUAGE = os.getenv("SCRIBE_LANGUAGE", "fr")

TOPIC_CONTROL = "clinic.control"  # frontend -> agent
TOPIC_TRANSCRIPT = "clinic.transcript"  # agent -> frontend
TOPIC_SUGGESTIONS = "clinic.suggestions"  # agent -> frontend
TOPIC_SOAP = "clinic.soap"  # agent -> frontend

SPEAKER_ROLE_MAP: dict[str, str] = {
    "S1": "doctor",
    "S2": "patient",
}

_DOCTOR_ROLE_RE = re.compile(
    r"(?:^|[^a-z])(doc|doctor|dr|physician|medic|clinician)(?:[^a-z]|$)"
)
_PATIENT_ROLE_RE = re.compile(r"(?:^|[^a-z])(patient|pat|caller)(?:[^a-z]|$)")
_SPEAKER_TAG_RE = re.compile(r"<(S\d+)>(.*?)</\1>", re.DOTALL)


def _normalize_role(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"doctor", "doc", "dr", "physician", "medic", "clinician"}:
        return "doctor"
    if text in {"patient", "pat", "caller"}:
        return "patient"
    return "unknown"


def _infer_role_from_text(value: str) -> str:
    lowered = (value or "").lower()
    if _DOCTOR_ROLE_RE.search(lowered):
        return "doctor"
    if _PATIENT_ROLE_RE.search(lowered):
        return "patient"
    return "unknown"


def _infer_participant_role(participant: rtc.RemoteParticipant) -> str:
    attributes = getattr(participant, "attributes", None)
    if isinstance(attributes, dict):
        for key in ("role", "participant_role", "type"):
            raw_value = attributes.get(key)
            if isinstance(raw_value, str):
                role = _normalize_role(raw_value)
                if role != "unknown":
                    return role

    for raw_value in (
        getattr(participant, "identity", ""),
        getattr(participant, "name", ""),
        getattr(participant, "metadata", ""),
    ):
        if isinstance(raw_value, str) and raw_value.strip():
            role = _infer_role_from_text(raw_value)
            if role != "unknown":
                return role

    return "unknown"


def _parse_speaker_tag(text: str) -> tuple[str | None, str]:
    match = _SPEAKER_TAG_RE.search(text or "")
    if match:
        return match.group(1), match.group(2).strip()
    return None, (text or "").strip()


def _extract_tagged_segments(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for match in _SPEAKER_TAG_RE.finditer(text or ""):
        speaker_id = match.group(1)
        clean = match.group(2).strip()
        if clean:
            segments.append((speaker_id, clean))
    return segments


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


async def _collect_llm_text(stream: Any) -> str:
    if stream is None:
        return ""

    if hasattr(stream, "collect"):
        response = await stream.collect()
        for attr in ("text", "content", "output_text", "text_content"):
            value = getattr(response, attr, None)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, list):
                joined = "".join(str(item) for item in value if item is not None)
                if joined.strip():
                    return joined
        return ""

    chunks: list[str] = []
    try:
        if hasattr(stream, "to_str_iterable"):
            async for part in stream.to_str_iterable():
                if part:
                    chunks.append(str(part))
        else:
            async for chunk in stream:
                delta = getattr(chunk, "delta", None)
                text_part = None
                if delta is not None:
                    text_part = getattr(delta, "content", None) or getattr(
                        delta, "text", None
                    )
                if text_part is None:
                    text_part = getattr(chunk, "content", None) or getattr(
                        chunk, "text", None
                    )
                if isinstance(text_part, list):
                    text_part = "".join(str(item) for item in text_part)
                if text_part:
                    chunks.append(str(text_part))
    finally:
        if hasattr(stream, "aclose"):
            await stream.aclose()

    return "".join(chunks)


@dataclass
class Turn:
    ts: float
    speaker: str
    text: str


@dataclass
class PendingTurn:
    ts: float
    speaker_identity: str
    role: str
    speaker_id: str
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

        import livekit.plugins.openai as openai_plugin

        self._llm = openai_plugin.LLM(model=SCRIBE_LLM_MODEL)

        self._suggest_task: asyncio.Task | None = None
        self._suggest_delay_s = 2.0

        self._active_text_tasks: set[asyncio.Task] = set()
        self._pending_turn: PendingTurn | None = None
        self._pending_flush_task: asyncio.Task | None = None
        self._merge_window_s = 1.2
        self._flush_delay_s = 0.8
        self._max_merged_chars = 420

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

        if self._pending_flush_task:
            self._pending_flush_task.cancel()
            await utils.aio.cancel_and_wait(self._pending_flush_task)
            self._pending_flush_task = None
        await self._flush_pending_turn()

        await utils.aio.cancel_and_wait(*self._tasks)
        await asyncio.gather(
            *[self._close_session(sess) for sess in self._sessions.values()],
            return_exceptions=True,
        )

    def on_participant_connected(self, participant: rtc.RemoteParticipant):
        if participant.identity in self._sessions:
            return

        self._roles[participant.identity] = _infer_participant_role(participant)

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
        pending = self._pending_turn
        if pending and pending.speaker_identity == participant.identity:
            task = asyncio.create_task(self._flush_pending_turn())
            self._tasks.add(task)
            task.add_done_callback(lambda t: self._tasks.discard(t))
        if not sess:
            return
        logger.info("Closing STT session for %s", participant.identity)
        task = asyncio.create_task(self._close_session(sess))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(t))

    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        # Diarization is required when doctor+patient voices are captured in one room stream.
        try:
            stt = speechmatics.STT(
                language=SCRIBE_LANGUAGE,
                enable_partials=True,
                enable_diarization=True,
                speaker_active_format="<{speaker_id}>{text}</{speaker_id}>",
            )
        except TypeError:
            try:
                stt = speechmatics.STT(
                    language=SCRIBE_LANGUAGE,
                    enable_partials=True,
                    enable_diarization=True,
                )
            except TypeError:
                stt = speechmatics.STT(
                    language=SCRIBE_LANGUAGE,
                    enable_partials=True,
                )

        session = AgentSession(
            stt=stt,
            vad=self.ctx.proc.userdata["vad"],
        )

        await session.start(
            agent=ParticipantTranscriber(
                participant_identity=participant.identity, manager=self
            ),
            room=self.room,
            room_input_options=RoomInputOptions(
                audio_enabled=True,
                text_enabled=False,
                participant_identity=participant.identity,
            ),
            room_output_options=RoomOutputOptions(
                audio_enabled=False,
                transcription_enabled=False,
            ),
        )
        return session

    async def _close_session(self, sess: AgentSession):
        await sess.drain()
        await sess.aclose()

    @staticmethod
    def _merge_text(previous: str, current: str) -> str:
        left = (previous or "").strip()
        right = (current or "").strip()
        if not left:
            return right
        if not right:
            return left
        if left.lower() == right.lower():
            return left
        merged = f"{left} {right}".strip()
        return re.sub(r"\s+([,.;:?!])", r"\1", merged)

    def _same_pending_speaker(
        self,
        pending: PendingTurn,
        *,
        speaker_identity: str,
        role: str,
        speaker_id: str,
        ts: float,
        new_text: str,
    ) -> bool:
        if pending.speaker_identity != speaker_identity:
            return False
        if pending.role != role:
            return False
        if speaker_id and pending.speaker_id and speaker_id != pending.speaker_id:
            return False
        if (ts - pending.ts) > self._merge_window_s:
            return False
        if len(pending.text) + len(new_text) + 1 > self._max_merged_chars:
            return False
        return True

    def _schedule_pending_flush(self):
        if self._pending_flush_task and not self._pending_flush_task.done():
            self._pending_flush_task.cancel()
        self._pending_flush_task = asyncio.create_task(self._flush_pending_after_delay())

    async def _flush_pending_after_delay(self):
        try:
            await asyncio.sleep(self._flush_delay_s)
            await self._flush_pending_turn()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("pending transcript flush failed: %s", e)

    async def _flush_pending_turn(self):
        pending = self._pending_turn
        if not pending:
            return
        self._pending_turn = None

        turn = Turn(
            ts=pending.ts,
            speaker=f"{pending.speaker_identity}({pending.role})",
            text=pending.text,
        )
        self._turns.append(turn)

        logger.info("%s [%s]: %s", pending.speaker_identity, pending.role, pending.text)
        await self._send_json(
            topic=TOPIC_TRANSCRIPT,
            payload={
                "type": "transcript",
                "speaker": "Doctor" if pending.role == "doctor" else "Patient",
                "speaker_role": pending.role,
                "text": pending.text,
                "speaker_id": pending.speaker_id or "unknown",
                "timestamp": pending.ts,
            },
        )
        self._trigger_suggestions()

    async def on_final_transcript(self, speaker_identity: str, text: str):
        base_role = self._roles.get(speaker_identity, "unknown")
        tagged_segments = _extract_tagged_segments(text)

        if tagged_segments:
            segments = tagged_segments
        else:
            logger.info(
                "No diarization tags for %s; using participant role fallback.",
                speaker_identity,
            )
            speaker_id, clean = _parse_speaker_tag(text)
            if speaker_id and clean:
                segments = [(speaker_id, clean)]
            else:
                segments = [("", (text or "").strip())]

        added_any = False
        for speaker_id, clean_text in segments:
            clean_text = (clean_text or "").strip()
            if not clean_text:
                continue

            role = SPEAKER_ROLE_MAP.get(speaker_id, base_role)
            if role not in {"doctor", "patient"}:
                role = "patient"

            ts = time.time()
            pending = self._pending_turn
            if pending and self._same_pending_speaker(
                pending,
                speaker_identity=speaker_identity,
                role=role,
                speaker_id=speaker_id,
                ts=ts,
                new_text=clean_text,
            ):
                pending.text = self._merge_text(pending.text, clean_text)
                pending.ts = ts
                if speaker_id and not pending.speaker_id:
                    pending.speaker_id = speaker_id
            else:
                await self._flush_pending_turn()
                self._pending_turn = PendingTurn(
                    ts=ts,
                    speaker_identity=speaker_identity,
                    role=role,
                    speaker_id=speaker_id,
                    text=clean_text,
                )

            self._schedule_pending_flush()
            added_any = True

        if added_any:
            return

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
            "You are an assistant helping a physician during a consultation.\n"
            "Task: propose short, high-signal follow-up questions the physician may ask next.\n"
            "Rules:\n"
            "- Do NOT diagnose.\n"
            "- Do NOT recommend medication.\n"
            "- Keep it concise.\n"
            "- Return STRICT JSON with keys: questions (array of strings), missing_info (array of strings).\n"
        )

        user = f"Conversation so far:\n{recent}\n\nReturn JSON."

        chat = llm.ChatContext()
        chat.add_message(role="system", content=system)
        chat.add_message(role="user", content=user)

        try:
            stream = self._llm.chat(chat_ctx=chat)
            text = await _collect_llm_text(stream)
            data = _safe_json(text) or {"questions": [], "missing_info": []}
        except Exception as e:
            logger.error("Failed to generate questions: %s", e)
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
        s = "\n".join(lines)
        return s[-max_chars:]

    async def finalize_and_send_soap(self):
        await self._flush_pending_turn()
        recent = self._format_recent_turns(max_turns=100, max_chars=12000)

        system = (
            "You are a medical scribe assistant.\n"
            "Create a structured SOAP note from the transcript.\n"
            "Rules:\n"
            "- Do NOT diagnose.\n"
            "- Do NOT prescribe or recommend new medications.\n"
            "- You may list medications ONLY if explicitly mentioned in the transcript.\n"
            "- Output STRICT JSON with keys:\n"
            "  soap: {subjective, objective, assessment, plan}\n"
            "  meds_mentioned: array of strings\n"
            "  followups: array of strings\n"
            "  safety_checks: array of strings\n"
        )

        user = f"Transcript:\n{recent}\n\nReturn JSON."
        chat = llm.ChatContext()
        chat.add_message(role="system", content=system)
        chat.add_message(role="user", content=user)

        try:
            stream = self._llm.chat(chat_ctx=chat)
            text = await _collect_llm_text(stream)
            data = _safe_json(text) or {}
        except Exception as e:
            logger.exception("SOAP generation failed: %s", e)
            data = {}

        payload = {
            "type": "soap",
            "soap": data.get("soap", {}) if isinstance(data.get("soap"), dict) else {},
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
                    role = _normalize_role(msg.get("role"))
                    if isinstance(identity, str) and role in (
                        "doctor",
                        "patient",
                        "unknown",
                    ):
                        self._roles[identity] = role
                        logger.info("Role updated: %s -> %s", identity, role)

                elif mtype == "set_context":
                    # frontend sends this; not required by this minimal working flow.
                    pass

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


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name, "agent": AGENT_NAME}

    manager = ClinicScribeManager(ctx)
    manager.start()

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    for participant in ctx.room.remote_participants.values():
        manager.on_participant_connected(participant)

    async def _cleanup():
        await manager.aclose()

    ctx.add_shutdown_callback(_cleanup)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=AGENT_NAME,
        )
    )


if __name__ == "__main__":
    run()
