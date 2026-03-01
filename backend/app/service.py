from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any, Iterable
from uuid import uuid4

from app.config import load_calendar_config, load_persistence_config, load_sms_config
from app.integrations.calcom_client import CalComClient
from app.integrations.livekit_dispatcher import DispatchResult, LiveKitOutboundDispatcher
from app.integrations.persistence_client import PostgresPersistenceClient
from app.integrations.twilio_client import TwilioSmsClient
from app.lifecycle import default_lifecycle_stages
from app.models import (
    BookAppointmentRequest,
    BookAppointmentResponse,
    CancelAppointmentResponse,
    ConsultationRoomTokenResponse,
    DashboardAppointment,
    DashboardAppointmentDetailResponse,
    DashboardCallbackTask,
    DashboardCallRecord,
    DashboardKpis,
    DashboardOverviewResponse,
    DashboardPatient,
    DashboardPatientDetailResponse,
    DashboardPriorityItem,
    FollowupCallCompleteRequest,
    FollowupCallRequest,
    FollowupCallResponse,
    ConsultationSummaryRequest,
    ConsultationSummaryResponse,
    ConsultationSessionState,
    DashboardAppointmentsResponse,
    DashboardPatientsResponse,
    LifecycleEvent,
    LifecycleStage,
    PastAppointmentRecord,
    SuggestQuestionsRequest,
    SuggestQuestionsResponse,
    TranscriptMessageInput,
)

