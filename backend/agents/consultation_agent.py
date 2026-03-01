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
SCRIBE_LANGUAGE = os.getenv("SCRIBE_LANGUAGE", "en")

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
_DOCTOR_ROLE_RE = re.compile(r"(?:^|[^a-z])(doc|doctor|dr|physician|medic|clinician)(?:[^a-z]|$)")
_PATIENT_ROLE_RE = re.compile(r"(?:^|[^a-z])(patient|pat|caller)(?:[^a-z]|$)")


def _read_bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning("Invalid boolean for %s=%r; using default=%s", name, raw, default)
    return default


def _read_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default=%s", name, raw, default)
        return default


def _read_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r; using default=%s", name, raw, default)
        return default


def _normalize_role(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"doctor", "doc", "dr", "physician", "medic", "clinician"}:
        return "doctor"
    if text in {"patient", "pat", "caller"}:
        return "patient"
    if text in {"other", "noise", "unknown"}:
        return "other" if text == "other" else "unknown"
    return "unknown"


def _infer_role_from_text(value: str) -> str:
    lowered = value.lower()
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


def _build_consultation_stt(*, enable_diarization_override: bool | None = None):
    language = (SCRIBE_LANGUAGE or "").strip()
    domain = (os.getenv("CONSULTATION_STT_DOMAIN") or os.getenv("STT_DOMAIN") or "medical").strip().lower()
    operating_point = (
        os.getenv("CONSULTATION_STT_OPERATING_POINT") or os.getenv("STT_OPERATING_POINT") or "enhanced"
    ).strip().lower()
    enable_diarization_default = _read_bool_env("CONSULTATION_ENABLE_DIARIZATION", False)
    enable_diarization = (
        enable_diarization_override
        if enable_diarization_override is not None
        else enable_diarization_default
    )
    include_partials = _read_bool_env("CONSULTATION_INCLUDE_PARTIALS", False)
    max_delay = _read_float_env("CONSULTATION_STT_MAX_DELAY", 0.9)
    diarization_sensitivity = _read_float_env("CONSULTATION_DIARIZATION_SENSITIVITY", 0.75)
    end_of_utterance_silence_trigger = _read_float_env("CONSULTATION_EOU_SILENCE_TRIGGER", 0.4)
    prefer_current_speaker = _read_bool_env("CONSULTATION_PREFER_CURRENT_SPEAKER", False)
    speaker_active_format = (
        os.getenv("CONSULTATION_SPEAKER_ACTIVE_FORMAT", "<{speaker_id}>{text}</{speaker_id}>") or ""
    ).strip()

    language_kwargs: list[dict[str, str]] = [{key: language} for key in ("language", "language_code")] if language else [{}]

    base_kwargs_common: dict[str, Any] = {
        "max_delay": max_delay,
        "end_of_utterance_silence_trigger": end_of_utterance_silence_trigger,
        "enable_diarization": enable_diarization,
        "prefer_current_speaker": prefer_current_speaker,
    }
    if domain:
        base_kwargs_common["domain"] = domain
    if operating_point:
        base_kwargs_common["operating_point"] = operating_point
    if enable_diarization and speaker_active_format:
        base_kwargs_common["speaker_active_format"] = speaker_active_format
        base_kwargs_common["diarization_sensitivity"] = diarization_sensitivity

    partial_keys = {"enable_partials", "include_partials"}
    for partial_key in ("enable_partials", "include_partials", ""):
        base_kwargs = dict(base_kwargs_common)
        if partial_key:
            base_kwargs[partial_key] = include_partials
        for lang_kwargs in language_kwargs:
            attempts: list[dict[str, Any]] = [
                {**lang_kwargs, **base_kwargs},
                {**lang_kwargs, **{k: v for k, v in base_kwargs.items() if k not in partial_keys}},
                {**lang_kwargs, **{k: v for k, v in base_kwargs.items() if k not in (partial_keys | {"max_delay"})}},
                {**lang_kwargs, **{k: v for k, v in base_kwargs.items() if k != "speaker_active_format"}},
                {**lang_kwargs, **{k: v for k, v in base_kwargs.items() if k not in {"enable_diarization", "speaker_active_format"}}},
                dict(lang_kwargs),
            ]
            for kwargs in attempts:
                try:
                    stt = speechmatics.STT(**kwargs)
                    logger.info(
                        "Speechmatics STT configured language=%s domain=%s operating_point=%s diarization=%s max_delay=%s",
                        kwargs.get("language") or kwargs.get("language_code") or "default",
                        kwargs.get("domain", "default"),
                        kwargs.get("operating_point", "default"),
                        kwargs.get("enable_diarization", "default"),
                        kwargs.get("max_delay", "default"),
                    )
                    return stt
                except TypeError:
                    continue

    logger.warning("speechmatics.STT does not accept consultation overrides in this SDK; using default config.")
    return speechmatics.STT()


