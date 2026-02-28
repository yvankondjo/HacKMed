from __future__ import annotations

from app.models import LifecycleStage


def default_lifecycle_stages() -> list[LifecycleStage]:
    return [
        LifecycleStage(
            id="patient-call",
            title="Patient appelle",
            description="Capture du besoin, qualification initiale et creation de rendez-vous.",
            status="done",
            impactedTables=[
                {"table": "users", "eventLabel": "lookup/create patient user"},
                {"table": "patients", "eventLabel": "lookup/create patient profile"},
                {"table": "appointments", "eventLabel": "create appointment status=upcoming"},
                {"table": "ai_summaries", "eventLabel": "insert type=phone_briefing"},
                {"table": "call_records", "eventLabel": "insert inbound intake call"},
                {"table": "sms_messages", "eventLabel": "insert type=booking_confirmation"},
            ],
        ),
        LifecycleStage(
            id="day-before-confirmation",
            title="Confirmation J-1",
            description="Relance patient et validation de presence avant consultation.",
            status="done",
            impactedTables=[
                {"table": "sms_messages", "eventLabel": "insert type=reminder"},
                {"table": "call_records", "eventLabel": "optional confirmation call"},
                {"table": "appointments", "eventLabel": "update status=confirmed"},
            ],
        ),
        LifecycleStage(
            id="consultation-start",
            title="Consultation demarre",
            description="Debut session clinique avec transcription live et resume progressif.",
            status="active",
            impactedTables=[
                {"table": "consultations", "eventLabel": "insert state=active, started_at"},
                {"table": "transcript_messages", "eventLabel": "stream doctor/patient/ai utterances"},
                {"table": "ai_summaries", "eventLabel": "insert type=live_summary"},
            ],
        ),
        LifecycleStage(
            id="consultation-end-prescription",
            title="Fin consultation + ordonnance",
            description="Cloture medicale, generation compte-rendu et envoi ordonnance.",
            status="next",
            impactedTables=[
                {"table": "ai_summaries", "eventLabel": "insert type=final_report"},
                {"table": "prescriptions", "eventLabel": "insert/validate prescription"},
                {"table": "prescription_items", "eventLabel": "insert medication lines"},
                {"table": "sms_messages", "eventLabel": "insert type=prescription"},
            ],
        ),
        LifecycleStage(
            id="post-consultation-followup",
            title="Suivi post-consultation",
            description="Automatisation des rappels et monitorage d'evolution.",
            status="next",
            impactedTables=[
                {"table": "followup_tasks", "eventLabel": "insert follow-up workflow tasks"},
                {"table": "sms_messages", "eventLabel": "insert type=followup"},
                {"table": "call_records", "eventLabel": "insert outbound follow-up call"},
            ],
        ),
    ]
