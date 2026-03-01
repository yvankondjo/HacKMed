from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


LifecycleStatus = Literal["done", "active", "next"]


class LifecycleTableImpact(BaseModel):
    table: str
    eventLabel: str


class LifecycleStage(BaseModel):
    id: str
    title: str
    description: str
    status: LifecycleStatus
    impactedTables: list[LifecycleTableImpact]


class TranscriptMessageInput(BaseModel):
    speaker: Literal["Doctor", "Patient", "AI"]
    text: str = Field(min_length=1)
    timestamp: str | None = None


class LifecycleEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    stage_id: str
    appointment_id: str | None = None
    patient_id: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StartConsultationRequest(BaseModel):
    appointmentId: str
    patientId: str
    doctorId: str | None = None


class EndConsultationRequest(BaseModel):
    appointmentId: str


class ConsultationSummaryRequest(BaseModel):
    appointmentId: str
    patientId: str
    transcript: list[TranscriptMessageInput] = Field(default_factory=list)


class Medication(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str


class ConsultationSummaryResponse(BaseModel):
    summary: str
    detectedSymptoms: list[str]
    diagnoses: list[str]
    prescription: dict


class SuggestQuestionsRequest(BaseModel):
    appointmentId: str
    patientId: str
    transcript: list[TranscriptMessageInput]


class SuggestQuestionsResponse(BaseModel):
    questions: list[str]
    redFlags: list[str]
    askedTopics: list[str]


class StageProgressResponse(BaseModel):
    stages: list[LifecycleStage]
    eventCount: int


class BookAppointmentRequest(BaseModel):
    patientId: str
    patientName: str
    patientPhone: str
    patientEmail: str
    reason: str
    startsAt: str
    timezone: str | None = None
    eventTypeId: int | None = None
    durationMinutes: int = 20


class BookAppointmentResponse(BaseModel):
    appointmentId: str
    calcomBookingId: str
    meetingUrl: str | None = None
    smsSid: str
    smsStatus: str
    confirmationMessage: str
    createdVia: Literal["livekit_tool", "api"]


class ConsultationSessionState(BaseModel):
    appointmentId: str
    patientId: str
    status: Literal["not_started", "active", "ended"] = "not_started"
    startedAt: str | None = None
    endedAt: str | None = None
    transcriptCount: int = 0
    latestSuggestedQuestions: list[str] = Field(default_factory=list)
    latestRedFlags: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    token: str
    url: str
