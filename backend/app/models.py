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
    symptoms: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    conversationSummary: str | None = None
    transcript: list[TranscriptMessageInput] = Field(default_factory=list)
    callStartedAt: str | None = None
    callEndedAt: str | None = None
    recordingUrl: str | None = None
    createdVia: Literal["livekit_tool", "api"] = "api"


class BookAppointmentResponse(BaseModel):
    appointmentId: str
    calcomBookingId: str
    meetingUrl: str | None = None
    smsSid: str
    smsStatus: str
    confirmationMessage: str
    createdVia: Literal["livekit_tool", "api"]
    persistedToDb: bool = False
    consultationId: str | None = None
    callRecordId: str | None = None


class ConsultationSessionState(BaseModel):
    appointmentId: str
    patientId: str
    status: Literal["not_started", "active", "ended"] = "not_started"
    startedAt: str | None = None
    endedAt: str | None = None
    transcriptCount: int = 0
    latestSuggestedQuestions: list[str] = Field(default_factory=list)
    latestRedFlags: list[str] = Field(default_factory=list)


class DashboardAppointment(BaseModel):
    id: str
    patientId: str
    patientName: str
    patientPhone: str
    date: str
    time: str
    startsAt: str
    endsAt: str | None = None
    doctor: str
    doctorSpecialty: str
    motif: str
    status: Literal["upcoming", "in-progress", "done"]
    rawStatus: str
    notes: str | None = None
    aiSummary: str | None = None


class DashboardAppointmentsResponse(BaseModel):
    appointments: list[DashboardAppointment]


class DashboardPatient(BaseModel):
    id: str
    firstName: str
    lastName: str
    dateOfBirth: str | None = None
    phone: str
    email: str
    bloodType: str | None = None
    allergies: list[str] = Field(default_factory=list)
    antecedents: list[str] = Field(default_factory=list)
    lastAppointmentDate: str | None = None
    lastAppointmentMotif: str | None = None
    upcomingAppointmentsCount: int = 0


class DashboardPatientsResponse(BaseModel):
    patients: list[DashboardPatient]


class PastAppointmentRecord(BaseModel):
    date: str
    motif: str
    doctor: str
    summary: str


class DashboardCallRecord(BaseModel):
    id: str
    patientId: str
    appointmentId: str | None = None
    date: str
    duration: str
    motif: str
    symptoms: list[str] = Field(default_factory=list)
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    evolution: Literal["improvement", "worsening", "stable"] | str = "stable"
    urgencyScore: int = 0


class DashboardAppointmentDetailResponse(BaseModel):
    appointment: DashboardAppointment
    patient: DashboardPatient
    history: list[PastAppointmentRecord] = Field(default_factory=list)
    calls: list[DashboardCallRecord] = Field(default_factory=list)


class CancelAppointmentRequest(BaseModel):
    reason: str | None = None


class CancelAppointmentResponse(BaseModel):
    appointmentId: str
    status: Literal["cancelled"]
    callbackScheduled: bool
    callbackTaskId: str | None = None
    callbackScheduledAt: str | None = None
    patientId: str | None = None
    patientPhone: str | None = None


class DashboardPatientDetailResponse(BaseModel):
    patient: DashboardPatient
    appointments: list[DashboardAppointment] = Field(default_factory=list)
    calls: list[DashboardCallRecord] = Field(default_factory=list)


class DashboardKpis(BaseModel):
    appointmentsToday: int = 0
    callsToday: int = 0
    cancellationsToday: int = 0
    pendingCallbacks: int = 0


class DashboardCallbackTask(BaseModel):
    id: str
    patientId: str
    patientName: str
    patientPhone: str
    scheduledAt: str
    notes: str | None = None
    status: str


class DashboardPriorityItem(BaseModel):
    id: str
    patientId: str
    patientName: str
    patientPhone: str
    appointmentId: str | None = None
    urgencyScore: int = 0
    symptoms: list[str] = Field(default_factory=list)
    summary: str = ""
    createdAt: str


class DashboardOverviewResponse(BaseModel):
    kpis: DashboardKpis
    callbackTasks: list[DashboardCallbackTask] = Field(default_factory=list)
    priorityQueue: list[DashboardPriorityItem] = Field(default_factory=list)
    nextAppointments: list[DashboardAppointment] = Field(default_factory=list)
