from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any, Iterable
from uuid import uuid4

from app.config import load_calendar_config, load_persistence_config, load_sms_config
from app.integrations.calcom_client import CalComClient
from app.integrations.livekit_dispatcher import DispatchResult, LiveKitOutboundDispatcher
from app.integrations.persistence_client import PostgresPersistenceClient
from app.integrations.resend_email import send_prescription_to_patient
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
    SendPrescriptionRequest,
    SendPrescriptionResponse,
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


def _coerce_transcript_entry(raw: Any) -> TranscriptMessageInput | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None

    speaker_raw = str(raw.get("speaker") or "").strip().lower()
    if speaker_raw in {"doctor", "dr", "dr.", "assistant", "system"}:
        speaker = "Doctor"
    elif speaker_raw in {"patient", "caller", "user"}:
        speaker = "Patient"
    elif speaker_raw == "ai":
        speaker = "AI"
    else:
        return None

    timestamp_raw = raw.get("timestamp")
    timestamp = str(timestamp_raw).strip() if timestamp_raw is not None else None
    if timestamp == "":
        timestamp = None
    try:
        return TranscriptMessageInput(speaker=speaker, text=text, timestamp=timestamp)
    except Exception:
        return None


def _extract_adjudicated_transcript_from_soap(soap: dict[str, Any] | None) -> list[TranscriptMessageInput]:
    if not isinstance(soap, dict):
        return []
    for key in ("adjudicated_transcript", "enhanced_transcript"):
        raw = soap.get(key)
        if not isinstance(raw, list):
            continue
        parsed: list[TranscriptMessageInput] = []
        for item in raw:
            entry = _coerce_transcript_entry(item)
            if entry is not None:
                parsed.append(entry)
        if parsed:
            return parsed
    return []


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


_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _word_to_int(token: str) -> int | None:
    text = (token or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None
    return _NUMBER_WORDS.get(text)


def _text_window_around_alias(text: str, aliases: tuple[str, ...], radius: int = 140) -> str:
    lowered = (text or "").lower()
    if not lowered:
        return ""
    for alias in aliases:
        idx = lowered.find(alias.lower())
        if idx == -1:
            continue
        start = max(0, idx - radius)
        end = min(len(text), idx + radius)
        return text[start:end]
    return text


def _extract_med_frequency(text: str) -> str:
    lowered = (text or "").lower()
    patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bevery\s*(\d{1,2})\s*(?:h|hr|hrs|hour|hours)\b"), "Every {n} hours"),
        (re.compile(r"\btwice(?:\s+(?:a|per))?\s+day\b"), "Twice daily"),
        (re.compile(r"\b(?:2|two)\s+times(?:\s+(?:a|per))?\s+day\b"), "Twice daily"),
        (re.compile(r"\bthree\s+times(?:\s+(?:a|per))?\s+day\b"), "3 times daily"),
        (re.compile(r"\b(?:3|three)\s*x\s*(?:a|per)?\s*day\b"), "3 times daily"),
        (re.compile(r"\bonce(?:\s+(?:a|per))?\s+day\b"), "Once daily"),
        (re.compile(r"\bas needed\b"), "As needed"),
    ]
    for pattern, label in patterns:
        match = pattern.search(lowered)
        if not match:
            continue
        if "{n}" in label:
            return label.format(n=match.group(1))
        return label
    return ""


def _extract_med_duration(text: str) -> str:
    lowered = (text or "").lower()
    match = re.search(
        r"\bfor\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(day|days|week|weeks|month|months)\b",
        lowered,
    )
    if match:
        number = _word_to_int(match.group(1))
        if number is not None:
            unit = match.group(2)
            return f"{number} {unit}"
    if "as needed" in lowered:
        return "As needed"
    return ""


def _extract_med_dosage(text: str) -> str:
    lowered = (text or "").lower()
    match = re.search(r"\b(\d{1,4}(?:\.\d+)?)\s*(mg|g|mcg|µg)\b", lowered)
    if not match:
        return ""
    value = match.group(1)
    unit = match.group(2)
    return f"{value} {unit}"


