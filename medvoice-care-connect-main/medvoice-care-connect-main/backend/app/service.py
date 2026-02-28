from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from app.config import load_calendar_config, load_sms_config
from app.integrations.calcom_client import CalComClient
from app.integrations.twilio_client import TwilioSmsClient
from app.lifecycle import default_lifecycle_stages
from app.models import (
    BookAppointmentRequest,
    BookAppointmentResponse,
    ConsultationSummaryRequest,
    ConsultationSummaryResponse,
    ConsultationSessionState,
    LifecycleEvent,
    LifecycleStage,
    SuggestQuestionsRequest,
    SuggestQuestionsResponse,
    TranscriptMessageInput,
)


class LifecycleService:
    def __init__(self) -> None:
        self._stages = default_lifecycle_stages()
        self._events: list[LifecycleEvent] = []
        self._transcripts: dict[str, list[TranscriptMessageInput]] = defaultdict(list)
        self._consultation_sessions: dict[str, ConsultationSessionState] = {}
        self._calcom_client = CalComClient(load_calendar_config())
        self._sms_client = TwilioSmsClient(load_sms_config())

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

    def generate_summary(
        self, request: ConsultationSummaryRequest
    ) -> ConsultationSummaryResponse:
        # If transcript is omitted, use what was already streamed in consultation/transcript endpoint.
        transcript = request.transcript or self._transcripts.get(request.appointmentId, [])
        self.save_transcript(request.appointmentId, transcript)
        self.add_event(
            stage_id="consultation-end-prescription",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={"messages": len(transcript), "finished_at": datetime.now(timezone.utc).isoformat()},
        )
        self.add_event(
            stage_id="post-consultation-followup",
            appointment_id=request.appointmentId,
            patient_id=request.patientId,
            payload={"followup_type": "sms"},
        )
        self.end_consultation(request.appointmentId)

        joined = " ".join(message.text.lower() for message in transcript)
        has_fever = "fievre" in joined or "fièvre" in joined
        has_throat = "gorge" in joined

        summary = (
            "Patient avec douleur pharyngee, dysphagie et syndrome infectieux compatible "
            "avec angine bacterienne probable."
            if has_fever and has_throat
            else "Consultation resumee automatiquement a partir de la transcription."
        )

        symptoms = ["Douleur gorge", "Dysphagie"] if has_throat else ["Symptomes non specifiques"]
        if has_fever:
            symptoms.append("Fievre")

        return ConsultationSummaryResponse(
            summary=summary,
            detectedSymptoms=symptoms,
            diagnoses=[
                "Angine bacterienne (streptocoque probable)",
                "Pharyngite aigue",
                "Infection virale VAS",
            ],
            prescription={
                "medications": [
                    {
                        "name": "Amoxicilline",
                        "dosage": "1g",
                        "frequency": "3 fois par jour",
                        "duration": "6 jours",
                    },
                    {
                        "name": "Paracetamol",
                        "dosage": "1000mg",
                        "frequency": "Toutes les 6h si douleur",
                        "duration": "5 jours",
                    },
                ],
                "additionalAdvice": [
                    "Hydratation abondante",
                    "Repos vocal",
                    "Reconsulter si aggravation sous 48h",
                ],
            },
        )

    def suggest_questions(
        self, request: SuggestQuestionsRequest
    ) -> SuggestQuestionsResponse:
        joined = " ".join(message.text.lower() for message in request.transcript)

        topics = {
            "duree": ["depuis", "jours", "semaines", "durée", "duree"],
            "fievre": ["fievre", "fièvre", "temperature", "température"],
            "douleur": ["douleur", "mal", "intensite", "intensité"],
            "allergies": ["allergie", "allergies"],
            "traitements": ["traitement", "medicament", "médicament", "prise"],
            "redflag_resp": ["essoufflement", "dyspnee", "dyspnée", "respirer"],
            "redflag_chest": ["douleur thoracique", "poitrine"],
            "redflag_confusion": ["confusion", "desoriente", "désorienté"],
        }

        asked_topics = [
            topic
            for topic, keywords in topics.items()
            if any(keyword in joined for keyword in keywords)
        ]

        questions: list[str] = []
        if "duree" not in asked_topics:
            questions.append("Depuis quand exactement les symptomes ont-ils commence ?")
        if "fievre" not in asked_topics:
            questions.append("Avez-vous eu de la fievre, et a combien ?")
        if "douleur" not in asked_topics:
            questions.append("Sur une echelle de 0 a 10, quelle est l'intensite de la douleur ?")
        if "allergies" not in asked_topics:
            questions.append("Avez-vous des allergies medicamenteuses connues ?")
        if "traitements" not in asked_topics:
            questions.append("Avez-vous deja pris un traitement pour ce probleme ?")

        red_flags: list[str] = []
        if "redflag_resp" in asked_topics:
            red_flags.append("Difficulte respiratoire detectee")
        if "redflag_chest" in asked_topics:
            red_flags.append("Douleur thoracique mentionnee")
        if "redflag_confusion" in asked_topics:
            red_flags.append("Confusion mentionnee")

        if not questions:
            questions.append("Les symptomes ont-ils tendance a s'ameliorer ou a s'aggraver ?")

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

        appointment_id = f"apt-{booking.booking_id or uuid4().hex[:8]}"
        confirmation_message = (
            f"Bonjour {request.patientName}, votre RDV est confirme le {booking.start_at}. "
            f"Motif: {request.reason}."
        )
        if booking.meeting_url:
            confirmation_message += f" Lien: {booking.meeting_url}"

        sms = self._sms_client.send_confirmation_sms(
            to_phone=request.patientPhone,
            body=confirmation_message,
        )

        self.add_event(
            stage_id="patient-call",
            appointment_id=appointment_id,
            patient_id=request.patientId,
            payload={
                "patient_name": request.patientName,
                "starts_at": booking.start_at,
                "booking_id": booking.booking_id,
                "calendar_provider": "cal.com",
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
        )

    @property
    def event_count(self) -> int:
        return len(self._events)


service = LifecycleService()