def _is_benign_speechmatics_close(context: dict[str, Any]) -> bool:
    """
    Speechmatics can emit a late timer callback during teardown after a channel closes.
    This is noisy but not fatal for consultation completion.
    """
    exc = context.get("exception")
    if exc is None or exc.__class__.__name__ != "ChanClosed":
        return False

    message = str(context.get("message") or "")
    handle_text = str(context.get("handle") or "")
    joined = f"{message} {handle_text}".lower()
    return "speechstream._end_of_utterance_timer_start" in joined or "speechmatics/stt.py" in joined


def _install_asyncio_exception_filter() -> None:
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def _handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if _is_benign_speechmatics_close(context):
            logger.info("Ignoring benign Speechmatics close callback after room disconnect.")
            return
        if previous_handler:
            previous_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


@dataclass
class Turn:
    ts: float
    speaker: str
    text: str
    speaker_id: str | None = None


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
        self._session_uses_diarization: dict[str, bool] = {}
        self._diarization_tag_roles: dict[str, dict[str, str]] = {}
        self._last_turn_role: dict[str, str] = {}
        self._tasks: set[asyncio.Task] = set()

        self._turns: list[Turn] = []
        self._roles: dict[str, str] = {}

        # Use LiveKit inference or direct OpenAI if configured
        import livekit.plugins.openai as openai_plugin

        self._llm = openai_plugin.LLM(model=SCRIBE_LLM_MODEL)
        adjudication_model = (os.getenv("CONSULTATION_LLM_ADJUDICATION_MODEL") or SCRIBE_LLM_MODEL).strip()
        self._adjudicator_llm = openai_plugin.LLM(model=adjudication_model)
        self._adjudication_enabled = _read_bool_env("CONSULTATION_LLM_ADJUDICATION_ENABLED", True)
        self._adjudication_min_turns = _read_int_env("CONSULTATION_LLM_ADJUDICATION_MIN_TURNS", 4)
        self._adjudication_last_run_at = 0.0
        self._adjudication_cache_turn_count = 0
        self._adjudication_cache: list[Turn] | None = None
        self._adjudication_lock = asyncio.Lock()

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
        self._session_uses_diarization.clear()
        self._diarization_tag_roles.clear()
        self._last_turn_role.clear()
        self._adjudication_cache = None
        self._adjudication_cache_turn_count = 0
        self._adjudication_last_run_at = 0.0
        # LLM from OpenAI plugin doesn't need strict aclose, but good to have if inference plugin used

    def on_participant_connected(self, participant: rtc.RemoteParticipant):
        if participant.identity in self._sessions:
            return

        inferred_role = _infer_participant_role(participant)
        self._roles[participant.identity] = inferred_role

        logger.info(
            "Starting STT session for %s with inferred role=%s",
            participant.identity,
            inferred_role,
        )
        task = asyncio.create_task(self._start_session(participant))
        self._tasks.add(task)

        def _done(t: asyncio.Task):
            try:
                self._sessions[participant.identity] = t.result()
            except Exception as exc:
                self._session_uses_diarization.pop(participant.identity, None)
                logger.exception(
                    "Failed to start STT session for %s: %s",
                    participant.identity,
                    exc,
                )
            finally:
                self._tasks.discard(t)

        task.add_done_callback(_done)

    def on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        sess = self._sessions.pop(participant.identity, None)
        self._session_uses_diarization.pop(participant.identity, None)
        self._diarization_tag_roles.pop(participant.identity, None)
        self._last_turn_role.pop(participant.identity, None)
        self._adjudication_cache = None
        self._adjudication_cache_turn_count = 0
        if not sess:
            return
        logger.info("Closing STT session for %s", participant.identity)
        task = asyncio.create_task(self._close_session(sess))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(t))

    def _resolve_diarized_role(self, participant_identity: str, participant_role: str, speaker_id: str) -> str:
        tag_roles = self._diarization_tag_roles.setdefault(participant_identity, {})
        existing = tag_roles.get(speaker_id)
        if existing:
            return existing

        if participant_role == "doctor" and "doctor" not in tag_roles.values():
            tag_roles[speaker_id] = "doctor"
            return "doctor"
        if "patient" not in tag_roles.values():
            tag_roles[speaker_id] = "patient"
            return "patient"

        tag_roles[speaker_id] = "other"
        return "other"

    def _infer_single_tag_role(self, participant_identity: str, text: str) -> tuple[str, int, int]:
        lowered = (text or "").lower()
        previous = self._last_turn_role.get(participant_identity)

        doctor_score = 0
        patient_score = 0

        doctor_cues = (
            "for how long",
            "how long",
            "where is",
            "what kind",
            "do you",
            "did you",
            "have you",
            "can you",
            "are you",
            "on a scale",
            "let me",
            "i will",
            "we can",
            "come back",
        )
        patient_cues = (
            "i have",
            "i feel",
            "it hurts",
            "my back",
            "my head",
            "pain",
            "since",
            "for years",
            "for days",
        )

        if "?" in lowered:
            doctor_score += 2
        for cue in doctor_cues:
            if cue in lowered:
                doctor_score += 1
        for cue in patient_cues:
            if cue in lowered:
                patient_score += 1

        stripped = lowered.strip()
        if stripped.startswith(("yes", "no", "i ", "my ")):
            patient_score += 1
        if stripped.startswith(("okay", "so", "right")) and "?" in lowered:
            doctor_score += 1

        if doctor_score == patient_score:
            if previous == "doctor":
                return "patient", doctor_score, patient_score
            if previous == "patient":
                return "doctor", doctor_score, patient_score
            inferred = "doctor" if "?" in lowered else "patient"
            return inferred, doctor_score, patient_score

        inferred = "doctor" if doctor_score > patient_score else "patient"
        return inferred, doctor_score, patient_score

    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        role = self._roles.get(participant.identity, "unknown")
        remote_count = len(self.room.remote_participants)
        manual_diarization = _read_bool_env("CONSULTATION_ENABLE_DIARIZATION", False)
        auto_diarize_single = _read_bool_env("CONSULTATION_AUTO_DIARIZE_SINGLE_PARTICIPANT", True)
        use_diarization = bool(
            manual_diarization or (auto_diarize_single and remote_count <= 1 and role == "doctor")
        )
        self._session_uses_diarization[participant.identity] = use_diarization
        if use_diarization:
            self._diarization_tag_roles.setdefault(participant.identity, {})
        if use_diarization:
            logger.info(
                "Diarization enabled for participant=%s (manual=%s remote_count=%s role=%s)",
                participant.identity,
                manual_diarization,
                remote_count,
                role,
            )

        session = AgentSession(
            stt=_build_consultation_stt(enable_diarization_override=use_diarization),
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

    async def on_final_transcript(self, speaker_identity: str, text: str):
        participant_role = self._roles.get(speaker_identity, "unknown")
        use_diarization = self._session_uses_diarization.get(speaker_identity, False)
        min_chars = max(1, int(_read_float_env("CONSULTATION_MIN_TEXT_CHARS", 3)))
        include_other_speaker = _read_bool_env("CONSULTATION_INCLUDE_OTHER_SPEAKER", False)
        single_tag_heuristic = _read_bool_env("CONSULTATION_SINGLE_TAG_ROLE_HEURISTIC", True)
        override_delta = max(1, int(_read_float_env("CONSULTATION_SINGLE_TAG_OVERRIDE_DELTA", 2)))

        tagged_segments = _extract_tagged_segments(text) if use_diarization else []
        segments: list[tuple[str | None, str]]
        if tagged_segments:
            segments = [(speaker_id, clean_text) for speaker_id, clean_text in tagged_segments]
        else:
            speaker_id, clean_text = _parse_speaker_tag(text)
            segments = [(speaker_id, clean_text)]

        added_turn = False
        for speaker_id, clean_text in segments:
            if not clean_text:
                continue
            if len(clean_text) < min_chars:
                continue

            heuristic_role, doctor_score, patient_score = self._infer_single_tag_role(
                speaker_identity, clean_text
            )
            role_delta = patient_score - doctor_score

            role = "unknown"
            has_patient_tag = False
            if use_diarization and speaker_id:
                role = self._resolve_diarized_role(speaker_identity, participant_role, speaker_id)
                tag_roles = self._diarization_tag_roles.get(speaker_identity, {})
                has_patient_tag = "patient" in tag_roles.values()

                if single_tag_heuristic:
                    if not has_patient_tag:
                        role = heuristic_role
                    elif role == "doctor" and role_delta >= override_delta:
                        role = "patient"
                    elif role == "patient" and role_delta <= -override_delta:
                        role = heuristic_role
            if role == "unknown":
                role = participant_role
            if role == "unknown" and speaker_id:
                role = SPEAKER_ROLE_MAP.get(speaker_id, "unknown")
            if role == "unknown":
                role = "patient"
            if role == "other" and not include_other_speaker:
                if not has_patient_tag:
                    role = heuristic_role
                else:
                    logger.info(
                        "[%s/%s] filtered additional speaker from %s: %s",
                        speaker_id or "?",
                        role,
                        speaker_identity,
                        clean_text,
                    )
                    continue

            ts = time.time()
            self._turns.append(Turn(ts=ts, speaker=role, text=clean_text, speaker_id=speaker_id))
            self._last_turn_role[speaker_identity] = role
            self._adjudication_cache = None
            self._adjudication_cache_turn_count = 0
            added_turn = True

            logger.info(
                "[%s/%s] %s: %s",
                speaker_id or "?",
                role,
                speaker_identity,
                clean_text,
            )
            await self._send_json(
                topic=TOPIC_TRANSCRIPT,
                payload={
                    "type": "transcript",
                    "speaker": "Doctor" if role == "doctor" else "Patient",
                    "speaker_role": role,
                    "text": clean_text,
                    "speaker_id": speaker_id or "unknown",
                    "timestamp": ts,
                },
            )

        if added_turn:
            self._trigger_suggestions()

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

        recent = self._format_turns(self._turns[-14:], max_chars=4000)

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

        chat = llm.ChatContext()
        chat.add_message(role="system", content=system)
        chat.add_message(role="user", content=user)

        try:
            stream = self._llm.chat(chat_ctx=chat)
            text = await _collect_llm_text(stream)
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

    def _format_turns(self, turns: list[Turn], *, max_chars: int | None = None) -> str:
        lines = [f"- {t.speaker}: {t.text}" for t in turns]
        s = "\\n".join(lines)
        if max_chars is None or max_chars <= 0:
            return s
        return s[-max_chars:]

    def _serialize_turns_for_summary(self, turns: list[Turn]) -> list[dict[str, str]]:
        # Keep summary payload compatible with backend TranscriptMessageInput
        # while preferring adjudicated doctor/patient turns.
        transcript: list[dict[str, str]] = []

        def _append(turn: Turn, *, force_patient_fallback: bool = False) -> None:
            text = (turn.text or "").strip()
            if not text:
                return
            if force_patient_fallback:
                speaker = "Doctor" if turn.speaker == "doctor" else "Patient"
            else:
                if turn.speaker not in {"doctor", "patient"}:
                    return
                speaker = "Doctor" if turn.speaker == "doctor" else "Patient"

            transcript.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "timestamp": time.strftime("%H:%M:%S", time.localtime(turn.ts)),
                }
            )

        for turn in turns:
            _append(turn)

        # If role filtering dropped everything, keep the text as patient fallback.
        if not transcript:
            for turn in turns:
                _append(turn, force_patient_fallback=True)

        return transcript

    async def _adjudicate_turns(
        self,
        turns: list[Turn],
        *,
        max_chars: int | None = None,
        preserve_all: bool = False,
    ) -> list[Turn]:
        if not turns:
            return turns

        payload_turns = [
            {
                "idx": idx,
                "speaker": turn.speaker,
                "speaker_id": turn.speaker_id or "unknown",
                "text": turn.text,
            }
            for idx, turn in enumerate(turns)
            if turn.text.strip()
        ]
        if not payload_turns:
            return turns

        system = (
            "You are a medical transcript adjudicator. "
            "Given noisy ASR turns, relabel speaker roles and lightly clean wording. "
            "Return STRICT JSON with key 'turns'. Each item must include: "
            "idx (int), speaker ('doctor'|'patient'|'other'), text (string), drop (bool), confidence (0..1). "
            "Rules: do not invent facts, keep medical meaning, keep text concise, and keep chronology."
        )
        user = (
            "Input turns JSON:\\n"
            f"{json.dumps(payload_turns, ensure_ascii=False)}\\n\\n"
            "Return JSON only."
        )

        chat = llm.ChatContext()
        chat.add_message(role="system", content=system)
        chat.add_message(role="user", content=user)

        try:
            stream = self._adjudicator_llm.chat(chat_ctx=chat)
            text = await _collect_llm_text(stream)
            data = _safe_json(text) or {}
        except Exception as exc:
            logger.warning("Transcript adjudication failed; using raw turns: %s", exc)
            return turns

        raw_items = data.get("turns")
        if not isinstance(raw_items, list) or not raw_items:
            return turns

        updated: list[Turn] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            idx = item.get("idx")
            if not isinstance(idx, int) or idx < 0 or idx >= len(turns):
                continue
            original = turns[idx]
            speaker = _normalize_role(item.get("speaker") if isinstance(item.get("speaker"), str) else None)
            if speaker == "unknown":
                speaker = original.speaker
            drop = bool(item.get("drop", False))
            confidence_raw = item.get("confidence")
            confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.5
            cleaned_text = str(item.get("text") or "").strip() or original.text
            if drop and confidence >= 0.6:
                continue
            updated.append(
                Turn(
                    ts=original.ts,
                    speaker=speaker if speaker in {"doctor", "patient", "other"} else original.speaker,
                    text=cleaned_text,
                    speaker_id=original.speaker_id,
                )
            )

        if len(updated) < max(2, len(turns) // 2):
            return turns

        if preserve_all or max_chars is None or max_chars <= 0:
            return updated

        # Trim for prompt budget while preserving most recent context.
        budgeted: list[Turn] = []
        total_chars = 0
        for turn in reversed(updated):
            line_len = len(turn.text) + 16
            if budgeted and (total_chars + line_len) > max_chars:
                break
            budgeted.append(turn)
            total_chars += line_len
        budgeted.reverse()
        return budgeted if budgeted else updated

    async def _adjudicate_full_dialogue(self) -> list[Turn]:
        if not self._turns:
            return []
        if not self._adjudication_enabled or len(self._turns) < self._adjudication_min_turns:
            return list(self._turns)

        chunk_turns = max(10, _read_int_env("CONSULTATION_LLM_ADJUDICATION_CHUNK_TURNS", 40))
        chunk_max_chars = max(4000, _read_int_env("CONSULTATION_LLM_ADJUDICATION_CHUNK_MAX_CHARS", 20000))
        adjudicated_all: list[Turn] = []

        async with self._adjudication_lock:
            for idx in range(0, len(self._turns), chunk_turns):
                chunk = self._turns[idx : idx + chunk_turns]
                adjudicated_chunk = await self._adjudicate_turns(
                    chunk,
                    max_chars=chunk_max_chars,
                    preserve_all=True,
                )
                adjudicated_all.extend(adjudicated_chunk)
            self._adjudication_cache = adjudicated_all
            self._adjudication_cache_turn_count = len(self._turns)
            self._adjudication_last_run_at = time.time()

        return adjudicated_all if adjudicated_all else list(self._turns)

    async def finalize_and_send_soap(self):
        turns_for_prompt = await self._adjudicate_full_dialogue()
        final_max_chars_raw = _read_int_env("CONSULTATION_FINAL_TRANSCRIPT_MAX_CHARS", 0)
        final_max_chars = None if final_max_chars_raw <= 0 else final_max_chars_raw
        recent = self._format_turns(turns_for_prompt, max_chars=final_max_chars)
        enhanced_transcript = self._serialize_turns_for_summary(turns_for_prompt)

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
        chat = llm.ChatContext()
        chat.add_message(role="system", content=system)
        chat.add_message(role="user", content=user)

        stream = self._llm.chat(chat_ctx=chat)
        text = await _collect_llm_text(stream)
        data = _safe_json(text) or {}

        payload = {
            "type": "soap",
            "soap": data.get("soap", {}),
            "meds_mentioned": data.get("meds_mentioned", []),
            "followups": data.get("followups", []),
            "safety_checks": data.get("safety_checks", []),
            "enhanced_transcript": enhanced_transcript,
            "enhanced_transcript_text": recent,
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
                    normalized = _normalize_role(role if isinstance(role, str) else None)
                    if isinstance(identity, str) and normalized in {"doctor", "patient", "unknown"}:
                        self._roles[identity] = normalized
                        self._adjudication_cache = None
                        self._adjudication_cache_turn_count = 0
                        logger.info("Role updated: %s -> %s", identity, normalized)

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


def _extract_tagged_segments(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for match in _SPEAKER_TAG_RE.finditer(text or ""):
        speaker_id = match.group(1)
        clean = match.group(2).strip()
        if clean:
            segments.append((speaker_id, clean))
    return segments


async def _collect_llm_text(stream: Any) -> str:
    """
    LiveKit LLM stream compatibility helper.
    Supports both:
    - new API: stream.collect() -> response.content
    - current pinned API: async iteration + to_str_iterable()
    """
    if stream is None:
        return ""

    if hasattr(stream, "collect"):
        resp = await stream.collect()
        return str(getattr(resp, "content", "") or "")

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
                    text_part = getattr(delta, "content", None) or getattr(delta, "text", None)
                if text_part is None:
                    text_part = getattr(chunk, "content", None) or getattr(chunk, "text", None)
                if isinstance(text_part, list):
                    text_part = "".join(str(item) for item in text_part)
                if text_part:
                    chunks.append(str(text_part))
    finally:
        if hasattr(stream, "aclose"):
            await stream.aclose()

    return "".join(chunks)


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name, "agent": AGENT_NAME}
    _install_asyncio_exception_filter()

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