def _plan_score(text: str) -> int:
    lowered = (text or "").lower()
    cues = (
        "prescribe",
        "prescription",
        "take",
        "dose",
        "session",
        "physio",
        "physiotherapist",
        "paracetamol",
        "ibuprofen",
        "amoxicillin",
        "azithromycin",
        "antibiotic",
    )
    return sum(lowered.count(cue) for cue in cues)


def _select_prescriber_text(transcript: list[TranscriptMessageInput]) -> tuple[str, str]:
    doctor_lines: list[str] = []
    patient_lines: list[str] = []
    all_lines: list[str] = []

    for item in transcript:
        line = str(item.text or "").strip()
        if not line:
            continue
        all_lines.append(line)
        role = _normalize_transcript_speaker(item.speaker)
        if role == "doctor":
            doctor_lines.append(line)
        elif role == "patient":
            patient_lines.append(line)

    doctor_blob = " ".join(doctor_lines)
    patient_blob = " ".join(patient_lines)
    all_blob = " ".join(all_lines)

    doctor_score = _plan_score(doctor_blob)
    patient_score = _plan_score(patient_blob)

    if patient_score > doctor_score and patient_lines:
        selected = patient_blob
        source = "patient"
    elif doctor_lines:
        selected = doctor_blob
        source = "doctor"
    else:
        selected = all_blob
        source = "all"

    if _plan_score(selected) == 0 and all_blob:
        selected = all_blob
        source = "all"

    return selected, source