logger = logging.getLogger("medvoice.service")


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _unique_compact(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        label = str(value or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _to_e164_fr(phone: str) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return raw
    if raw.startswith("+"):
        digits = "+" + "".join(ch for ch in raw[1:] if ch.isdigit())
        return digits
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if digits.startswith("33"):
        return f"+{digits}"
    if len(digits) == 10 and digits.startswith("0"):
        return f"+33{digits[1:]}"
    return f"+{digits}"


def _normalize_transcript_speaker(label: str) -> str:
    value = (label or "").strip().lower()
    if value in {"patient", "user", "caller"}:
        return "patient"
    if value in {"doctor", "assistant", "ai", "system"}:
        return "doctor"
    return value


def _classify_binary_answer(text: str) -> str:
    lowered = (text or "").strip().lower()
    if not lowered:
        return "unknown"
    yes_hits = _has_any(
        lowered,
        ("yes", "yeah", "yep", "of course", "i am", "i do", "regularly", "sure", "okay"),
    )
    no_hits = _has_any(
        lowered,
        (
            "no",
            "not",
            "don't",
            "do not",
            "none",
            "nothing",
            "never",
            "not at all",
        ),
    )
    if yes_hits and not no_hits:
        return "yes"
    if no_hits and not yes_hits:
        return "no"
    return "unknown"


def _detect_symptoms_from_text(text: str) -> list[str]:
    lowered = (text or "").lower()
    symptom_rules = {
        "Back pain": ("back pain", "back hurts", "lower back"),
        "Headache": ("headache", "migraine"),
        "Fever": ("fever", "temperature"),
        "Nausea": ("nausea", "vomit", "vomiting"),
        "Shortness of breath": ("shortness of breath", "breathing issue", "dyspnea"),
        "Chest pain": ("chest pain", "chest tightness"),
    }
    detected: list[str] = []
    for label, keys in symptom_rules.items():
        if any(key in lowered for key in keys):
            detected.append(label)
    return detected


def _extract_reported_allergies(patient_text: str) -> list[str]:
    lowered = (patient_text or "").lower()
    if not lowered:
        return []
    if _has_any(lowered, ("no allergy", "no allergies", "none", "not allergic")):
        return []
    results: list[str] = []
    for marker in ("allergy to", "allergic to"):
        if marker not in lowered:
            continue
        tail = lowered.split(marker, 1)[1]
        chunk = tail.split(".", 1)[0].split(",", 1)[0].strip(" :;")
        if not chunk:
            continue
        cleaned = " ".join(chunk.split()[:4]).strip()
        if cleaned and cleaned not in {"anything", "none"}:
            results.append(cleaned.title())
    return _unique_compact(results)


def _next_patient_reply(transcript: list[TranscriptMessageInput], start_idx: int) -> str:
    window = transcript[start_idx + 1 : start_idx + 6]
    for item in window:
        if _normalize_transcript_speaker(item.speaker) == "patient":
            text = (item.text or "").strip()
            if text:
                return text
    return ""


def _extract_followup_signals(transcript: list[TranscriptMessageInput]) -> dict[str, Any]:
    adherence = "unknown"
    side_effects = "unknown"
    new_symptoms = "unknown"
    evolution = "unknown"

    patient_blob = " ".join(
        (item.text or "").strip()
        for item in transcript
        if _normalize_transcript_speaker(item.speaker) == "patient"
    )
    patient_blob_lower = patient_blob.lower()

    for idx, item in enumerate(transcript):
        if _normalize_transcript_speaker(item.speaker) != "doctor":
            continue
        question = (item.text or "").strip().lower()
        if not question:
            continue
        answer = _next_patient_reply(transcript, idx)
        if not answer:
            continue

        if "taking" in question and _has_any(question, ("medication", "prescribed", "treatment")):
            adherence = _classify_binary_answer(answer)
        elif _has_any(question, ("side effect", "allergic reaction", "allerg")):
            side_effects = _classify_binary_answer(answer)
        elif _has_any(question, ("new symptom", "new symptoms")):
            new_symptoms = _classify_binary_answer(answer)
        elif _has_any(question, ("improving", "stable", "worsening", "worsen")):
            answer_lower = answer.lower()
            if "wors" in answer_lower:
                evolution = "worsening"
            elif _has_any(answer_lower, ("improv", "better", "less pain")):
                evolution = "improvement"
            elif "stable" in answer_lower:
                evolution = "stable"

    if evolution == "unknown":
        if "wors" in patient_blob_lower:
            evolution = "worsening"
        elif _has_any(patient_blob_lower, ("improv", "better", "less pain")):
            evolution = "improvement"
        elif "stable" in patient_blob_lower:
            evolution = "stable"

    if side_effects == "unknown":
        if _has_any(patient_blob_lower, ("side effect", "allergic reaction", "rash", "itch")):
            side_effects = "yes"
        elif _has_any(patient_blob_lower, ("no side effect", "no side effects", "no allergy", "not allergic")):
            side_effects = "no"

    if new_symptoms == "unknown":
        if _has_any(patient_blob_lower, ("new symptom", "new symptoms")):
            new_symptoms = "yes"
        elif _has_any(patient_blob_lower, ("nothing new", "no new symptoms", "no new symptom", "nothing else")):
            new_symptoms = "no"

    return {
        "adherence": adherence,
        "side_effects": side_effects,
        "new_symptoms": new_symptoms,
        "evolution": evolution,
        "symptoms": _detect_symptoms_from_text(patient_blob),
        "allergies": _extract_reported_allergies(patient_blob),
    }


def _build_followup_summary(
    *,
    status: str,
    duration_seconds: int,
    symptoms: list[str],
    evolution: str,
    recommendations: list[str],
    insights: dict[str, Any],
    fallback: str,
) -> str:
    if status != "completed":
        reason = (fallback or "").strip() or f"status={status}"
        return f"Follow-up call did not complete ({reason})."

    duration_minutes = max(1, round(max(duration_seconds, 0) / 60))
    lines: list[str] = [f"Follow-up call completed in {duration_minutes} minute(s)."]

    if symptoms:
        symptom_text = ", ".join(symptoms[:3])
        if evolution in {"improvement", "stable", "worsening"}:
            lines.append(f"Current symptom trend: {symptom_text} ({evolution}).")
        else:
            lines.append(f"Discussed symptoms: {symptom_text}.")

    adherence = str(insights.get("adherence") or "unknown")
    if adherence == "yes":
        lines.append("Medication adherence was confirmed.")
    elif adherence == "no":
        lines.append("Possible medication non-adherence was reported.")

    side_effects = str(insights.get("side_effects") or "unknown")
    if side_effects == "no":
        lines.append("No side effects or allergic reactions were reported.")
    elif side_effects == "yes":
        lines.append("Possible side effects/allergic concerns were reported.")

    new_symptoms = str(insights.get("new_symptoms") or "unknown")
    if new_symptoms == "no":
        lines.append("No new symptoms were reported.")
    elif new_symptoms == "yes":
        lines.append("New symptoms were reported and require monitoring.")

    if recommendations:
        clean_plan = "; ".join(item.rstrip(" .;") for item in recommendations[:2] if item.strip())
        if clean_plan:
            lines.append(f"Plan: {clean_plan}.")

    summary = " ".join(lines).strip()
    return summary or "Follow-up call completed with no structured summary."


class LifecycleService:
    def __init__(self) -> None:
        self._stages = default_lifecycle_stages()
        self._events: list[LifecycleEvent] = []
        self._transcripts: dict[str, list[TranscriptMessageInput]] = defaultdict(list)
        self._consultation_sessions: dict[str, ConsultationSessionState] = {}
        self._livekit_url = (os.getenv("LIVEKIT_URL") or "").strip()
        self._livekit_api_key = (os.getenv("LIVEKIT_API_KEY") or "").strip()
        self._livekit_api_secret = (os.getenv("LIVEKIT_API_SECRET") or "").strip()
        self._consultation_agent_name = (
            os.getenv("CONSULTATION_AGENT_NAME")
            or os.getenv("AGENT_NAME")
            or "medvoice-consultation"
        ).strip()
        self._consultation_auto_dispatch = (
            (os.getenv("CONSULTATION_AUTO_DISPATCH") or "true").strip().lower()
            != "false"
        )
        self._outbound_agent_name = (os.getenv("LIVEKIT_OUTBOUND_AGENT_NAME") or "outbound-caller").strip()
        self._followup_default_phone = (os.getenv("FOLLOWUP_TEST_PHONE") or "0784221830").strip()
        self._calcom_client = CalComClient(load_calendar_config())
        self._sms_client = TwilioSmsClient(load_sms_config())
        self._persistence_client = PostgresPersistenceClient(load_persistence_config())
        self._outbound_dispatcher = LiveKitOutboundDispatcher(
            livekit_url=self._livekit_url,
            api_key=self._livekit_api_key,
            api_secret=self._livekit_api_secret,
            agent_name=self._outbound_agent_name,
            sip_outbound_trunk_id=(os.getenv("SIP_OUTBOUND_TRUNK_ID") or "").strip(),
        )

    def _clone_stages(self) -> list[LifecycleStage]:
        return [LifecycleStage.model_validate(stage.model_dump()) for stage in self._stages]

    def list_stages(self) -> list[LifecycleStage]:
        stages = self._clone_stages()
        if self._has_stage_event("consultation-end-prescription"):
            stages = self._set_status(stages, "consultation-end-prescription", "done")
            stages = self._set_status(stages, "post-consultation-followup", "active")
        if self._has_stage_event("post-consultation-followup"):
            stages = self._set_status(stages, "post-consultation-followup", "done")
        return stages

    def _set_status(
        self, stages: list[LifecycleStage], stage_id: str, status: str
    ) -> list[LifecycleStage]:
        for stage in stages:
            if stage.id == stage_id:
                stage.status = status  # type: ignore[assignment]
        return stages

    def _has_stage_event(self, stage_id: str) -> bool:
        return any(event.stage_id == stage_id for event in self._events)

    def add_event(
        self,
        stage_id: str,
        appointment_id: str | None = None,
        patient_id: str | None = None,
        payload: dict | None = None,
    ) -> LifecycleEvent:
        event = LifecycleEvent(
            stage_id=stage_id,
            appointment_id=appointment_id,
            patient_id=patient_id,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def save_transcript(
        self, appointment_id: str, messages: Iterable[TranscriptMessageInput]
    ) -> None:
        serialized_messages = list(messages)
        self._transcripts[appointment_id].extend(serialized_messages)
        session = self._consultation_sessions.get(appointment_id)
        if session:
            session.transcriptCount += len(serialized_messages)

    def start_consultation(self, appointment_id: str, patient_id: str) -> ConsultationSessionState:
        session = self._consultation_sessions.get(appointment_id)
        if not session:
            session = ConsultationSessionState(
                appointmentId=appointment_id,
                patientId=patient_id,
                status="active",
                startedAt=datetime.now(timezone.utc).isoformat(),
            )
            self._consultation_sessions[appointment_id] = session
        else:
            session.status = "active"
            session.startedAt = session.startedAt or datetime.now(timezone.utc).isoformat()
        return session

    def end_consultation(self, appointment_id: str) -> ConsultationSessionState | None:
        session = self._consultation_sessions.get(appointment_id)
        if not session:
            return None
        session.status = "ended"
        session.endedAt = datetime.now(timezone.utc).isoformat()
        return session

    def get_consultation_state(self, appointment_id: str) -> ConsultationSessionState | None:
        return self._consultation_sessions.get(appointment_id)

    async def issue_consultation_room_token(
        self,
        *,
        appointment_id: str,
        participant_identity: str,
        participant_name: str,
    ) -> ConsultationRoomTokenResponse:
        if not self._livekit_url or not self._livekit_api_key or not self._livekit_api_secret:
            raise RuntimeError(
                "Missing LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET for consultation token generation."
            )
        try:
            from livekit import api as livekit_api  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("livekit SDK is required to issue consultation tokens.") from exc

        room_name = f"consultation-{appointment_id}"
        try:
            grants = livekit_api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        except TypeError:
            grants = livekit_api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        token = (
            livekit_api.AccessToken(self._livekit_api_key, self._livekit_api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_grants(grants)
            .to_jwt()
        )

        if self._consultation_auto_dispatch:
            await self._ensure_consultation_dispatch(room_name)

        return ConsultationRoomTokenResponse(
            token=token,
            url=self._livekit_url,
            roomName=room_name,
            participantIdentity=participant_identity,
            participantName=participant_name,
        )

    async def _ensure_consultation_dispatch(self, room_name: str) -> None:
        try:
            from livekit import api as livekit_api  # type: ignore
            from livekit.protocol import room as room_proto  # type: ignore
            from livekit.protocol import agent_dispatch as agent_dispatch_proto  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("livekit server API package is required for agent dispatch.") from exc

        api_url = self._livekit_url
        if api_url.startswith("wss://"):
            api_url = "https://" + api_url[6:]
        elif api_url.startswith("ws://"):
            api_url = "http://" + api_url[5:]

        lk = livekit_api.LiveKitAPI(
            url=api_url,
            api_key=self._livekit_api_key,
            api_secret=self._livekit_api_secret,
        )
        try:
            try:
                await lk.room.create_room(
                    room_proto.CreateRoomRequest(
                        name=room_name,
                        empty_timeout=60 * 15,
                        departure_timeout=20,
                    )
                )
            except Exception as exc:
                text = str(exc).lower()
                if "already exists" not in text and "room already" not in text:
                    raise RuntimeError(f"Failed to ensure room '{room_name}': {exc}") from exc

            existing = await lk.agent_dispatch.list_dispatch(room_name)
            if any(dispatch.agent_name == self._consultation_agent_name for dispatch in existing):
                return

            request = agent_dispatch_proto.CreateAgentDispatchRequest(
                agent_name=self._consultation_agent_name,
                room=room_name,
                metadata=json.dumps({"source": "backend_consultation_token"}),
            )
            await lk.agent_dispatch.create_dispatch(request)
            logger.info(
                "Created consultation agent dispatch room=%s agent=%s",
                room_name,
                self._consultation_agent_name,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to dispatch consultation agent '{self._consultation_agent_name}' in room '{room_name}': {exc}"
            ) from exc
        finally:
            await lk.aclose()

    def _load_summary_context(self, appointment_id: str, patient_id: str) -> dict:
        context_signals: list[str] = []
        allergies: list[str] = []
        antecedents: list[str] = []
        historical_symptoms: list[str] = []
        past_call_summaries: list[str] = []

        detail = self.get_appointment_detail(appointment_id)
        if detail:
            allergies = detail.patient.allergies
            antecedents = detail.patient.antecedents
            historical_symptoms = _unique_compact(
                symptom
                for call in detail.calls
                for symptom in call.symptoms
            )
            past_call_summaries = [
                call.summary.strip()
                for call in detail.calls
                if call.summary and call.summary.strip()
            ][:4]
            if allergies:
                context_signals.append(f"Known allergies: {', '.join(allergies)}")
            if antecedents:
                context_signals.append(f"Chronic conditions: {', '.join(antecedents)}")
            if historical_symptoms:
                context_signals.append(
                    f"Symptoms seen in previous calls: {', '.join(historical_symptoms[:5])}"
                )
        else:
            patient_detail = self.get_patient_detail(patient_id)
            if patient_detail:
                allergies = patient_detail.patient.allergies
                antecedents = patient_detail.patient.antecedents
                historical_symptoms = _unique_compact(
                    symptom
                    for call in patient_detail.calls
                    for symptom in call.symptoms
                )
                past_call_summaries = [
                    call.summary.strip()
                    for call in patient_detail.calls
                    if call.summary and call.summary.strip()
                ][:4]
                if allergies:
                    context_signals.append(f"Known allergies: {', '.join(allergies)}")
                if antecedents:
                    context_signals.append(f"Chronic conditions: {', '.join(antecedents)}")

        return {
            "allergies": allergies,
            "antecedents": antecedents,
            "historical_symptoms": historical_symptoms,
            "past_call_summaries": past_call_summaries,
            "context_signals": context_signals,
        }

    def generate_summary(
        self, request: ConsultationSummaryRequest
    ) -> ConsultationSummaryResponse:
        # If transcript is omitted, use what was already streamed in consultation/transcript endpoint.
        transcript = request.transcript or self._transcripts.get(request.appointmentId, [])
        self.save_transcript(request.appointmentId, transcript)

        context = self._load_summary_context(request.appointmentId, request.patientId)
        joined = " ".join(message.text.lower() for message in transcript)
        soap_blob = " ".join(str(v).lower() for v in request.soap.values()) if request.soap else ""
        combined = f"{joined} {soap_blob}".strip()

        symptom_rules: list[tuple[str, tuple[str, ...]]] = [
            ("Fever", ("fever", "temperature")),
            ("Sore throat", ("sore throat", "throat pain")),
            ("Cough", ("cough",)),
            ("Headache", ("headache", "migraine")),
            ("Fatigue", ("fatigue", "tired", "asthenia")),
            ("Shortness of breath", ("shortness of breath", "dyspnea")),
            ("Chest pain", ("chest pain",)),
            ("Nausea", ("nausea", "vomit")),
        ]

        detected_symptoms = [
            label for label, keywords in symptom_rules if _has_any(combined, keywords)
        ]
        if not detected_symptoms:
            detected_symptoms = ["General symptoms"]

        for prior in context["historical_symptoms"][:4]:
            if prior and prior.lower() not in {sym.lower() for sym in detected_symptoms}:
                detected_symptoms.append(prior)

        has_fever = any(sym.lower() == "fever" for sym in detected_symptoms)
        has_throat = any(sym.lower() == "sore throat" for sym in detected_symptoms)
        has_cough = any(sym.lower() == "cough" for sym in detected_symptoms)
        has_red_flag = any(
            sym.lower() in {"shortness of breath", "chest pain"} for sym in detected_symptoms
        )

        diagnoses: list[str] = []
        if has_fever and has_throat:
            diagnoses.append("Acute pharyngitis (bacterial vs viral)")
        if has_cough and has_fever:
            diagnoses.append("Upper respiratory tract infection")
        if has_red_flag:
            diagnoses.append("Requires urgent in-person assessment for red-flag symptoms")
        diagnoses.extend(
            [
                "Viral syndrome",
                "Symptomatic follow-up recommended",
            ]
        )
        diagnoses = _unique_compact(diagnoses)[:4]

        allergy_text = " ".join(context["allergies"]).lower()
        penicillin_allergy = _has_any(allergy_text, ("penicillin", "amoxicillin"))

        antibiotics = (
            {
                "name": "Azithromycin",
                "dosage": "500mg",
                "frequency": "Once daily",
                "duration": "3 days",
            }
            if penicillin_allergy
            else {
                "name": "Amoxicillin",
                "dosage": "1g",
                "frequency": "3 times daily",
                "duration": "6 days",
            }
        )
        prescription = {
            "medications": [
                antibiotics,
                {
                    "name": "Paracetamol",
                    "dosage": "1000mg",
                    "frequency": "Every 6 to 8 hours if needed",
                    "duration": "3 to 5 days",
                },
            ],
            "additionalAdvice": _unique_compact(
                [
                    "Hydration and rest are recommended.",
                    "Return quickly if symptoms worsen.",
                    "Emergency care advised if chest pain or breathing difficulty occurs."
                    if has_red_flag
                    else "Follow-up if no improvement in 48 hours.",
                    (
                        f"Medication selected to avoid documented allergy: {', '.join(context['allergies'])}."
                        if penicillin_allergy
                        else ""
                    ),
                ]
            ),
        }

        summary_chunks = [
            "Consultation summary generated from live transcript and prior patient context.",
            f"Main symptoms discussed: {', '.join(detected_symptoms[:5])}.",
        ]
        if context["antecedents"]:
            summary_chunks.append(
                f"Relevant history considered: {', '.join(context['antecedents'][:4])}."
            )
        if context["past_call_summaries"]:
            summary_chunks.append(
                f"Previous call trend: {context['past_call_summaries'][0][:220]}"
            )
        if request.soap:
            summary_chunks.append("SOAP note from consultation agent was incorporated.")
        summary = " ".join(summary_chunks)

        persisted_report = False
        try:
            persisted_report = self._persistence_client.persist_consultation_report(
                appointment_id=request.appointmentId,
                patient_id=request.patientId,
                transcript=[message.model_dump() for message in transcript],
                summary_text=summary,
                symptoms=detected_symptoms,
                diagnoses=diagnoses,
                prescription=prescription,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to persist consultation report: %s", exc)

        self.add_event(
            stage_id="consultation-end-prescription",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={
                "messages": len(transcript),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "persisted_report": persisted_report,
            },
        )
        self.add_event(
            stage_id="post-consultation-followup",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={"followup_type": "sms"},
        )
        self.end_consultation(request.appointmentId)

        return ConsultationSummaryResponse(
            summary=summary,
            detectedSymptoms=detected_symptoms,
            diagnoses=diagnoses,
            prescription=prescription,
            contextSignals=context["context_signals"],
        )

    def suggest_questions(
        self, request: SuggestQuestionsRequest
    ) -> SuggestQuestionsResponse:
        joined = " ".join(message.text.lower() for message in request.transcript)

        topics = {
            "duration": ["since", "days", "weeks", "duration"],
            "fever": ["fever", "temperature"],
            "pain": ["pain", "intensity", "severity"],
            "allergies": ["allergy", "allergies"],
            "treatments": ["treatment", "medication", "medicine", "taken"],
            "redflag_resp": ["shortness of breath", "dyspnea", "breathing"],
            "redflag_chest": ["chest pain", "chest tightness"],
            "redflag_confusion": ["confusion", "disoriented", "disorientation"],
        }

        asked_topics = [
            topic
            for topic, keywords in topics.items()
            if any(keyword in joined for keyword in keywords)
        ]

        questions: list[str] = []
        if "duration" not in asked_topics:
            questions.append("When exactly did the symptoms start?")
        if "fever" not in asked_topics:
            questions.append("Have you had a fever, and what was the highest temperature?")
        if "pain" not in asked_topics:
            questions.append("On a scale from 0 to 10, how severe is the pain?")
        if "allergies" not in asked_topics:
            questions.append("Do you have any known medication allergies?")
        if "treatments" not in asked_topics:
            questions.append("Have you already taken any treatment for this issue?")

        red_flags: list[str] = []
        if "redflag_resp" in asked_topics:
            red_flags.append("Breathing difficulty detected")
        if "redflag_chest" in asked_topics:
            red_flags.append("Chest pain mentioned")
        if "redflag_confusion" in asked_topics:
            red_flags.append("Confusion mentioned")

        if not questions:
            questions.append("Are the symptoms improving, stable, or getting worse?")

        result = SuggestQuestionsResponse(
            questions=questions[:5],
            redFlags=red_flags,
            askedTopics=asked_topics,
        )
        session = self._consultation_sessions.get(request.appointmentId)
        if session:
            session.latestSuggestedQuestions = result.questions
            session.latestRedFlags = result.redFlags
        return result

    def _build_followup_context(self, request: FollowupCallRequest) -> dict[str, Any]:
        appointment_detail = self.get_appointment_detail(request.appointmentId)
        patient_detail = self.get_patient_detail(request.patientId)

        patient_phone = (
            (appointment_detail.patient.phone if appointment_detail else None)
            or (patient_detail.patient.phone if patient_detail else None)
            or request.patientPhone
            or request.patientId
        )
        patient_name = (
            (f"{appointment_detail.patient.firstName} {appointment_detail.patient.lastName}".strip() if appointment_detail else "")
            or (f"{patient_detail.patient.firstName} {patient_detail.patient.lastName}".strip() if patient_detail else "")
            or request.patientName
        )
        doctor_name = (
            (appointment_detail.appointment.doctor if appointment_detail else None)
            or request.doctorName
            or "Dr. Unassigned"
        )

        allergies = (
            appointment_detail.patient.allergies
            if appointment_detail
            else (patient_detail.patient.allergies if patient_detail else [])
        )
        antecedents = (
            appointment_detail.patient.antecedents
            if appointment_detail
            else (patient_detail.patient.antecedents if patient_detail else [])
        )
        call_records = (
            appointment_detail.calls if appointment_detail else (patient_detail.calls if patient_detail else [])
        )
        history_records = (
            appointment_detail.history if appointment_detail else []
        )

        try:
            latest_prescription = self._persistence_client.get_latest_prescription(
                patient_id=str(patient_phone or request.patientId),
                appointment_id=request.appointmentId,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load latest prescription for follow-up context: %s", exc)
            latest_prescription = {"medications": [], "additionalAdvice": []}

        medications_from_request: list[dict[str, str]] = []
        for med in request.medications:
            payload = med.model_dump() if hasattr(med, "model_dump") else dict(med)
            medications_from_request.append(
                {
                    "name": str(payload.get("name") or ""),
                    "dosage": str(payload.get("dosage") or ""),
                    "frequency": str(payload.get("frequency") or ""),
                    "duration": str(payload.get("duration") or ""),
                }
            )

        medications = medications_from_request or list(latest_prescription.get("medications") or [])
        additional_advice = _unique_compact(
            request.additionalAdvice or list(latest_prescription.get("additionalAdvice") or [])
        )

        prior_symptoms = _unique_compact(
            symptom
            for call in call_records[:8]
            for symptom in call.symptoms
        )

        next_appointment = request.nextAppointmentAt
        if not next_appointment and patient_detail:
            upcoming = [
                appt
                for appt in patient_detail.appointments
                if appt.status in {"upcoming", "in-progress"}
            ]
            if upcoming:
                starts_at = upcoming[0].startsAt
                next_appointment = starts_at

        question_plan: list[str] = []
        question_plan.append("How are you feeling since your last consultation?")
        if medications:
            question_plan.append("Are you taking your prescribed medications as advised?")
            for med in medications[:3]:
                label = str(med.get("name") or "").strip()
                if not label:
                    continue
                frequency = str(med.get("frequency") or "").strip()
                if frequency:
                    question_plan.append(f"Are you taking {label} ({frequency}) regularly?")
                else:
                    question_plan.append(f"Are you taking {label} regularly?")
        if prior_symptoms:
            question_plan.append(
                f"Are these symptoms improving, stable, or worsening: {', '.join(prior_symptoms[:3])}?"
            )
        question_plan.extend(
            [
                "Did you notice any side effects or allergic reactions?",
                "Do you have any new symptoms since the last visit?",
            ]
        )
        if next_appointment:
            question_plan.append(f"Reminder: your next appointment is scheduled for {next_appointment}.")

        return {
            "patient_phone": str(patient_phone or request.patientId),
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "allergies": _unique_compact(allergies),
            "antecedents": _unique_compact(antecedents),
            "history": [item.summary for item in history_records[:3] if item.summary],
            "recent_calls": [item.summary for item in call_records[:3] if item.summary],
            "medications": medications,
            "additional_advice": additional_advice,
            "next_appointment": next_appointment,
            "question_plan": _unique_compact(question_plan)[:8],
            "conversation_summary": (request.conversationSummary or "").strip(),
        }

    async def schedule_followup_call(
        self,
        request: FollowupCallRequest,
    ) -> FollowupCallResponse:
        followup_call_id = f"fup-{uuid4().hex[:12]}"
        target_phone_raw = (self._followup_default_phone or request.patientPhone or "").strip()
        if not target_phone_raw:
            raise RuntimeError("No target phone available for follow-up call.")
        target_dial_to = _to_e164_fr(target_phone_raw)

        context = self._build_followup_context(request)
        patient_ref = str(context.get("patient_phone") or request.patientId)
        task_notes = (
            f"Automated follow-up call queued. followup_call_id={followup_call_id}; "
            f"appointment_id={request.appointmentId}; dial_to={target_dial_to}"
        )
        try:
            followup_task_id = self._persistence_client.queue_followup_task(
                patient_id=patient_ref,
                notes=task_notes,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to queue follow-up task: %s", exc)
            followup_task_id = None

        metadata = {
            "type": "followup_call",
            "followup_call_id": followup_call_id,
            "followup_task_id": followup_task_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "appointment_id": request.appointmentId,
            "patient_id": request.patientId,
            "patient_name": context["patient_name"],
            "patient_phone": patient_ref,
            "dial_to": target_dial_to,
            "doctor_name": context["doctor_name"],
            "next_appointment_at": context["next_appointment"],
            "allergies": context["allergies"],
            "antecedents": context["antecedents"],
            "history_highlights": context["history"],
            "recent_call_highlights": context["recent_calls"],
            "prescription_medications": context["medications"],
            "prescription_advice": context["additional_advice"],
            "question_plan": context["question_plan"],
            "conversation_summary": context["conversation_summary"],
            "backend_api_base_url": os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            "language": os.getenv("OUTBOUND_CALL_LANGUAGE", "en"),
        }
        room_name = f"followup-{request.appointmentId}-{uuid4().hex[:6]}"
        sip_trunk_id = (os.getenv("SIP_OUTBOUND_TRUNK_ID") or "").strip()
        if not sip_trunk_id:
            dispatch = DispatchResult(
                status="failed",
                provider="livekit-dispatch",
                dispatch_id=None,
                room_name=None,
                detail="Missing SIP_OUTBOUND_TRUNK_ID. Configure your LiveKit SIP outbound trunk before launching calls.",
            )
            try:
                self._persistence_client.persist_outbound_followup_result(
                    followup_call_id=followup_call_id,
                    appointment_id=request.appointmentId,
                    patient_id=request.patientId,
                    patient_phone=patient_ref,
                    status="failed",
                    duration_seconds=0,
                    summary=str(dispatch.detail),
                    symptoms=[],
                    recommendations=["Configure SIP_OUTBOUND_TRUNK_ID and retry follow-up call."],
                    evolution="unknown",
                    followup_task_id=followup_task_id,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to persist immediate failed follow-up result: %s", exc)
        else:
            dispatch = await self._outbound_dispatcher.dispatch_followup_call(
                metadata=metadata,
                room_name=room_name,
                auto_dial=False,
            )

        confirmation_message = (
            f"Follow-up call to {target_phone_raw} was queued."
            if dispatch.status == "queued"
            else (
                f"Follow-up dispatch is running in mock mode for {target_phone_raw}."
                if dispatch.status == "mock"
                else f"Follow-up call dispatch failed for {target_phone_raw}."
            )
        )

        if dispatch.status == "failed":
            sms_sid = "mock-sms-skipped"
            sms_status = "skipped"
        else:
            sms = self._sms_client.send_confirmation_sms(
                to_phone=target_dial_to,
                body=(
                    f"Hello {context['patient_name']}, this is MedVoice. "
                    "We will call you shortly for your follow-up."
                ),
            )
            sms_sid = sms.sid
            sms_status = sms.status

        self.add_event(
            stage_id="post-consultation-followup",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={
                "followup_type": "call",
                "followup_call_id": followup_call_id,
                "followup_task_id": followup_task_id,
                "dispatch_status": dispatch.status,
                "dispatch_id": dispatch.dispatch_id,
                "room_name": dispatch.room_name,
                "dial_to": target_dial_to,
                "sms_sid": sms_sid,
                "sms_status": sms_status,
            },
        )

        return FollowupCallResponse(
            followupCallId=followup_call_id,
            status=dispatch.status if dispatch.status in {"queued", "failed", "mock", "completed"} else "failed",
            dialTo=target_dial_to,
            provider=dispatch.provider,
            dispatchId=dispatch.dispatch_id,
            roomName=dispatch.room_name,
            dispatchDetail=dispatch.detail,
            followupTaskId=followup_task_id,
            confirmationMessage=confirmation_message,
        )

    def complete_followup_call(self, request: FollowupCallCompleteRequest) -> dict[str, Any]:
        recommendations = _unique_compact(request.recommendations)
        transcript_items = list(request.transcript or [])
        insights = _extract_followup_signals(transcript_items)

        symptoms = _unique_compact(request.symptoms or list(insights.get("symptoms") or []))
        normalized_evolution = (
            request.evolution
            if request.evolution in {"improvement", "worsening", "stable"}
            else str(insights.get("evolution") or "unknown")
        )
        summary_text = _build_followup_summary(
            status=request.status,
            duration_seconds=request.durationSeconds,
            symptoms=symptoms,
            evolution=normalized_evolution,
            recommendations=recommendations,
            insights=insights,
            fallback=(request.summary or "").strip(),
        )
        profile_conditions = symptoms or _unique_compact(list(insights.get("symptoms") or []))
        profile_allergies = _unique_compact(list(insights.get("allergies") or []))

        try:
            call_record_id = self._persistence_client.persist_outbound_followup_result(
                followup_call_id=request.followupCallId,
                appointment_id=request.appointmentId,
                patient_id=request.patientId,
                patient_phone=request.patientPhone,
                status=request.status,
                duration_seconds=request.durationSeconds,
                summary=summary_text,
                symptoms=symptoms,
                recommendations=recommendations,
                evolution=normalized_evolution,
                followup_task_id=request.followupTaskId,
                profile_conditions=profile_conditions,
                profile_allergies=profile_allergies,
                profile_note=summary_text,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to persist outbound follow-up result: %s", exc)
            call_record_id = None

        self.add_event(
            stage_id="post-consultation-followup",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={
                "followup_type": "call",
                "followup_call_id": request.followupCallId,
                "status": request.status,
                "duration_seconds": request.durationSeconds,
                "call_record_id": call_record_id,
            },
        )

        return {
            "ok": True,
            "followupCallId": request.followupCallId,
            "callRecordId": call_record_id,
            "updated": {
                "call_records": bool(call_record_id),
                "followup_tasks": True,
                "lifecycle_events": True,
                "patient_profile": bool(profile_conditions or profile_allergies),
            },
        }

    def list_dashboard_appointments(self, *, date_value: str | None = None) -> DashboardAppointmentsResponse:
        rows = self._persistence_client.list_dashboard_appointments(date_value=date_value)
        return DashboardAppointmentsResponse(
            appointments=[DashboardAppointment.model_validate(item) for item in rows]
        )

    def list_dashboard_patients(self) -> DashboardPatientsResponse:
        rows = self._persistence_client.list_dashboard_patients()
        return DashboardPatientsResponse(
            patients=[DashboardPatient.model_validate(item) for item in rows]
        )

    def list_agenda_appointments(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> DashboardAppointmentsResponse:
        rows = self._persistence_client.list_agenda_appointments(
            date_from=date_from,
            date_to=date_to,
        )
        return DashboardAppointmentsResponse(
            appointments=[DashboardAppointment.model_validate(item) for item in rows]
        )

    def get_appointment_detail(self, appointment_id: str) -> DashboardAppointmentDetailResponse | None:
        row = self._persistence_client.get_appointment_detail(appointment_id)
        if not row:
            return None
        return DashboardAppointmentDetailResponse(
            appointment=DashboardAppointment.model_validate(row["appointment"]),
            patient=DashboardPatient.model_validate(row["patient"]),
            history=[PastAppointmentRecord.model_validate(item) for item in row.get("history", [])],
            calls=[DashboardCallRecord.model_validate(item) for item in row.get("calls", [])],
        )

    def get_patient_detail(self, patient_id: str) -> DashboardPatientDetailResponse | None:
        row = self._persistence_client.get_patient_detail(patient_id)
        if not row:
            return None
        return DashboardPatientDetailResponse(
            patient=DashboardPatient.model_validate(row["patient"]),
            appointments=[DashboardAppointment.model_validate(item) for item in row.get("appointments", [])],
            calls=[DashboardCallRecord.model_validate(item) for item in row.get("calls", [])],
        )

    def cancel_appointment(
        self,
        appointment_id: str,
        *,
        reason: str | None = None,
    ) -> CancelAppointmentResponse | None:
        cancelled = self._persistence_client.cancel_appointment_and_queue_callback(
            appointment_id,
            reason=reason,
        )
        if not cancelled:
            return None
        return CancelAppointmentResponse(
            appointmentId=cancelled.appointment_id,
            status="cancelled",
            callbackScheduled=cancelled.callback_scheduled,
            callbackTaskId=cancelled.callback_task_id,
            callbackScheduledAt=(
                cancelled.callback_scheduled_at.isoformat()
                if cancelled.callback_scheduled_at
                else None
            ),
            patientId=cancelled.patient_id,
            patientPhone=cancelled.patient_phone,
        )

    def get_dashboard_overview(self, *, date_value: str | None = None) -> DashboardOverviewResponse:
        data = self._persistence_client.get_dashboard_overview(date_value=date_value)
        return DashboardOverviewResponse(
            kpis=DashboardKpis.model_validate(data.get("kpis", {})),
            callbackTasks=[
                DashboardCallbackTask.model_validate(item)
                for item in data.get("callbackTasks", [])
            ],
            priorityQueue=[
                DashboardPriorityItem.model_validate(item)
                for item in data.get("priorityQueue", [])
            ],
            nextAppointments=[
                DashboardAppointment.model_validate(item)
                for item in data.get("nextAppointments", [])
            ],
        )

    async def get_booking_availability(
        self,
        *,
        timezone_name: str | None = None,
        days_ahead: int = 10,
        limit: int = 5,
        event_type_id: int | None = None,
    ) -> dict:
        slots = await self._calcom_client.get_available_slots(
            timezone=timezone_name,
            days_ahead=days_ahead,
            limit=limit,
            event_type_id=event_type_id,
        )
        return {
            "timezone": timezone_name or self._calcom_client.config.calcom_timezone,
            "slots": [{"startsAt": slot} for slot in slots],
            "count": len(slots),
            "source": "calcom" if self._calcom_client.enabled else "mock",
        }

    async def book_appointment_and_confirm(
        self,
        request: BookAppointmentRequest,
        *,
        created_via: str = "api",
    ) -> BookAppointmentResponse:
        booking = await self._calcom_client.create_booking(
            patient_name=request.patientName,
            patient_email=request.patientEmail,
            patient_phone=request.patientPhone,
            starts_at_iso=request.startsAt,
            reason=request.reason,
            timezone=request.timezone,
            event_type_id=request.eventTypeId,
            duration_minutes=request.durationMinutes,
        )

        confirmation_message = (
            f"Hello {request.patientName}, your appointment is confirmed for {booking.start_at}. "
            f"Reason: {request.reason}."
        )
        if booking.meeting_url:
            confirmation_message += f" Meeting link: {booking.meeting_url}"

        sms = self._sms_client.send_confirmation_sms(
            to_phone=request.patientPhone,
            body=confirmation_message,
        )

        try:
            persisted = self._persistence_client.persist_booking_bundle(
                request=request,
                booking=booking,
                sms=sms,
                created_via=created_via,
            )
            appointment_id = persisted.appointment_id
        except Exception as exc:  # pragma: no cover
            logger.exception("DB persistence failed after successful Cal booking: %s", exc)
            fallback_appointment_id = f"apt-{booking.booking_id or datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            from app.integrations.persistence_client import PersistedBookingResult
            persisted = PersistedBookingResult(
                saved=False,
                appointment_id=fallback_appointment_id,
                consultation_id=None,
                call_record_id=None,
            )
            appointment_id = persisted.appointment_id

        self.add_event(
            stage_id="patient-call",
            appointment_id=appointment_id,
            patient_id=request.patientId,
            payload={
                "patient_name": request.patientName,
                "starts_at": booking.start_at,
                "booking_id": booking.booking_id,
                "calendar_provider": "cal.com",
                "persisted_to_db": persisted.saved,
            },
        )
        self.add_event(
            stage_id="day-before-confirmation",
            appointment_id=appointment_id,
            patient_id=request.patientId,
            payload={
                "sms_sid": sms.sid,
                "sms_status": sms.status,
                "message_type": "booking_confirmation",
            },
        )

        return BookAppointmentResponse(
            appointmentId=appointment_id,
            calcomBookingId=booking.booking_id,
            meetingUrl=booking.meeting_url,
            smsSid=sms.sid,
            smsStatus=sms.status,
            confirmationMessage=confirmation_message,
            createdVia="livekit_tool" if created_via == "livekit_tool" else "api",
            persistedToDb=persisted.saved,
            consultationId=persisted.consultation_id,
            callRecordId=persisted.call_record_id,
        )

    @property
    def event_count(self) -> int:
        return len(self._events)


service = LifecycleService()
