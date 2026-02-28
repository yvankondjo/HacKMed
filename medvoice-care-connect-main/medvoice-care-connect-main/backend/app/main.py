from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    BookAppointmentRequest,
    ConsultationSummaryRequest,
    EndConsultationRequest,
    StartConsultationRequest,
    StageProgressResponse,
    SuggestQuestionsRequest,
    TranscriptMessageInput,
)
from app.service import service

app = FastAPI(title="MedVoice Care Connect API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/lifecycle/stages", response_model=StageProgressResponse)
async def lifecycle_stages() -> StageProgressResponse:
    return StageProgressResponse(stages=service.list_stages(), eventCount=service.event_count)


@app.post("/api/lifecycle/patient-call")
async def patient_call(payload: dict) -> dict:
    event = service.add_event(
        stage_id="patient-call",
        appointment_id=payload.get("appointmentId"),
        patient_id=payload.get("patientId"),
        payload=payload,
    )
    return {"ok": True, "eventId": event.id}


@app.post("/api/lifecycle/day-before-confirmation")
async def day_before_confirmation(payload: dict) -> dict:
    event = service.add_event(
        stage_id="day-before-confirmation",
        appointment_id=payload.get("appointmentId"),
        patient_id=payload.get("patientId"),
        payload=payload,
    )
    return {"ok": True, "eventId": event.id}


@app.post("/api/lifecycle/consultation/start")
async def consultation_start(request: StartConsultationRequest) -> dict:
    session = service.start_consultation(request.appointmentId, request.patientId)
    event = service.add_event(
        stage_id="consultation-start",
        appointment_id=request.appointmentId,
        patient_id=request.patientId,
        payload=request.model_dump(),
    )
    return {"ok": True, "eventId": event.id, "session": session.model_dump()}


@app.post("/api/lifecycle/consultation/transcript")
async def consultation_transcript(payload: dict) -> dict:
    appointment_id = payload.get("appointmentId")
    messages = [TranscriptMessageInput.model_validate(item) for item in payload.get("messages", [])]
    if appointment_id:
        service.save_transcript(appointment_id=appointment_id, messages=messages)
    event = service.add_event(
        stage_id="consultation-start",
        appointment_id=appointment_id,
        patient_id=payload.get("patientId"),
        payload={"messages": len(messages)},
    )
    return {"ok": True, "eventId": event.id}


@app.get("/api/lifecycle/consultation/{appointment_id}/state")
async def consultation_state(appointment_id: str) -> dict:
    session = service.get_consultation_state(appointment_id)
    return {"state": session.model_dump() if session else None}


@app.post("/api/lifecycle/consultation/end")
async def consultation_end(request: EndConsultationRequest) -> dict:
    session = service.end_consultation(request.appointmentId)
    return {"ok": session is not None, "session": session.model_dump() if session else None}


@app.post("/api/consultation/summary")
async def consultation_summary(request: ConsultationSummaryRequest) -> dict:
    result = service.generate_summary(request)
    return result.model_dump()


@app.post("/api/consultation/suggest-questions")
async def consultation_suggest_questions(request: SuggestQuestionsRequest) -> dict:
    result = service.suggest_questions(request)
    return result.model_dump()


@app.post("/api/booking/calcom")
async def booking_calcom(request: BookAppointmentRequest) -> dict:
    result = await service.book_appointment_and_confirm(request, created_via="api")
    return result.model_dump()