def _extract_plan_medications(plan_text: str) -> list[dict[str, str]]:
    text = str(plan_text or "").strip()
    lowered = text.lower()
    meds: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add_med(name: str, window: str, *, default_dose: str = "", default_freq: str = "", default_duration: str = "") -> None:
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        dosage = _extract_med_dosage(window) or default_dose
        frequency = _extract_med_frequency(window) or default_freq
        duration = _extract_med_duration(window) or default_duration
        meds.append(
            {
                "name": name,
                "dosage": dosage,
                "frequency": frequency,
                "duration": duration,
            }
        )

    has_physio = _has_any(lowered, ("physio", "physiotherapy", "physiotherapist"))
    physio_negated = re.search(
        r"(?:do not|don't|no)\s+(?:go|need|start|do).{0,35}(?:physio|physiotherapy|physiotherapist)",
        lowered,
    )
    if has_physio and (not physio_negated or re.search(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+sessions?\b", lowered)):
        window = _text_window_around_alias(text, ("physio", "physiotherapy", "physiotherapist"))
        sessions = 0
        session_match = re.search(
            r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+sessions?\b",
            lowered,
        )
        if session_match:
            sessions = _word_to_int(session_match.group(1)) or 0
        dosage = f"{sessions} sessions" if sessions > 0 else "As prescribed"
        frequency = _extract_med_frequency(window) or "As prescribed"
        duration = _extract_med_duration(window) or ""
        if sessions > 0 and not duration and frequency:
            freq_match = re.search(r"\b(\d{1,2}|one|two|three)\s+sessions?\s+(?:per|a)\s+week\b", lowered)
            if freq_match:
                per_week = _word_to_int(freq_match.group(1)) or 0
                if per_week > 0:
                    approx_weeks = max(1, round(sessions / per_week))
                    duration = f"{approx_weeks} weeks"
        meds.append(
            {
                "name": "Physiotherapy sessions",
                "dosage": dosage,
                "frequency": frequency,
                "duration": duration,
            }
        )
        seen.add("physiotherapy sessions")

    paracetamol_aliases = ("paracetamol", "acetaminophen", "etamol")
    if any(alias in lowered for alias in paracetamol_aliases):
        window = _text_window_around_alias(text, paracetamol_aliases)
        _add_med("Paracetamol", window, default_freq="As needed")

    ibuprofen_aliases = ("ibuprofen",)
    if any(alias in lowered for alias in ibuprofen_aliases):
        window = _text_window_around_alias(text, ibuprofen_aliases)
        _add_med("Ibuprofen", window, default_freq="As needed")

    amoxicillin_aliases = ("amoxicillin", "amoxicilline")
    if any(alias in lowered for alias in amoxicillin_aliases):
        window = _text_window_around_alias(text, amoxicillin_aliases)
        _add_med("Amoxicillin", window)

    azithromycin_aliases = ("azithromycin",)
    if any(alias in lowered for alias in azithromycin_aliases):
        window = _text_window_around_alias(text, azithromycin_aliases)
        _add_med("Azithromycin", window)

    if "antibiotic" in lowered and not any(
        med["name"].lower() in {"amoxicillin", "azithromycin"} for med in meds
    ):
        window = _text_window_around_alias(text, ("antibiotic", "antibiotics"))
        _add_med("Antibiotic (doctor-specified)", window)

    return meds


def _extract_dynamic_diagnoses(combined_text: str, detected_symptoms: list[str]) -> list[str]:
    lowered = (combined_text or "").lower()
    diagnoses: list[str] = []

    if _has_any(lowered, ("back pain", "lower back", "lumbar", "lumbago", "sciatica")):
        diagnoses.append("Low-back pain syndrome")
    if _has_any(lowered, ("numbness in my leg", "numbness in my legs", "radiat", "sciatica", "leg pain")):
        diagnoses.append("Possible lumbar radicular involvement")
    if _has_any(lowered, ("virus", "viral")):
        diagnoses.append("Possible viral syndrome")
    if _has_any(lowered, ("infection", "antibiotic", "bacterial")):
        diagnoses.append("Possible infectious etiology (to confirm clinically)")
    if _has_any(lowered, ("can't walk", "cannot walk", "difficulty walking")):
        diagnoses.append("Functional impairment due to pain")

    if not diagnoses and detected_symptoms:
        diagnoses.extend(f"Symptom-focused assessment: {symptom}" for symptom in detected_symptoms[:2])

    if not diagnoses:
        diagnoses.append("Clinical assessment to be confirmed from consultation findings")

    return _unique_compact(diagnoses)[:4]


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
        self._followup_default_phone = (os.getenv("FOLLOWUP_TEST_PHONE") or "0765540003").strip()
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

    def send_prescription(self, request: SendPrescriptionRequest) -> SendPrescriptionResponse:
        logger.info(f"Received request to send prescription for {request.patientName} to {request.patientEmail}")
        
        self.add_event(
            stage_id="consultation-end-prescription",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={"action": "send_prescription", "medications": len(request.medications)}
        )
        
        meds = [med.model_dump() for med in request.medications]
        
        logger.info("Calling resend API integration...")
        
        result = send_prescription_to_patient(
            transcript=[msg.model_dump() for msg in request.transcript],
            patient_name=request.patientName,
            doctor_name=request.doctorName,
            appointment_id=request.appointmentId,
            medications=meds,
            patient_email=request.patientEmail,
            additional_advice=request.additionalAdvice,
        )
        
        logger.info(f"Resend integration returned: ok={result.ok}, status={result.status}, detail={result.detail}")
        
        return SendPrescriptionResponse(
            ok=result.ok,
            status=result.status,
            messageId=result.message_id,
            to=result.to,
            detail=result.detail,
        )

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
        history_highlights: list[str] = []

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
            history_highlights = [
                " - ".join(
                    value
                    for value in (
                        str(item.motif or "").strip(),
                        str(item.summary or "").strip(),
                    )
                    if value
                ).strip()
                for item in detail.history
                if str(item.motif or "").strip() or str(item.summary or "").strip()
            ][:4]
            if allergies:
                context_signals.append(f"Known allergies: {', '.join(allergies)}")
            if antecedents:
                context_signals.append(f"Chronic conditions: {', '.join(antecedents)}")
            if historical_symptoms:
                context_signals.append(
                    f"Symptoms seen in previous calls: {', '.join(historical_symptoms[:5])}"
                )
            if history_highlights:
                context_signals.append(
                    f"Recent consultation history: {history_highlights[0][:160]}"
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
            "history_highlights": history_highlights,
            "context_signals": context_signals,
        }

    def generate_summary(
        self, request: ConsultationSummaryRequest
    ) -> ConsultationSummaryResponse:
        # Prefer adjudicated transcript when available to improve role consistency
        # and medication-plan extraction quality.
        adjudicated_transcript = _extract_adjudicated_transcript_from_soap(request.soap)
        transcript_source = "adjudicated"
        if adjudicated_transcript:
            transcript = adjudicated_transcript
        else:
            transcript_source = "raw"
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

        has_red_flag = any(
            sym.lower() in {"shortness of breath", "chest pain"} for sym in detected_symptoms
        ) or _has_any(combined, ("shortness of breath", "cannot breathe", "chest pain"))

        allergy_text = " ".join(context["allergies"]).lower()
        penicillin_allergy = _has_any(allergy_text, ("penicillin", "amoxicillin"))
        nsaid_allergy = _has_any(
            allergy_text,
            ("aspirin", "ibuprofen", "naproxen", "nsaid", "anti inflammatory"),
        )

        prescriber_text, prescriber_source = _select_prescriber_text(transcript)
        prescriber_blob = " ".join(
            [combined, prescriber_text, soap_blob]
            if prescriber_text
            else [combined, soap_blob]
        ).strip()

        diagnoses = _extract_dynamic_diagnoses(prescriber_blob, detected_symptoms)
        medications = _extract_plan_medications(prescriber_text)
        if not medications:
            # Fallback if speaker roles were swapped and the plan was spoken by the other role.
            medications = _extract_plan_medications(combined)

        if nsaid_allergy:
            medications = [
                med for med in medications if "ibuprofen" not in str(med.get("name", "")).lower()
            ]
        if penicillin_allergy:
            medications = [
                med
                for med in medications
                if "amoxicillin" not in str(med.get("name", "")).lower()
            ]

        if not medications and isinstance(request.soap.get("meds_mentioned"), list):
            for item in request.soap.get("meds_mentioned", []):
                name = str(item or "").strip()
                if not name:
                    continue
                medications.append(
                    {
                        "name": name,
                        "dosage": "",
                        "frequency": "As prescribed",
                        "duration": "",
                    }
                )

        additional_advice: list[str] = []
        if _has_any(prescriber_blob, ("avoid heavy lifting", "no heavy lifting")):
            additional_advice.append("Avoid heavy lifting until symptoms improve.")
        if _has_any(prescriber_blob, ("rest", "hydration", "drink fluids")):
            additional_advice.append("Follow the hydration/rest advice discussed during the consultation.")
        if has_red_flag or _has_any(prescriber_blob, ("numbness", "weakness", "bladder", "bowel")):
            additional_advice.append(
                "Urgent reassessment is required if weakness, numbness, bladder/bowel changes, chest pain, or breathing issues occur."
            )
        if penicillin_allergy and any("amoxicillin" in str(med.get("name", "")).lower() for med in medications):
            additional_advice.append(
                f"Allergy conflict detected with documented allergies: {', '.join(context['allergies'])}."
            )
        if not additional_advice:
            additional_advice.append("Follow the clinician instructions discussed during the consultation and monitor symptom evolution.")

        if isinstance(request.soap.get("followups"), list):
            additional_advice.extend(str(item).strip() for item in request.soap.get("followups", []))

        diagnoses = _unique_compact(diagnoses)[:4]
        prescription = {
            "medications": medications,
            "additionalAdvice": _unique_compact(additional_advice),
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
        if medications:
            summary_chunks.append(
                f"Prescription extracted from consultation dialogue ({prescriber_source}-led plan parsing)."
            )
        if transcript_source == "adjudicated":
            summary_chunks.append("Adjudicated transcript was prioritized for prescription extraction.")
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
        context = self._load_summary_context(request.appointmentId, request.patientId)
        appointment_detail = self.get_appointment_detail(request.appointmentId)
        motif = (
            (appointment_detail.appointment.motif if appointment_detail else "")
            or ""
        ).strip()

        doctor_text = " ".join(
            (message.text or "").strip().lower()
            for message in request.transcript
            if _normalize_transcript_speaker(message.speaker) == "doctor"
        )
        patient_text = " ".join(
            (message.text or "").strip().lower()
            for message in request.transcript
            if _normalize_transcript_speaker(message.speaker) == "patient"
        )
        joined = f"{doctor_text} {patient_text}".strip()
        joined_with_motif = f"{motif.lower()} {joined}".strip()

        def _mentions(keywords: tuple[str, ...], *, source: str | None = None) -> bool:
            haystack = source if source is not None else joined_with_motif
            return any(keyword in haystack for keyword in keywords)

        topic_keywords: dict[str, tuple[str, ...]] = {
            "duration": ("when did", "since", "started", "for two", "for three", "for one"),
            "severity": ("0 to 10", "/10", "severity", "intensity", "how severe"),
            "allergies": ("allergy", "allergies", "allergic"),
            "treatments": (
                "treatment",
                "medication",
                "medicine",
                "taken",
                "paracetamol",
                "ibuprofen",
                "physio",
                "physiotherapy",
            ),
            "redflag_resp": ("shortness of breath", "dyspnea", "cannot breathe"),
            "redflag_chest": ("chest pain", "chest tightness"),
            "redflag_confusion": ("confusion", "disoriented", "disorientation"),
            "redflag_neuro": ("numbness", "weakness", "bladder", "bowel", "saddle"),
        }
        asked_topics = [
            topic
            for topic, keywords in topic_keywords.items()
            if _mentions(keywords)
        ]

        questions: list[str] = []

        def _push_question(text: str) -> None:
            label = (text or "").strip()
            if not label:
                return
            if label in questions:
                return
            if len(questions) >= 5:
                return
            questions.append(label)

        is_back_pain_case = _mentions(
            (
                "back pain",
                "low back",
                "lower back",
                "lumbar",
                "lumbago",
                "sciatica",
            )
        )

        if is_back_pain_case:
            if "duration" not in asked_topics:
                _push_question("When exactly did this back pain episode start?")
            if "severity" not in asked_topics:
                _push_question("On a scale of 0 to 10, how severe is the back pain now?")
            if not _mentions(("radiat", "leg pain", "shooting pain", "sciatica")):
                _push_question("Does the pain radiate to one leg, or stay localized in the back?")
            if "redflag_neuro" not in asked_topics:
                _push_question("Any numbness, weakness, or bladder/bowel changes since the pain began?")
            if not _mentions(("lifting", "trauma", "fall", "injury", "trigger", "after effort")):
                _push_question("Did it begin after lifting, a fall, or another specific trigger?")
            if "treatments" not in asked_topics:
                _push_question("What have you already tried (paracetamol, physiotherapy, or other treatments)?")
            if context["history_highlights"]:
                _push_question("Compared with prior episodes, is this pain stronger or lasting longer?")
        else:
            if "duration" not in asked_topics:
                _push_question("When exactly did these symptoms start?")
            if not _mentions(("worse", "better", "improv", "stable", "evolving")):
                _push_question("Are symptoms improving, stable, or getting worse?")
            if "severity" not in asked_topics and _mentions(("pain", "ache", "hurts")):
                _push_question("On a scale of 0 to 10, how severe is the pain right now?")
            if "treatments" not in asked_topics:
                _push_question("Have you already taken any treatment for this issue?")

        if "allergies" not in asked_topics:
            if context["allergies"]:
                _push_question(
                    f"Can you confirm medication allergies before prescribing ({', '.join(context['allergies'][:2])})?"
                )
            else:
                _push_question("Do you have any known medication allergies?")

        if context["antecedents"] and not _mentions(("medical history", "chronic", "antecedent", "baseline")):
            history_hint = str(context["antecedents"][0]).strip()[:60]
            if history_hint:
                _push_question(
                    f"Any recent change in your baseline condition related to {history_hint}?"
                )

        red_flags: list[str] = []
        if "redflag_resp" in asked_topics:
            red_flags.append("Breathing difficulty detected")
        if "redflag_chest" in asked_topics:
            red_flags.append("Chest pain mentioned")
        if "redflag_confusion" in asked_topics:
            red_flags.append("Confusion mentioned")
        if is_back_pain_case and "redflag_neuro" in asked_topics:
            red_flags.append("Neurological red flag terms mentioned for back pain")

        if not questions:
            questions.append("Are symptoms improving, stable, or getting worse?")

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
