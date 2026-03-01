from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    BookAppointmentRequest,
    CancelAppointmentRequest,
    CancelAppointmentResponse,
    ConsultationRoomTokenResponse,
    ConsultationSummaryRequest,
    DashboardAppointmentDetailResponse,
    DashboardAppointmentsResponse,
    DashboardOverviewResponse,
    DashboardPatientDetailResponse,
    DashboardPatientsResponse,
    EndConsultationRequest,
    FollowupCallCompleteRequest,
    FollowupCallRequest,
    FollowupCallResponse,
    StartConsultationRequest,
    StageProgressResponse,
    SuggestQuestionsRequest,
    TranscriptMessageInput,
    SendPrescriptionRequest,
    SendPrescriptionResponse,
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


@app.get(
    "/api/lifecycle/consultation/{appointment_id}/token",
    response_model=ConsultationRoomTokenResponse,
)
async def consultation_room_token(
    appointment_id: str,
    participant_identity: str = Query(..., alias="participantIdentity"),
    participant_name: str = Query(default="Doctor", alias="participantName"),
) -> ConsultationRoomTokenResponse:
    try:
        return await service.issue_consultation_room_token(
            appointment_id=appointment_id,
            participant_identity=participant_identity,
            participant_name=participant_name,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/lifecycle/consultation/end")
async def consultation_end(request: EndConsultationRequest) -> dict:
    session = service.end_consultation(request.appointmentId)
    return {"ok": session is not None, "session": session.model_dump() if session else None}


@app.post("/api/reminder/followup-call", response_model=FollowupCallResponse)
async def reminder_followup_call(request: FollowupCallRequest) -> FollowupCallResponse:
    try:
        return await service.schedule_followup_call(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/reminder/followup-call/complete")
async def reminder_followup_call_complete(request: FollowupCallCompleteRequest) -> dict:
    return service.complete_followup_call(request)


@app.post("/api/consultation/summary")
async def consultation_summary(request: ConsultationSummaryRequest) -> dict:
    result = service.generate_summary(request)
    return result.model_dump()


@app.post("/api/consultation/suggest-questions")
async def consultation_suggest_questions(request: SuggestQuestionsRequest) -> dict:
    result = service.suggest_questions(request)
    return result.model_dump()


@app.post("/api/prescription/send", response_model=SendPrescriptionResponse)
async def send_prescription(request: SendPrescriptionRequest) -> dict:
    result = service.send_prescription(request)
    return result.model_dump()


@app.post("/api/booking/calcom")
async def booking_calcom(request: BookAppointmentRequest) -> dict:
    try:
        result = await service.book_appointment_and_confirm(request, created_via=request.createdVia)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/booking/calcom/availability")
async def booking_calcom_availability(
    timezone: str | None = Query(default=None),
    days_ahead: int = Query(default=10, alias="daysAhead"),
    limit: int = Query(default=5),
    event_type_id: int | None = Query(default=None, alias="eventTypeId"),
) -> dict:
    try:
        return await service.get_booking_availability(
            timezone_name=timezone,
            days_ahead=days_ahead,
            limit=limit,
            event_type_id=event_type_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/dashboard/appointments", response_model=DashboardAppointmentsResponse)
async def dashboard_appointments(date: str | None = Query(default=None)) -> DashboardAppointmentsResponse:
    return service.list_dashboard_appointments(date_value=date)


@app.get("/api/dashboard/overview", response_model=DashboardOverviewResponse)
async def dashboard_overview(date: str | None = Query(default=None)) -> DashboardOverviewResponse:
    return service.get_dashboard_overview(date_value=date)


@app.get("/api/dashboard/appointments/{appointment_id}", response_model=DashboardAppointmentDetailResponse)
async def dashboard_appointment_detail(appointment_id: str) -> DashboardAppointmentDetailResponse:
    detail = service.get_appointment_detail(appointment_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return detail


@app.post("/api/dashboard/appointments/{appointment_id}/cancel", response_model=CancelAppointmentResponse)
async def dashboard_appointment_cancel(
    appointment_id: str,
    request: CancelAppointmentRequest,
) -> CancelAppointmentResponse:
    try:
        result = service.cancel_appointment(appointment_id, reason=request.reason)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result


@app.get("/api/dashboard/patients", response_model=DashboardPatientsResponse)
async def dashboard_patients() -> DashboardPatientsResponse:
    return service.list_dashboard_patients()


@app.get("/api/dashboard/patients/{patient_id}", response_model=DashboardPatientDetailResponse)
async def dashboard_patient_detail(patient_id: str) -> DashboardPatientDetailResponse:
    detail = service.get_patient_detail(patient_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Patient not found")
    return detail


@app.get("/api/dashboard/agenda", response_model=DashboardAppointmentsResponse)
async def dashboard_agenda(
    date_from: str | None = Query(default=None, alias="dateFrom"),
    date_to: str | None = Query(default=None, alias="dateTo"),
) -> DashboardAppointmentsResponse:
    return service.list_agenda_appointments(date_from=date_from, date_to=date_to)
