from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.config import PersistenceConfig
from app.integrations.calcom_client import BookingResult
from app.integrations.twilio_client import SmsResult
from app.models import BookAppointmentRequest

logger = logging.getLogger("medvoice.persistence")


@dataclass(frozen=True)
class PersistedBookingResult:
    saved: bool
    appointment_id: str
    consultation_id: str | None
    call_record_id: str | None


@dataclass(frozen=True)
class CancelledAppointmentResult:
    appointment_id: str
    status: str
    callback_scheduled: bool
    callback_task_id: str | None
    callback_scheduled_at: datetime | None
    patient_id: str | None
    patient_phone: str | None


def _parse_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in full_name.strip().split(" ") if p]
    if not parts:
        return ("Unknown", "Patient")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def _normalize_labels(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    labels: list[str] = []
    for value in values:
        label = value.strip()
        if not label:
            continue
        low = label.lower()
        if low in seen:
            continue
        seen.add(low)
        labels.append(label)
    return labels


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _map_appointment_status(raw_status: str | None) -> str:
    status = (raw_status or "").strip().lower()
    if status == "in_progress":
        return "in-progress"
    if status in {"done", "cancelled", "no_show"}:
        return "done"
    return "upcoming"


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return []
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            return [trimmed]
    return []


def _duration_text(seconds: Any) -> str:
    try:
        total = int(seconds)
    except Exception:
        return "0 min"
    minutes = max(1, round(total / 60))
    return f"{minutes} min"


class PostgresPersistenceClient:
    def __init__(self, config: PersistenceConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return bool(self._config.database_url)

    def persist_booking_bundle(
        self,
        *,
        request: BookAppointmentRequest,
        booking: BookingResult,
        sms: SmsResult,
        created_via: str,
    ) -> PersistedBookingResult:
        if not self.enabled:
            fallback_id = f"apt-{booking.booking_id or uuid4().hex[:8]}"
            return PersistedBookingResult(
                saved=False,
                appointment_id=fallback_id,
                consultation_id=None,
                call_record_id=None,
            )

        try:
            import psycopg  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required when DATABASE_URL is configured") from exc

        first_name, last_name = _parse_name(request.patientName)
        starts_at = _parse_iso_ts(booking.start_at) or _parse_iso_ts(request.startsAt)
        if not starts_at:
            starts_at = datetime.now(timezone.utc)
        ends_at = _parse_iso_ts(booking.end_at)

        call_started_at = _parse_iso_ts(request.callStartedAt) or starts_at
        call_ended_at = _parse_iso_ts(request.callEndedAt) or datetime.now(timezone.utc)
        duration_seconds = max(int((call_ended_at - call_started_at).total_seconds()), 0)

        appointment_id = str(uuid4())
        consultation_id = str(uuid4())
        call_record_id = str(uuid4())
        red_flags = [sym for sym in request.symptoms if "red flag" in sym.lower()]
        urgency = 8 if red_flags else 3

        transcript = request.transcript or []
        summary = (request.conversationSummary or "").strip()
        if not summary and transcript:
            summary = " ".join(msg.text.strip() for msg in transcript if msg.text.strip())[:1200]

        conditions = _normalize_labels(request.conditions)
        allergies = _normalize_labels(request.allergies)

        with psycopg.connect(self._config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO patients (phone, first_name, last_name, email, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (phone) DO UPDATE
                    SET first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        email = EXCLUDED.email,
                        updated_at = now()
                    """,
                    (request.patientPhone, first_name, last_name, request.patientEmail),
                )

                for condition in conditions:
                    cur.execute(
                        """
                        INSERT INTO patient_conditions (patient_id, label, status, notes)
                        VALUES (%s, %s, 'active', 'captured during intake call')
                        """,
                        (request.patientPhone, condition),
                    )

                for allergy in allergies:
                    cur.execute(
                        """
                        INSERT INTO patient_allergies (patient_id, substance, severity)
                        VALUES (%s, %s, 'unknown')
                        """,
                        (request.patientPhone, allergy),
                    )

                cur.execute(
                    """
                    INSERT INTO appointments (
                        id, patient_id, doctor_id, starts_at, ends_at, reason, status, location, notes, created_at, updated_at
                    ) VALUES (
                        %s::uuid, %s, %s::uuid, %s, %s, %s, 'confirmed', %s, %s, now(), now()
                    )
                    """,
                    (
                        appointment_id,
                        request.patientPhone,
                        self._config.default_doctor_id,
                        starts_at,
                        ends_at,
                        request.reason,
                        "cal.com",
                        f"Cal.com booking_id={booking.booking_id}; created_via={created_via}",
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO consultations (
                        id, appointment_id, started_at, ended_at, state, urgency_score, detected_symptoms, safety_alerts, created_at, updated_at
                    ) VALUES (
                        %s::uuid, %s::uuid, %s, %s, 'ended', %s, %s::jsonb, %s::jsonb, now(), now()
                    )
                    """,
                    (
                        consultation_id,
                        appointment_id,
                        call_started_at,
                        call_ended_at,
                        urgency,
                        json.dumps(request.symptoms),
                        json.dumps(red_flags),
                    ),
                )

                for msg in transcript:
                    sender = msg.speaker.strip().lower()
                    sender_type = "ai" if sender == "ai" else ("doctor" if sender == "doctor" else "patient")
                    sent_at = _parse_iso_ts(msg.timestamp) or datetime.now(timezone.utc)
                    cur.execute(
                        """
                        INSERT INTO transcript_messages (consultation_id, sender_type, content, sent_at, meta)
                        VALUES (%s::uuid, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            consultation_id,
                            sender_type,
                            msg.text,
                            sent_at,
                            json.dumps({"source": "booking_confirmation"}),
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO call_records (
                        id, patient_id, doctor_id, appointment_id, started_at, ended_at, duration_seconds,
                        reason, symptoms, summary, recommendations, evolution, urgency_score, recording_url, created_at
                    ) VALUES (
                        %s::uuid, %s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s,
                        %s::jsonb, 'unknown', %s, %s, now()
                    )
                    """,
                    (
                        call_record_id,
                        request.patientPhone,
                        self._config.default_doctor_id,
                        appointment_id,
                        call_started_at,
                        call_ended_at,
                        duration_seconds,
                        request.reason,
                        json.dumps(request.symptoms),
                        summary or None,
                        json.dumps([]),
                        urgency,
                        request.recordingUrl,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO sms_messages (patient_id, appointment_id, message_type, body, status, sent_at)
                    VALUES (%s, %s::uuid, 'booking_confirmation', %s, %s, now())
                    """,
                    (
                        request.patientPhone,
                        appointment_id,
                        sms.raw.get("body_preview") or "Booking confirmation sent",
                        sms.status if sms.status in {"sent", "delivered", "no_response", "failed"} else "sent",
                    ),
                )

                if summary:
                    cur.execute(
                        """
                        INSERT INTO ai_summaries (
                            appointment_id, consultation_id, type, summary_text, symptoms, urgency_score, model_info, created_at
                        ) VALUES (
                            %s::uuid, %s::uuid, 'phone_briefing', %s, %s::jsonb, %s, %s::jsonb, now()
                        )
                        """,
                        (
                            appointment_id,
                            consultation_id,
                            summary,
                            json.dumps(request.symptoms),
                            urgency,
                            json.dumps({"source": "telephony_agent"}),
                        ),
                    )

            conn.commit()

        logger.info(
            "Persisted booking bundle to DB appointment_id=%s consultation_id=%s call_record_id=%s",
            appointment_id,
            consultation_id,
            call_record_id,
        )
        return PersistedBookingResult(
            saved=True,
            appointment_id=appointment_id,
            consultation_id=consultation_id,
            call_record_id=call_record_id,
        )

    def _connect(self):
        if not self.enabled:
            raise RuntimeError("DATABASE_URL is not configured")
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required when DATABASE_URL is configured") from exc
        return psycopg.connect(self._config.database_url, row_factory=dict_row)

    def persist_consultation_report(
        self,
        *,
        appointment_id: str,
        patient_id: str,
        transcript: list[dict[str, Any]],
        summary_text: str,
        symptoms: list[str],
        diagnoses: list[str],
        prescription: dict[str, Any],
    ) -> bool:
        if not self.enabled:
            return False

        now = datetime.now(timezone.utc)
        medications = prescription.get("medications", []) if isinstance(prescription, dict) else []
        additional_advice = (
            prescription.get("additionalAdvice", []) if isinstance(prescription, dict) else []
        )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        a.id::text AS appointment_id,
                        a.patient_id AS patient_id,
                        a.doctor_id::text AS doctor_id
                    FROM appointments a
                    WHERE a.id::text = %s
                    LIMIT 1
                    """,
                    (appointment_id,),
                )
                appointment_row = cur.fetchone()
                if not appointment_row:
                    return False

                effective_patient_id = str(
                    appointment_row.get("patient_id") or patient_id
                )
                doctor_id = appointment_row.get("doctor_id")

                cur.execute(
                    """
                    SELECT id::text AS id
                    FROM consultations
                    WHERE appointment_id::text = %s
                    LIMIT 1
                    """,
                    (appointment_id,),
                )
                consultation_row = cur.fetchone()
                if consultation_row:
                    consultation_id = str(consultation_row.get("id"))
                    cur.execute(
                        """
                        UPDATE consultations
                        SET ended_at = %s,
                            state = 'ended',
                            urgency_score = %s,
                            detected_symptoms = %s::jsonb,
                            safety_alerts = %s::jsonb,
                            updated_at = now()
                        WHERE id::uuid = %s::uuid
                        """,
                        (
                            now,
                            8 if any("chest" in s.lower() or "breath" in s.lower() for s in symptoms) else 4,
                            json.dumps(symptoms),
                            json.dumps([]),
                            consultation_id,
                        ),
                    )
                else:
                    consultation_id = str(uuid4())
                    cur.execute(
                        """
                        INSERT INTO consultations (
                            id, appointment_id, started_at, ended_at, state, urgency_score,
                            detected_symptoms, safety_alerts, created_at, updated_at
                        ) VALUES (
                            %s::uuid, %s::uuid, %s, %s, 'ended', %s, %s::jsonb, %s::jsonb, now(), now()
                        )
                        """,
                        (
                            consultation_id,
                            appointment_id,
                            now,
                            now,
                            8 if any("chest" in s.lower() or "breath" in s.lower() for s in symptoms) else 4,
                            json.dumps(symptoms),
                            json.dumps([]),
                        ),
                    )

                cur.execute(
                    """
                    DELETE FROM transcript_messages
                    WHERE consultation_id = %s::uuid
                      AND COALESCE(meta->>'source', '') = 'consultation_summary_api'
                    """,
                    (consultation_id,),
                )

                for message in transcript:
                    speaker = str(message.get("speaker") or "Patient").strip().lower()
                    sender_type = "ai" if speaker == "ai" else ("doctor" if speaker == "doctor" else "patient")
                    sent_at = _parse_iso_ts(str(message.get("timestamp") or "")) or now
                    cur.execute(
                        """
                        INSERT INTO transcript_messages (consultation_id, sender_type, content, sent_at, meta)
                        VALUES (%s::uuid, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            consultation_id,
                            sender_type,
                            str(message.get("text") or ""),
                            sent_at,
                            json.dumps({"source": "consultation_summary_api"}),
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO ai_summaries (
                        appointment_id, consultation_id, type, summary_text, probable_diagnosis,
                        recommendations, symptoms, urgency_score, model_info, created_at
                    ) VALUES (
                        %s::uuid, %s::uuid, 'live_summary', %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, now()
                    )
                    """,
                    (
                        appointment_id,
                        consultation_id,
                        summary_text,
                        " | ".join(diagnoses[:3]) if diagnoses else None,
                        json.dumps(additional_advice),
                        json.dumps(symptoms),
                        8 if any("chest" in s.lower() or "breath" in s.lower() for s in symptoms) else 4,
                        json.dumps({"source": "consultation_summary_api"}),
                    ),
                )

                should_create_prescription = bool(medications) or bool(additional_advice)
                if should_create_prescription:
                    cur.execute(
                        """
                        DELETE FROM prescription_items
                        WHERE prescription_id IN (
                            SELECT id FROM prescriptions WHERE appointment_id = %s::uuid AND status = 'draft'
                        )
                        """,
                        (appointment_id,),
                    )
                    cur.execute(
                        """
                        DELETE FROM prescriptions
                        WHERE appointment_id = %s::uuid AND status = 'draft'
                        """,
                        (appointment_id,),
                    )

                    prescription_id = str(uuid4())
                    notes = (
                        "AI generated draft from consultation summary."
                        + (f" Diagnoses: {'; '.join(diagnoses[:3])}" if diagnoses else "")
                    )
                    cur.execute(
                        """
                        INSERT INTO prescriptions (
                            id, appointment_id, patient_id, doctor_id, status, issued_at, notes, created_at, updated_at
                        ) VALUES (
                            %s::uuid, %s::uuid, %s, %s::uuid, 'draft', %s, %s, now(), now()
                        )
                        """,
                        (
                            prescription_id,
                            appointment_id,
                            effective_patient_id,
                            doctor_id,
                            now,
                            notes,
                        ),
                    )

                    for medication in medications:
                        name = str(medication.get("name") or "").strip()
                        if not name:
                            continue
                        cur.execute(
                            """
                            INSERT INTO prescription_items (
                                prescription_id, medication_name, dosage, frequency, duration, instructions, is_ai_suggested, created_at
                            ) VALUES (
                                %s::uuid, %s, %s, %s, %s, %s, true, now()
                            )
                            """,
                            (
                                prescription_id,
                                name,
                                str(medication.get("dosage") or ""),
                                str(medication.get("frequency") or ""),
                                str(medication.get("duration") or ""),
                                "; ".join(str(item) for item in additional_advice if str(item).strip()) or None,
                            ),
                        )

            conn.commit()
        return True

    def get_latest_prescription(
        self,
        *,
        patient_id: str,
        appointment_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"medications": [], "additionalAdvice": []}

        patient_ref = str(patient_id or "").strip()
        if not patient_ref:
            return {"medications": [], "additionalAdvice": []}

        query = """
            SELECT
                p.id::text AS id,
                p.appointment_id::text AS appointment_id,
                p.status AS status,
                p.issued_at AS issued_at,
                p.notes AS notes
            FROM prescriptions p
            WHERE (p.patient_id = %s OR p.patient_id = %s)
        """
        params: list[Any] = [patient_ref, patient_ref]
        if appointment_id:
            query += " OR p.appointment_id::text = %s"
            params.append(appointment_id)
        query += " ORDER BY COALESCE(p.issued_at, p.created_at) DESC LIMIT 1"

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                row = cur.fetchone()
                if not row:
                    return {"medications": [], "additionalAdvice": []}

                prescription_id = str(row.get("id") or "")
                cur.execute(
                    """
                    SELECT
                        medication_name,
                        dosage,
                        frequency,
                        duration,
                        instructions
                    FROM prescription_items
                    WHERE prescription_id = %s::uuid
                    ORDER BY created_at ASC
                    """,
                    (prescription_id,),
                )
                item_rows = cur.fetchall()

        medications: list[dict[str, str]] = []
        for item in item_rows:
            name = str(item.get("medication_name") or "").strip()
            if not name:
                continue
            medications.append(
                {
                    "name": name,
                    "dosage": str(item.get("dosage") or ""),
                    "frequency": str(item.get("frequency") or ""),
                    "duration": str(item.get("duration") or ""),
                }
            )

        additional_advice = _as_str_list(row.get("notes"))
        if not additional_advice and item_rows:
            additional_advice = _as_str_list(item_rows[0].get("instructions"))

        return {
            "id": prescription_id,
            "appointmentId": row.get("appointment_id"),
            "status": str(row.get("status") or "draft"),
            "issuedAt": (
                row.get("issued_at").isoformat() if isinstance(row.get("issued_at"), datetime) else None
            ),
            "medications": medications,
            "additionalAdvice": additional_advice,
        }

    def queue_followup_task(
        self,
        *,
        patient_id: str,
        notes: str,
    ) -> str | None:
        if not self.enabled:
            return None

        patient_ref = str(patient_id or "").strip()
        if not patient_ref:
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO followup_tasks (
                        patient_id,
                        scheduled_at,
                        followup_type,
                        status,
                        attempt_number,
                        notes
                    ) VALUES (
                        %s,
                        now(),
                        'call',
                        'pending',
                        1,
                        %s
                    )
                    RETURNING id::text AS id
                    """,
                    (patient_ref, notes[:1200]),
                )
                row = cur.fetchone() or {}
            conn.commit()
        return str(row.get("id") or "") or None

    def persist_outbound_followup_result(
        self,
        *,
        followup_call_id: str,
        appointment_id: str | None,
        patient_id: str,
        patient_phone: str | None,
        status: str,
        duration_seconds: int,
        summary: str,
        symptoms: list[str],
        recommendations: list[str],
        evolution: str,
        followup_task_id: str | None = None,
        profile_conditions: list[str] | None = None,
        profile_allergies: list[str] | None = None,
        profile_note: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return None

        appointment_ref = (appointment_id or "").strip() or None
        patient_ref = str(patient_phone or patient_id or "").strip()
        if not patient_ref:
            return None

        clean_duration = max(int(duration_seconds or 0), 0)
        now = datetime.now(timezone.utc)
        started_at = now - timedelta(seconds=clean_duration) if clean_duration > 0 else now
        summary_text = (
            str(summary or "").strip()
            or f"Outbound follow-up call completed with status={status}."
        )
        profile_note_text = (str(profile_note or "").strip() or summary_text)[:1600]
        normalized_evolution = (
            evolution
            if evolution in {"improvement", "worsening", "stable", "unknown"}
            else "unknown"
        )
        normalized_conditions = _normalize_labels(profile_conditions or symptoms)
        normalized_allergies = _normalize_labels(profile_allergies)
        computed_urgency = 4
        lowered_blob = " ".join(symptoms).lower()
        if "chest" in lowered_blob or "breath" in lowered_blob:
            computed_urgency = 8
        elif status in {"failed", "no-answer", "voicemail"}:
            computed_urgency = 5

        call_record_id = str(uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                doctor_id = None
                if appointment_ref:
                    cur.execute(
                        """
                        SELECT patient_id, doctor_id::text AS doctor_id
                        FROM appointments
                        WHERE id::text = %s
                        LIMIT 1
                        """,
                        (appointment_ref,),
                    )
                    appointment_row = cur.fetchone() or {}
                    if appointment_row.get("patient_id"):
                        patient_ref = str(appointment_row.get("patient_id"))
                    doctor_id = appointment_row.get("doctor_id")

                cur.execute(
                    "SELECT 1 FROM patients WHERE phone = %s LIMIT 1",
                    (patient_ref,),
                )
                patient_exists = bool(cur.fetchone())

                if patient_exists:
                    for condition in normalized_conditions:
                        cur.execute(
                            """
                            UPDATE patient_conditions
                            SET status = 'active',
                                notes = CASE
                                    WHEN COALESCE(notes, '') = '' THEN %s
                                    ELSE LEFT(notes || E'\n' || %s, 4000)
                                END
                            WHERE patient_id = %s
                              AND lower(label) = lower(%s)
                            """,
                            (
                                profile_note_text,
                                profile_note_text,
                                patient_ref,
                                condition,
                            ),
                        )
                        if cur.rowcount == 0:
                            cur.execute(
                                """
                                INSERT INTO patient_conditions (patient_id, label, status, notes, start_date)
                                VALUES (%s, %s, 'active', %s, current_date)
                                """,
                                (
                                    patient_ref,
                                    condition,
                                    profile_note_text,
                                ),
                            )

                    for allergy in normalized_allergies:
                        cur.execute(
                            """
                            INSERT INTO patient_allergies (patient_id, substance, reaction, severity, noted_at)
                            SELECT %s, %s, %s, 'unknown', current_date
                            WHERE NOT EXISTS (
                                SELECT 1
                                FROM patient_allergies
                                WHERE patient_id = %s
                                  AND lower(substance) = lower(%s)
                            )
                            """,
                            (
                                patient_ref,
                                allergy,
                                profile_note_text[:250],
                                patient_ref,
                                allergy,
                            ),
                        )

                if appointment_ref:
                    cur.execute(
                        """
                        INSERT INTO call_records (
                            id, patient_id, doctor_id, appointment_id, started_at, ended_at, duration_seconds,
                            reason, symptoms, summary, recommendations, evolution, urgency_score, recording_url, created_at
                        ) VALUES (
                            %s::uuid, %s, %s::uuid, %s::uuid, %s, %s, %s,
                            %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, now()
                        )
                        """,
                        (
                            call_record_id,
                            patient_ref,
                            doctor_id,
                            appointment_ref,
                            started_at,
                            now,
                            clean_duration,
                            "Post-consultation follow-up call",
                            json.dumps(symptoms),
                            summary_text[:4000],
                            json.dumps(recommendations),
                            normalized_evolution,
                            computed_urgency,
                            None,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO call_records (
                            id, patient_id, doctor_id, appointment_id, started_at, ended_at, duration_seconds,
                            reason, symptoms, summary, recommendations, evolution, urgency_score, recording_url, created_at
                        ) VALUES (
                            %s::uuid, %s, NULL, NULL, %s, %s, %s,
                            %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, now()
                        )
                        """,
                        (
                            call_record_id,
                            patient_ref,
                            started_at,
                            now,
                            clean_duration,
                            "Post-consultation follow-up call",
                            json.dumps(symptoms),
                            summary_text[:4000],
                            json.dumps(recommendations),
                            normalized_evolution,
                            computed_urgency,
                            None,
                        ),
                    )

                task_status = "completed" if status == "completed" else "failed"
                task_note = (
                    f"followup_call_id={followup_call_id}; status={status}; "
                    f"duration_seconds={clean_duration}; call_record_id={call_record_id}"
                )
                if followup_task_id:
                    cur.execute(
                        """
                        UPDATE followup_tasks
                        SET status = %s,
                            notes = COALESCE(notes, '') || %s
                        WHERE id::text = %s
                        """,
                        (
                            task_status,
                            f"\n{task_note}",
                            followup_task_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE followup_tasks
                        SET status = %s,
                            notes = COALESCE(notes, '') || %s
                        WHERE id = (
                            SELECT id
                            FROM followup_tasks
                            WHERE (patient_id = %s OR patient_id = %s)
                              AND followup_type = 'call'
                              AND status = 'pending'
                            ORDER BY scheduled_at DESC
                            LIMIT 1
                        )
                        """,
                        (
                            task_status,
                            f"\n{task_note}",
                            patient_ref,
                            patient_id,
                        ),
                    )

                if appointment_ref:
                    cur.execute(
                        """
                        INSERT INTO sms_messages (patient_id, appointment_id, message_type, body, status, sent_at)
                        VALUES (%s, %s::uuid, 'followup', %s, 'sent', now())
                        """,
                        (
                            patient_ref,
                            appointment_ref,
                            f"Follow-up call status: {status}.",
                        ),
                    )

            conn.commit()
        return call_record_id

    def list_dashboard_appointments(
        self,
        *,
        date_value: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        query = """
            SELECT
                a.id::text AS id,
                a.patient_id AS patient_id,
                a.starts_at AS starts_at,
                a.ends_at AS ends_at,
                COALESCE(a.reason, 'General consultation') AS motif,
                COALESCE(a.status, 'upcoming') AS raw_status,
                a.notes AS notes,
                COALESCE(
                    NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                    a.patient_id,
                    'Unknown Patient'
                ) AS patient_name,
                COALESCE(p.phone, a.patient_id, '') AS patient_phone,
                COALESCE(
                    NULLIF(TRIM('Dr. ' || COALESCE(d.first_name, '') || ' ' || COALESCE(d.last_name, '')), 'Dr.'),
                    'Dr. Unassigned'
                ) AS doctor_name,
                COALESCE(d.specialty, 'General Practitioner') AS doctor_specialty,
                ai.summary_text AS ai_summary
            FROM appointments a
            LEFT JOIN patients p
                ON p.phone = a.patient_id OR p.id::text = a.patient_id
            LEFT JOIN doctors d
                ON d.id = a.doctor_id
            LEFT JOIN LATERAL (
                SELECT summary_text
                FROM ai_summaries s
                WHERE s.appointment_id = a.id
                ORDER BY s.created_at DESC
                LIMIT 1
            ) ai ON true
            WHERE (%s::date IS NULL OR a.starts_at::date = %s::date)
              AND (%s::date IS NULL OR a.starts_at::date >= %s::date)
              AND (%s::date IS NULL OR a.starts_at::date <= %s::date)
            ORDER BY a.starts_at ASC
            LIMIT %s
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        date_value,
                        date_value,
                        date_from,
                        date_from,
                        date_to,
                        date_to,
                        limit,
                    ),
                )
                rows = cur.fetchall()

        normalized: list[dict[str, Any]] = []
        for row in rows:
            starts_at = row.get("starts_at")
            ends_at = row.get("ends_at")
            if not isinstance(starts_at, datetime):
                continue
            patient_phone = str(row.get("patient_phone") or row.get("patient_id") or "")
            normalized.append(
                {
                    "id": str(row.get("id")),
                    "patientId": patient_phone,
                    "patientName": str(row.get("patient_name") or "Unknown Patient"),
                    "patientPhone": patient_phone,
                    "date": starts_at.date().isoformat(),
                    "time": starts_at.strftime("%H:%M"),
                    "startsAt": starts_at.isoformat(),
                    "endsAt": ends_at.isoformat() if isinstance(ends_at, datetime) else None,
                    "doctor": str(row.get("doctor_name") or "Dr. Unassigned"),
                    "doctorSpecialty": str(row.get("doctor_specialty") or "General Practitioner"),
                    "motif": str(row.get("motif") or "General consultation"),
                    "status": _map_appointment_status(row.get("raw_status")),
                    "rawStatus": str(row.get("raw_status") or "upcoming"),
                    "notes": row.get("notes"),
                    "aiSummary": row.get("ai_summary"),
                }
            )
        return normalized

    def list_dashboard_patients(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        query = """
            SELECT
                COALESCE(p.phone, p.id::text) AS id,
                COALESCE(p.first_name, 'Unknown') AS first_name,
                COALESCE(p.last_name, 'Patient') AS last_name,
                p.date_of_birth AS date_of_birth,
                COALESCE(p.phone, p.id::text, '') AS phone,
                COALESCE(NULLIF(p.email, ''), 'no-email@medvoice.local') AS email,
                p.blood_type AS blood_type,
                allergies.items AS allergies,
                conditions.items AS antecedents,
                recent.starts_at AS last_starts_at,
                recent.reason AS last_reason,
                COALESCE(upcoming.count_upcoming, 0) AS upcoming_count
            FROM patients p
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT pa.substance ORDER BY pa.substance) AS items
                FROM patient_allergies pa
                WHERE pa.patient_id = p.phone OR pa.patient_id = p.id::text
            ) allergies ON true
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT pc.label ORDER BY pc.label) AS items
                FROM patient_conditions pc
                WHERE pc.patient_id = p.phone OR pc.patient_id = p.id::text
            ) conditions ON true
            LEFT JOIN LATERAL (
                SELECT a.starts_at, a.reason
                FROM appointments a
                WHERE a.patient_id = p.phone OR a.patient_id = p.id::text
                ORDER BY a.starts_at DESC
                LIMIT 1
            ) recent ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::int AS count_upcoming
                FROM appointments a
                WHERE (a.patient_id = p.phone OR a.patient_id = p.id::text)
                  AND a.starts_at >= now()
                  AND a.status IN ('upcoming', 'confirmed', 'in_progress')
            ) upcoming ON true
            ORDER BY p.updated_at DESC NULLS LAST, p.created_at DESC NULLS LAST
            LIMIT %s
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                rows = cur.fetchall()

        normalized: list[dict[str, Any]] = []
        for row in rows:
            dob = row.get("date_of_birth")
            last_starts_at = row.get("last_starts_at")
            normalized.append(
                {
                    "id": str(row.get("id")),
                    "firstName": str(row.get("first_name") or "Unknown"),
                    "lastName": str(row.get("last_name") or "Patient"),
                    "dateOfBirth": dob.isoformat() if isinstance(dob, date) else None,
                    "phone": str(row.get("phone") or ""),
                    "email": str(row.get("email") or "no-email@medvoice.local"),
                    "bloodType": row.get("blood_type"),
                    "allergies": _as_str_list(row.get("allergies")),
                    "antecedents": _as_str_list(row.get("antecedents")),
                    "lastAppointmentDate": (
                        last_starts_at.date().isoformat() if isinstance(last_starts_at, datetime) else None
                    ),
                    "lastAppointmentMotif": (
                        str(row.get("last_reason"))
                        if row.get("last_reason")
                        else None
                    ),
                    "upcomingAppointmentsCount": int(row.get("upcoming_count") or 0),
                }
            )
        return normalized

    def list_agenda_appointments(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        appointments = self.list_dashboard_appointments(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return [item for item in appointments if item["status"] != "done"]

    def get_appointment_detail(self, appointment_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        query = """
            SELECT
                a.id::text AS id,
                a.patient_id AS patient_id,
                a.starts_at AS starts_at,
                a.ends_at AS ends_at,
                COALESCE(a.reason, 'General consultation') AS motif,
                COALESCE(a.status, 'upcoming') AS raw_status,
                a.notes AS notes,
                COALESCE(
                    NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                    a.patient_id,
                    'Unknown Patient'
                ) AS patient_name,
                COALESCE(p.phone, a.patient_id, '') AS patient_phone,
                COALESCE(
                    NULLIF(TRIM('Dr. ' || COALESCE(d.first_name, '') || ' ' || COALESCE(d.last_name, '')), 'Dr.'),
                    'Dr. Unassigned'
                ) AS doctor_name,
                COALESCE(d.specialty, 'General Practitioner') AS doctor_specialty,
                ai.summary_text AS ai_summary,
                p.first_name AS patient_first_name,
                p.last_name AS patient_last_name,
                p.date_of_birth AS patient_dob,
                p.email AS patient_email,
                p.blood_type AS patient_blood_type
            FROM appointments a
            LEFT JOIN patients p
                ON p.phone = a.patient_id OR p.id::text = a.patient_id
            LEFT JOIN doctors d
                ON d.id = a.doctor_id
            LEFT JOIN LATERAL (
                SELECT summary_text
                FROM ai_summaries s
                WHERE s.appointment_id = a.id
                ORDER BY s.created_at DESC
                LIMIT 1
            ) ai ON true
            WHERE a.id::text = %s
            LIMIT 1
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (appointment_id,))
                row = cur.fetchone()
                if not row:
                    return None

                starts_at = row.get("starts_at")
                ends_at = row.get("ends_at")
                if not isinstance(starts_at, datetime):
                    return None

                patient_phone = str(row.get("patient_phone") or row.get("patient_id") or "")
                dob = row.get("patient_dob")

                cur.execute(
                    """
                    SELECT array_agg(DISTINCT pa.substance ORDER BY pa.substance) AS items
                    FROM patient_allergies pa
                    WHERE pa.patient_id = %s OR pa.patient_id = %s
                    """,
                    (patient_phone, row.get("patient_id")),
                )
                allergies_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT array_agg(DISTINCT pc.label ORDER BY pc.label) AS items
                    FROM patient_conditions pc
                    WHERE pc.patient_id = %s OR pc.patient_id = %s
                    """,
                    (patient_phone, row.get("patient_id")),
                )
                conditions_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                        a.starts_at,
                        COALESCE(a.reason, 'Consultation') AS motif,
                        COALESCE(
                            NULLIF(TRIM('Dr. ' || COALESCE(d.first_name, '') || ' ' || COALESCE(d.last_name, '')), 'Dr.'),
                            'Dr. Unassigned'
                        ) AS doctor
                    FROM appointments a
                    LEFT JOIN doctors d ON d.id = a.doctor_id
                    WHERE (a.patient_id = %s OR a.patient_id = %s)
                      AND a.id::text <> %s
                    ORDER BY a.starts_at DESC
                    LIMIT 8
                    """,
                    (patient_phone, row.get("patient_id"), appointment_id),
                )
                history_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        id::text AS id,
                        patient_id,
                        appointment_id::text AS appointment_id,
                        COALESCE(started_at, created_at) AS started_at,
                        duration_seconds,
                        COALESCE(reason, 'Phone call') AS motif,
                        symptoms,
                        summary,
                        recommendations,
                        COALESCE(evolution, 'stable') AS evolution,
                        COALESCE(urgency_score, 0) AS urgency_score
                    FROM call_records
                    WHERE appointment_id::text = %s
                       OR patient_id = %s
                    ORDER BY COALESCE(started_at, created_at) DESC
                    LIMIT 12
                    """,
                    (appointment_id, patient_phone),
                )
                call_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT COUNT(*)::int AS count_upcoming
                    FROM appointments a
                    WHERE (a.patient_id = %s OR a.patient_id = %s)
                      AND a.starts_at >= now()
                      AND a.status IN ('upcoming', 'confirmed', 'in_progress')
                    """,
                    (patient_phone, row.get("patient_id")),
                )
                upcoming_count_row = cur.fetchone() or {}

        appointment_payload = {
            "id": str(row.get("id")),
            "patientId": patient_phone,
            "patientName": str(row.get("patient_name") or "Unknown Patient"),
            "patientPhone": patient_phone,
            "date": starts_at.date().isoformat(),
            "time": starts_at.strftime("%H:%M"),
            "startsAt": starts_at.isoformat(),
            "endsAt": ends_at.isoformat() if isinstance(ends_at, datetime) else None,
            "doctor": str(row.get("doctor_name") or "Dr. Unassigned"),
            "doctorSpecialty": str(row.get("doctor_specialty") or "General Practitioner"),
            "motif": str(row.get("motif") or "General consultation"),
            "status": _map_appointment_status(row.get("raw_status")),
            "rawStatus": str(row.get("raw_status") or "upcoming"),
            "notes": row.get("notes"),
            "aiSummary": row.get("ai_summary"),
        }

        history_payload: list[dict[str, Any]] = []
        for item in history_rows:
            started = item.get("starts_at")
            if not isinstance(started, datetime):
                continue
            history_payload.append(
                {
                    "date": started.date().isoformat(),
                    "motif": str(item.get("motif") or "Consultation"),
                    "doctor": str(item.get("doctor") or "Dr. Unassigned"),
                    "summary": "Consultation history record.",
                }
            )

        calls_payload: list[dict[str, Any]] = []
        for call in call_rows:
            started = call.get("started_at")
            call_date = (
                started.date().isoformat()
                if isinstance(started, datetime)
                else datetime.now(timezone.utc).date().isoformat()
            )
            calls_payload.append(
                {
                    "id": str(call.get("id") or ""),
                    "patientId": str(call.get("patient_id") or patient_phone),
                    "appointmentId": call.get("appointment_id"),
                    "date": call_date,
                    "duration": _duration_text(call.get("duration_seconds")),
                    "motif": str(call.get("motif") or "Phone call"),
                    "symptoms": _as_str_list(call.get("symptoms")),
                    "summary": str(call.get("summary") or ""),
                    "recommendations": _as_str_list(call.get("recommendations")),
                    "evolution": str(call.get("evolution") or "stable"),
                    "urgencyScore": int(call.get("urgency_score") or 0),
                }
            )

        patient_payload = {
            "id": patient_phone,
            "firstName": str(row.get("patient_first_name") or appointment_payload["patientName"].split(" ")[0]),
            "lastName": str(row.get("patient_last_name") or " ".join(appointment_payload["patientName"].split(" ")[1:])),
            "dateOfBirth": dob.isoformat() if isinstance(dob, date) else None,
            "phone": patient_phone,
            "email": str(row.get("patient_email") or "no-email@medvoice.local"),
            "bloodType": row.get("patient_blood_type"),
            "allergies": _as_str_list(allergies_row.get("items")),
            "antecedents": _as_str_list(conditions_row.get("items")),
            "lastAppointmentDate": history_payload[0]["date"] if history_payload else appointment_payload["date"],
            "lastAppointmentMotif": history_payload[0]["motif"] if history_payload else appointment_payload["motif"],
            "upcomingAppointmentsCount": int(upcoming_count_row.get("count_upcoming") or 0),
        }

        return {
            "appointment": appointment_payload,
            "patient": patient_payload,
            "history": history_payload,
            "calls": calls_payload,
        }

    def get_patient_detail(self, patient_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(p.phone, p.id::text) AS id,
                        COALESCE(p.first_name, 'Unknown') AS first_name,
                        COALESCE(p.last_name, 'Patient') AS last_name,
                        p.date_of_birth AS date_of_birth,
                        COALESCE(p.phone, p.id::text, '') AS phone,
                        COALESCE(NULLIF(p.email, ''), 'no-email@medvoice.local') AS email,
                        p.blood_type AS blood_type,
                        allergies.items AS allergies,
                        conditions.items AS antecedents
                    FROM patients p
                    LEFT JOIN LATERAL (
                        SELECT array_agg(DISTINCT pa.substance ORDER BY pa.substance) AS items
                        FROM patient_allergies pa
                        WHERE pa.patient_id = p.phone OR pa.patient_id = p.id::text
                    ) allergies ON true
                    LEFT JOIN LATERAL (
                        SELECT array_agg(DISTINCT pc.label ORDER BY pc.label) AS items
                        FROM patient_conditions pc
                        WHERE pc.patient_id = p.phone OR pc.patient_id = p.id::text
                    ) conditions ON true
                    WHERE p.phone = %s OR p.id::text = %s
                    LIMIT 1
                    """,
                    (patient_id, patient_id),
                )
                patient_row = cur.fetchone()
                if not patient_row:
                    return None

                effective_patient_phone = str(patient_row.get("phone") or "")
                effective_patient_id = str(patient_row.get("id") or patient_id)

                cur.execute(
                    """
                    SELECT
                        a.id::text AS id,
                        a.patient_id AS patient_id,
                        a.starts_at AS starts_at,
                        a.ends_at AS ends_at,
                        COALESCE(a.reason, 'General consultation') AS motif,
                        COALESCE(a.status, 'upcoming') AS raw_status,
                        a.notes AS notes,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                            a.patient_id,
                            'Unknown Patient'
                        ) AS patient_name,
                        COALESCE(p.phone, a.patient_id, '') AS patient_phone,
                        COALESCE(
                            NULLIF(TRIM('Dr. ' || COALESCE(d.first_name, '') || ' ' || COALESCE(d.last_name, '')), 'Dr.'),
                            'Dr. Unassigned'
                        ) AS doctor_name,
                        COALESCE(d.specialty, 'General Practitioner') AS doctor_specialty,
                        ai.summary_text AS ai_summary
                    FROM appointments a
                    LEFT JOIN patients p ON p.phone = a.patient_id OR p.id::text = a.patient_id
                    LEFT JOIN doctors d ON d.id = a.doctor_id
                    LEFT JOIN LATERAL (
                        SELECT summary_text
                        FROM ai_summaries s
                        WHERE s.appointment_id = a.id
                        ORDER BY s.created_at DESC
                        LIMIT 1
                    ) ai ON true
                    WHERE a.patient_id = %s OR a.patient_id = %s
                    ORDER BY a.starts_at DESC
                    LIMIT 30
                    """,
                    (effective_patient_phone, effective_patient_id),
                )
                appointment_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        id::text AS id,
                        patient_id,
                        appointment_id::text AS appointment_id,
                        COALESCE(started_at, created_at) AS started_at,
                        duration_seconds,
                        COALESCE(reason, 'Phone call') AS motif,
                        symptoms,
                        summary,
                        recommendations,
                        COALESCE(evolution, 'stable') AS evolution,
                        COALESCE(urgency_score, 0) AS urgency_score
                    FROM call_records
                    WHERE patient_id = %s OR patient_id = %s
                    ORDER BY COALESCE(started_at, created_at) DESC
                    """,
                    (effective_patient_phone, effective_patient_id),
                )
                call_rows = cur.fetchall()

        appointments_payload: list[dict[str, Any]] = []
        for row in appointment_rows:
            starts_at = row.get("starts_at")
            ends_at = row.get("ends_at")
            if not isinstance(starts_at, datetime):
                continue
            patient_phone = str(row.get("patient_phone") or effective_patient_phone)
            appointments_payload.append(
                {
                    "id": str(row.get("id")),
                    "patientId": patient_phone,
                    "patientName": str(row.get("patient_name") or "Unknown Patient"),
                    "patientPhone": patient_phone,
                    "date": starts_at.date().isoformat(),
                    "time": starts_at.strftime("%H:%M"),
                    "startsAt": starts_at.isoformat(),
                    "endsAt": ends_at.isoformat() if isinstance(ends_at, datetime) else None,
                    "doctor": str(row.get("doctor_name") or "Dr. Unassigned"),
                    "doctorSpecialty": str(row.get("doctor_specialty") or "General Practitioner"),
                    "motif": str(row.get("motif") or "General consultation"),
                    "status": _map_appointment_status(row.get("raw_status")),
                    "rawStatus": str(row.get("raw_status") or "upcoming"),
                    "notes": row.get("notes"),
                    "aiSummary": row.get("ai_summary"),
                }
            )

        calls_payload: list[dict[str, Any]] = []
        for call in call_rows:
            started = call.get("started_at")
            call_date = (
                started.date().isoformat()
                if isinstance(started, datetime)
                else datetime.now(timezone.utc).date().isoformat()
            )
            calls_payload.append(
                {
                    "id": str(call.get("id") or ""),
                    "patientId": str(call.get("patient_id") or effective_patient_phone),
                    "appointmentId": call.get("appointment_id"),
                    "date": call_date,
                    "duration": _duration_text(call.get("duration_seconds")),
                    "motif": str(call.get("motif") or "Phone call"),
                    "symptoms": _as_str_list(call.get("symptoms")),
                    "summary": str(call.get("summary") or ""),
                    "recommendations": _as_str_list(call.get("recommendations")),
                    "evolution": str(call.get("evolution") or "stable"),
                    "urgencyScore": int(call.get("urgency_score") or 0),
                }
            )

        patient_dob = patient_row.get("date_of_birth")
        last_appointment = appointments_payload[0] if appointments_payload else None
        patient_payload = {
            "id": str(patient_row.get("id") or effective_patient_id),
            "firstName": str(patient_row.get("first_name") or "Unknown"),
            "lastName": str(patient_row.get("last_name") or "Patient"),
            "dateOfBirth": patient_dob.isoformat() if isinstance(patient_dob, date) else None,
            "phone": str(patient_row.get("phone") or effective_patient_phone),
            "email": str(patient_row.get("email") or "no-email@medvoice.local"),
            "bloodType": patient_row.get("blood_type"),
            "allergies": _as_str_list(patient_row.get("allergies")),
            "antecedents": _as_str_list(patient_row.get("antecedents")),
            "lastAppointmentDate": last_appointment["date"] if last_appointment else None,
            "lastAppointmentMotif": last_appointment["motif"] if last_appointment else None,
            "upcomingAppointmentsCount": sum(
                1 for item in appointments_payload if item["status"] in {"upcoming", "in-progress"}
            ),
        }

        return {
            "patient": patient_payload,
            "appointments": appointments_payload,
            "calls": calls_payload,
        }

    def cancel_appointment_and_queue_callback(
        self,
        appointment_id: str,
        *,
        reason: str | None = None,
    ) -> CancelledAppointmentResult | None:
        if not self.enabled:
            return None

        reason_text = (reason or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id::text AS id, a.patient_id, a.status, a.notes
                    FROM appointments a
                    WHERE a.id::text = %s
                    FOR UPDATE
                    """,
                    (appointment_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                current_status = str(row.get("status") or "upcoming").lower()
                if current_status in {"cancelled", "done", "no_show"}:
                    raise RuntimeError(
                        f"Appointment cannot be cancelled from status '{current_status}'."
                    )

                patient_id = str(row.get("patient_id") or "")
                cur.execute(
                    """
                    SELECT COALESCE(phone, %s) AS phone
                    FROM patients
                    WHERE phone = %s OR id::text = %s
                    LIMIT 1
                    """,
                    (patient_id, patient_id, patient_id),
                )
                patient_phone_row = cur.fetchone() or {}
                patient_phone = str(patient_phone_row.get("phone") or patient_id or "")
                existing_notes = str(row.get("notes") or "").strip()
                cancellation_note = f"Cancelled at {datetime.now(timezone.utc).isoformat()}"
                if reason_text:
                    cancellation_note += f" | reason={reason_text[:240]}"
                updated_notes = " ; ".join(part for part in [existing_notes, cancellation_note] if part)

                cur.execute(
                    """
                    UPDATE appointments
                    SET status = 'cancelled',
                        notes = %s,
                        updated_at = now()
                    WHERE id::text = %s
                    """,
                    (updated_notes, appointment_id),
                )

                callback_note = (
                    f"Appointment {appointment_id} was cancelled. Call patient to reschedule."
                )
                if reason_text:
                    callback_note += f" Reason: {reason_text[:240]}"
                cur.execute(
                    """
                    INSERT INTO followup_tasks (patient_id, scheduled_at, followup_type, status, notes)
                    VALUES (%s, now() + interval '10 minutes', 'call', 'pending', %s)
                    RETURNING id::text AS id, scheduled_at
                    """,
                    (patient_id or patient_phone, callback_note),
                )
                callback_row = cur.fetchone() or {}

                cur.execute(
                    """
                    INSERT INTO sms_messages (patient_id, appointment_id, message_type, body, status, sent_at)
                    VALUES (%s, %s::uuid, 'followup', %s, 'sent', now())
                    """,
                    (
                        patient_id or patient_phone,
                        appointment_id,
                        "Your appointment was cancelled. We will call you to help reschedule.",
                    ),
                )

            conn.commit()

        scheduled_at = callback_row.get("scheduled_at")
        return CancelledAppointmentResult(
            appointment_id=appointment_id,
            status="cancelled",
            callback_scheduled=True,
            callback_task_id=callback_row.get("id"),
            callback_scheduled_at=scheduled_at if isinstance(scheduled_at, datetime) else None,
            patient_id=patient_id or None,
            patient_phone=patient_phone or None,
        )

    def get_dashboard_overview(self, *, date_value: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {
                "kpis": {
                    "appointmentsToday": 0,
                    "callsToday": 0,
                    "cancellationsToday": 0,
                    "pendingCallbacks": 0,
                },
                "callbackTasks": [],
                "priorityQueue": [],
                "nextAppointments": [],
            }

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (
                            SELECT COUNT(*)::int
                            FROM appointments a
                            WHERE (%s::date IS NULL AND a.starts_at::date = CURRENT_DATE)
                               OR (%s::date IS NOT NULL AND a.starts_at::date = %s::date)
                        ) AS appointments_today,
                        (
                            SELECT COUNT(*)::int
                            FROM call_records c
                            WHERE (%s::date IS NULL AND COALESCE(c.started_at, c.created_at)::date = CURRENT_DATE)
                               OR (%s::date IS NOT NULL AND COALESCE(c.started_at, c.created_at)::date = %s::date)
                        ) AS calls_today,
                        (
                            SELECT COUNT(*)::int
                            FROM appointments a
                            WHERE a.status = 'cancelled'
                              AND (
                                (%s::date IS NULL AND a.updated_at::date = CURRENT_DATE)
                                OR (%s::date IS NOT NULL AND a.updated_at::date = %s::date)
                              )
                        ) AS cancellations_today,
                        (
                            SELECT COUNT(*)::int
                            FROM followup_tasks f
                            WHERE f.status = 'pending' AND f.followup_type = 'call'
                        ) AS pending_callbacks
                    """,
                    (
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                        date_value,
                    ),
                )
                kpis_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                        f.id::text AS id,
                        COALESCE(p.phone, f.patient_id, '') AS patient_id,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                            f.patient_id,
                            'Unknown Patient'
                        ) AS patient_name,
                        COALESCE(p.phone, f.patient_id, '') AS patient_phone,
                        f.scheduled_at,
                        f.notes,
                        f.status
                    FROM followup_tasks f
                    LEFT JOIN patients p
                        ON p.phone = f.patient_id OR p.id::text = f.patient_id
                    WHERE f.status = 'pending'
                      AND f.followup_type = 'call'
                    ORDER BY f.scheduled_at ASC
                    LIMIT 12
                    """
                )
                callback_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        c.id::text AS id,
                        COALESCE(p.phone, c.patient_id, '') AS patient_id,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                            c.patient_id,
                            'Unknown Patient'
                        ) AS patient_name,
                        COALESCE(p.phone, c.patient_id, '') AS patient_phone,
                        c.appointment_id::text AS appointment_id,
                        COALESCE(c.urgency_score, 0) AS urgency_score,
                        c.symptoms,
                        COALESCE(c.summary, '') AS summary,
                        COALESCE(c.started_at, c.created_at) AS created_at
                    FROM call_records c
                    LEFT JOIN patients p
                        ON p.phone = c.patient_id OR p.id::text = c.patient_id
                    WHERE COALESCE(c.urgency_score, 0) >= 5
                    ORDER BY COALESCE(c.urgency_score, 0) DESC, COALESCE(c.started_at, c.created_at) DESC
                    LIMIT 10
                    """
                )
                priority_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        a.id::text AS id,
                        a.patient_id AS patient_id,
                        a.starts_at AS starts_at,
                        a.ends_at AS ends_at,
                        COALESCE(a.reason, 'General consultation') AS motif,
                        COALESCE(a.status, 'upcoming') AS raw_status,
                        a.notes AS notes,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''),
                            a.patient_id,
                            'Unknown Patient'
                        ) AS patient_name,
                        COALESCE(p.phone, a.patient_id, '') AS patient_phone,
                        COALESCE(
                            NULLIF(TRIM('Dr. ' || COALESCE(d.first_name, '') || ' ' || COALESCE(d.last_name, '')), 'Dr.'),
                            'Dr. Unassigned'
                        ) AS doctor_name,
                        COALESCE(d.specialty, 'General Practitioner') AS doctor_specialty,
                        ai.summary_text AS ai_summary
                    FROM appointments a
                    LEFT JOIN patients p
                        ON p.phone = a.patient_id OR p.id::text = a.patient_id
                    LEFT JOIN doctors d
                        ON d.id = a.doctor_id
                    LEFT JOIN LATERAL (
                        SELECT summary_text
                        FROM ai_summaries s
                        WHERE s.appointment_id = a.id
                        ORDER BY s.created_at DESC
                        LIMIT 1
                    ) ai ON true
                    WHERE a.status IN ('upcoming', 'confirmed', 'in_progress')
                      AND a.starts_at >= now()
                    ORDER BY a.starts_at ASC
                    LIMIT 8
                    """
                )
                next_appointments_rows = cur.fetchall()

        callback_tasks: list[dict[str, Any]] = []
        for row in callback_rows:
            scheduled_at = row.get("scheduled_at")
            callback_tasks.append(
                {
                    "id": str(row.get("id") or ""),
                    "patientId": str(row.get("patient_id") or ""),
                    "patientName": str(row.get("patient_name") or "Unknown Patient"),
                    "patientPhone": str(row.get("patient_phone") or ""),
                    "scheduledAt": (
                        scheduled_at.isoformat()
                        if isinstance(scheduled_at, datetime)
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    "notes": row.get("notes"),
                    "status": str(row.get("status") or "pending"),
                }
            )

        priority_queue: list[dict[str, Any]] = []
        for row in priority_rows:
            created_at = row.get("created_at")
            priority_queue.append(
                {
                    "id": str(row.get("id") or ""),
                    "patientId": str(row.get("patient_id") or ""),
                    "patientName": str(row.get("patient_name") or "Unknown Patient"),
                    "patientPhone": str(row.get("patient_phone") or ""),
                    "appointmentId": row.get("appointment_id"),
                    "urgencyScore": int(row.get("urgency_score") or 0),
                    "symptoms": _as_str_list(row.get("symptoms")),
                    "summary": str(row.get("summary") or ""),
                    "createdAt": (
                        created_at.isoformat()
                        if isinstance(created_at, datetime)
                        else datetime.now(timezone.utc).isoformat()
                    ),
                }
            )

        next_appointments: list[dict[str, Any]] = []
        for row in next_appointments_rows:
            starts_at = row.get("starts_at")
            ends_at = row.get("ends_at")
            if not isinstance(starts_at, datetime):
                continue
            patient_phone = str(row.get("patient_phone") or row.get("patient_id") or "")
            next_appointments.append(
                {
                    "id": str(row.get("id")),
                    "patientId": patient_phone,
                    "patientName": str(row.get("patient_name") or "Unknown Patient"),
                    "patientPhone": patient_phone,
                    "date": starts_at.date().isoformat(),
                    "time": starts_at.strftime("%H:%M"),
                    "startsAt": starts_at.isoformat(),
                    "endsAt": ends_at.isoformat() if isinstance(ends_at, datetime) else None,
                    "doctor": str(row.get("doctor_name") or "Dr. Unassigned"),
                    "doctorSpecialty": str(row.get("doctor_specialty") or "General Practitioner"),
                    "motif": str(row.get("motif") or "General consultation"),
                    "status": _map_appointment_status(row.get("raw_status")),
                    "rawStatus": str(row.get("raw_status") or "upcoming"),
                    "notes": row.get("notes"),
                    "aiSummary": row.get("ai_summary"),
                }
            )

        return {
            "kpis": {
                "appointmentsToday": int(kpis_row.get("appointments_today") or 0),
                "callsToday": int(kpis_row.get("calls_today") or 0),
                "cancellationsToday": int(kpis_row.get("cancellations_today") or 0),
                "pendingCallbacks": int(kpis_row.get("pending_callbacks") or 0),
            },
            "callbackTasks": callback_tasks,
            "priorityQueue": priority_queue,
            "nextAppointments": next_appointments,
        }
