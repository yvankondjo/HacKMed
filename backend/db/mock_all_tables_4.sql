-- Full mock dataset for all tables (4 coherent patient cases)
-- Idempotent: can be re-run safely.
-- Run after schema.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- USERS
INSERT INTO users (id, email, phone, password_hash, role, is_active, last_login_at)
VALUES
  ('71000000-0000-0000-0000-000000000001', 'doctor.mock@medvoice.local', '+33610000001', NULL, 'doctor', true, now() - interval '1 day'),
  ('71000000-0000-0000-0000-000000000002', 'admin.mock@medvoice.local', '+33610000002', NULL, 'admin', true, now() - interval '2 day'),
  ('71000000-0000-0000-0000-000000000101', 'alice.example@example.test', '+33670000101', NULL, 'patient', true, now() - interval '3 day'),
  ('71000000-0000-0000-0000-000000000102', 'bruno.sample@example.test', '+33670000102', NULL, 'patient', true, now() - interval '4 day'),
  ('71000000-0000-0000-0000-000000000103', 'chloe.demo@example.test', '+33670000103', NULL, 'patient', true, now() - interval '5 day'),
  ('71000000-0000-0000-0000-000000000104', 'dorian.mock@example.test', '+33670000104', NULL, 'patient', true, now() - interval '6 day')
ON CONFLICT (id) DO UPDATE
SET
  email = EXCLUDED.email,
  phone = EXCLUDED.phone,
  role = EXCLUDED.role,
  is_active = EXCLUDED.is_active,
  last_login_at = EXCLUDED.last_login_at,
  updated_at = now();

-- DOCTORS
INSERT INTO doctors (
  id, user_id, first_name, last_name, specialty, phone, avatar_url, license_number
)
VALUES
  (
    '72000000-0000-0000-0000-000000000001',
    '71000000-0000-0000-0000-000000000001',
    'Alex',
    'Care',
    'General Practitioner',
    '+33610000001',
    NULL,
    'MOCK-LIC-001'
  )
ON CONFLICT (id) DO UPDATE
SET
  first_name = EXCLUDED.first_name,
  last_name = EXCLUDED.last_name,
  specialty = EXCLUDED.specialty,
  phone = EXCLUDED.phone,
  license_number = EXCLUDED.license_number,
  updated_at = now();

-- PATIENTS
INSERT INTO patients (
  id, user_id, phone, first_name, last_name, date_of_birth, sex, email, blood_type, address
)
VALUES
  ('73000000-0000-0000-0000-000000000001', '71000000-0000-0000-0000-000000000101', '+33670000101', 'Alice', 'Example', '1993-05-17', 'female', 'alice.example@example.test', 'A+', '1 Rue des Tests, Paris'),
  ('73000000-0000-0000-0000-000000000002', '71000000-0000-0000-0000-000000000102', '+33670000102', 'Bruno', 'Sample', '1988-11-02', 'male', 'bruno.sample@example.test', 'O-', '2 Avenue des Tests, Marseille'),
  ('73000000-0000-0000-0000-000000000003', '71000000-0000-0000-0000-000000000103', '+33670000103', 'Chloe', 'Demo', '1979-01-26', 'female', 'chloe.demo@example.test', 'B+', '3 Boulevard des Tests, Lille'),
  ('73000000-0000-0000-0000-000000000004', '71000000-0000-0000-0000-000000000104', '+33670000104', 'Dorian', 'Mock', '1997-09-09', 'male', 'dorian.mock@example.test', 'AB+', '4 Place des Tests, Nantes')
ON CONFLICT (phone) DO UPDATE
SET
  user_id = EXCLUDED.user_id,
  first_name = EXCLUDED.first_name,
  last_name = EXCLUDED.last_name,
  date_of_birth = EXCLUDED.date_of_birth,
  sex = EXCLUDED.sex,
  email = EXCLUDED.email,
  blood_type = EXCLUDED.blood_type,
  address = EXCLUDED.address,
  updated_at = now();

-- PATIENT ALLERGIES
INSERT INTO patient_allergies (id, patient_id, substance, reaction, severity, noted_at)
VALUES
  ('74000000-0000-0000-0000-000000000001', '+33670000101', 'Penicillin', 'Rash', 'high', current_date - 150),
  ('74000000-0000-0000-0000-000000000002', '+33670000102', 'Aspirin', 'Gastric pain', 'moderate', current_date - 260),
  ('74000000-0000-0000-0000-000000000003', '+33670000103', 'Peanuts', 'Swelling', 'high', current_date - 90),
  ('74000000-0000-0000-0000-000000000004', '+33670000104', 'None reported', NULL, 'unknown', current_date - 7)
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  substance = EXCLUDED.substance,
  reaction = EXCLUDED.reaction,
  severity = EXCLUDED.severity,
  noted_at = EXCLUDED.noted_at;

-- PATIENT CONDITIONS
INSERT INTO patient_conditions (id, patient_id, label, start_date, end_date, status, notes)
VALUES
  ('75000000-0000-0000-0000-000000000001', '+33670000101', 'Hypertension', current_date - 1100, NULL, 'active', 'Needs monthly BP check'),
  ('75000000-0000-0000-0000-000000000002', '+33670000102', 'Asthma', current_date - 2000, NULL, 'active', 'Uses rescue inhaler'),
  ('75000000-0000-0000-0000-000000000003', '+33670000103', 'Migraine', current_date - 1300, NULL, 'active', 'Triggered by stress'),
  ('75000000-0000-0000-0000-000000000004', '+33670000104', 'Lumbar pain history', current_date - 300, current_date - 5, 'resolved', 'Post-physio improvement')
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  label = EXCLUDED.label,
  start_date = EXCLUDED.start_date,
  end_date = EXCLUDED.end_date,
  status = EXCLUDED.status,
  notes = EXCLUDED.notes;

-- APPOINTMENTS
INSERT INTO appointments (
  id, patient_id, doctor_id, starts_at, ends_at, reason, status, location, notes, created_by
)
VALUES
  (
    '76000000-0000-0000-0000-000000000001',
    '+33670000101',
    '72000000-0000-0000-0000-000000000001',
    now() - interval '3 day',
    now() - interval '3 day' + interval '20 minutes',
    'Blood pressure follow-up',
    'done',
    'Cabinet A',
    'Routine control',
    '71000000-0000-0000-0000-000000000001'
  ),
  (
    '76000000-0000-0000-0000-000000000002',
    '+33670000102',
    '72000000-0000-0000-0000-000000000001',
    now() + interval '1 day' + interval '09:30',
    now() + interval '1 day' + interval '09:50',
    'Asthma symptoms',
    'confirmed',
    'Cabinet A',
    'Bring old spirometry',
    '71000000-0000-0000-0000-000000000001'
  ),
  (
    '76000000-0000-0000-0000-000000000003',
    '+33670000103',
    '72000000-0000-0000-0000-000000000001',
    now() + interval '2 day' + interval '11:00',
    now() + interval '2 day' + interval '11:20',
    'Migraine recurrence',
    'upcoming',
    'Cabinet B',
    'Needs trigger review',
    '71000000-0000-0000-0000-000000000001'
  ),
  (
    '76000000-0000-0000-0000-000000000004',
    '+33670000104',
    '72000000-0000-0000-0000-000000000001',
    now() - interval '1 day',
    now() - interval '1 day' + interval '20 minutes',
    'Low back pain',
    'done',
    'Teleconsultation',
    'Transcript includes email confirmation',
    '71000000-0000-0000-0000-000000000001'
  )
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  doctor_id = EXCLUDED.doctor_id,
  starts_at = EXCLUDED.starts_at,
  ends_at = EXCLUDED.ends_at,
  reason = EXCLUDED.reason,
  status = EXCLUDED.status,
  location = EXCLUDED.location,
  notes = EXCLUDED.notes,
  updated_at = now();

-- CONSULTATIONS
INSERT INTO consultations (
  id, appointment_id, started_at, ended_at, state, urgency_score, detected_symptoms, safety_alerts
)
VALUES
  (
    '77000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000001',
    now() - interval '3 day',
    now() - interval '3 day' + interval '20 minutes',
    'ended',
    3,
    '["Headache"]'::jsonb,
    '[]'::jsonb
  ),
  (
    '77000000-0000-0000-0000-000000000002',
    '76000000-0000-0000-0000-000000000002',
    NULL,
    NULL,
    'not_started',
    2,
    '[]'::jsonb,
    '[]'::jsonb
  ),
  (
    '77000000-0000-0000-0000-000000000003',
    '76000000-0000-0000-0000-000000000003',
    NULL,
    NULL,
    'not_started',
    2,
    '[]'::jsonb,
    '[]'::jsonb
  ),
  (
    '77000000-0000-0000-0000-000000000004',
    '76000000-0000-0000-0000-000000000004',
    now() - interval '1 day',
    now() - interval '1 day' + interval '20 minutes',
    'ended',
    4,
    '["Low-back pain","Radiation to leg"]'::jsonb,
    '[]'::jsonb
  )
ON CONFLICT (id) DO UPDATE
SET
  appointment_id = EXCLUDED.appointment_id,
  started_at = EXCLUDED.started_at,
  ended_at = EXCLUDED.ended_at,
  state = EXCLUDED.state,
  urgency_score = EXCLUDED.urgency_score,
  detected_symptoms = EXCLUDED.detected_symptoms,
  safety_alerts = EXCLUDED.safety_alerts,
  updated_at = now();

-- TRANSCRIPT MESSAGES (4 rows total)
INSERT INTO transcript_messages (
  id, consultation_id, sender_type, sender_id, content, sent_at, meta
)
VALUES
  (
    '78000000-0000-0000-0000-000000000001',
    '77000000-0000-0000-0000-000000000004',
    'doctor',
    '71000000-0000-0000-0000-000000000001',
    'Please confirm your email for prescription delivery.',
    now() - interval '1 day' + interval '5 minutes',
    '{"topic":"email"}'::jsonb
  ),
  (
    '78000000-0000-0000-0000-000000000002',
    '77000000-0000-0000-0000-000000000004',
    'patient',
    '71000000-0000-0000-0000-000000000104',
    'My email is dorian.mock@example.test',
    now() - interval '1 day' + interval '6 minutes',
    '{"captured":true}'::jsonb
  ),
  (
    '78000000-0000-0000-0000-000000000003',
    '77000000-0000-0000-0000-000000000001',
    'patient',
    '71000000-0000-0000-0000-000000000101',
    'No chest pain, just mild headache.',
    now() - interval '3 day' + interval '8 minutes',
    '{}'::jsonb
  ),
  (
    '78000000-0000-0000-0000-000000000004',
    '77000000-0000-0000-0000-000000000001',
    'ai',
    NULL,
    'Summary generated and attached to appointment.',
    now() - interval '3 day' + interval '18 minutes',
    '{"source":"agent"}'::jsonb
  )
ON CONFLICT (id) DO UPDATE
SET
  consultation_id = EXCLUDED.consultation_id,
  sender_type = EXCLUDED.sender_type,
  sender_id = EXCLUDED.sender_id,
  content = EXCLUDED.content,
  sent_at = EXCLUDED.sent_at,
  meta = EXCLUDED.meta;

-- AI SUMMARIES
INSERT INTO ai_summaries (
  id, appointment_id, consultation_id, type, summary_text, probable_diagnosis, recommendations, symptoms, urgency_score, model_info
)
VALUES
  (
    '79000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000001',
    '77000000-0000-0000-0000-000000000001',
    'final_report',
    'Routine follow-up completed without red flags.',
    'Tension headache',
    '["Hydration","Sleep hygiene"]'::jsonb,
    '["Headache"]'::jsonb,
    3,
    '{"model":"gpt-4o-mini"}'::jsonb
  ),
  (
    '79000000-0000-0000-0000-000000000002',
    '76000000-0000-0000-0000-000000000002',
    '77000000-0000-0000-0000-000000000002',
    'phone_briefing',
    'Upcoming consultation for asthma symptoms.',
    'Asthma flare (to confirm)',
    '["Assess trigger exposure"]'::jsonb,
    '["Dyspnea"]'::jsonb,
    4,
    '{"model":"gpt-4o-mini"}'::jsonb
  ),
  (
    '79000000-0000-0000-0000-000000000003',
    '76000000-0000-0000-0000-000000000003',
    '77000000-0000-0000-0000-000000000003',
    'live_summary',
    'Live summary placeholder before consultation.',
    'Migraine recurrence',
    '["Track frequency"]'::jsonb,
    '["Migraine"]'::jsonb,
    3,
    '{"model":"gpt-4o-mini"}'::jsonb
  ),
  (
    '79000000-0000-0000-0000-000000000004',
    '76000000-0000-0000-0000-000000000004',
    '77000000-0000-0000-0000-000000000004',
    'final_report',
    'Back pain follow-up; prescription sent by email.',
    'Lumbar strain',
    '["Relative rest","Physio"]'::jsonb,
    '["Low-back pain"]'::jsonb,
    4,
    '{"model":"gpt-4o-mini"}'::jsonb
  )
ON CONFLICT (id) DO UPDATE
SET
  appointment_id = EXCLUDED.appointment_id,
  consultation_id = EXCLUDED.consultation_id,
  type = EXCLUDED.type,
  summary_text = EXCLUDED.summary_text,
  probable_diagnosis = EXCLUDED.probable_diagnosis,
  recommendations = EXCLUDED.recommendations,
  symptoms = EXCLUDED.symptoms,
  urgency_score = EXCLUDED.urgency_score,
  model_info = EXCLUDED.model_info;

-- CALL RECORDS
INSERT INTO call_records (
  id, patient_id, doctor_id, appointment_id, started_at, ended_at, duration_seconds, reason, symptoms, summary, recommendations, evolution, urgency_score, recording_url
)
VALUES
  (
    '7a000000-0000-0000-0000-000000000001',
    '+33670000101',
    '72000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000001',
    now() - interval '4 day',
    now() - interval '4 day' + interval '8 minutes',
    480,
    'Intake call',
    '["Headache"]'::jsonb,
    'Patient requested follow-up.',
    '["Book consultation"]'::jsonb,
    'stable',
    3,
    NULL
  ),
  (
    '7a000000-0000-0000-0000-000000000002',
    '+33670000102',
    '72000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000002',
    now() - interval '2 day',
    now() - interval '2 day' + interval '10 minutes',
    600,
    'Follow-up call',
    '["Dyspnea","Wheezing"]'::jsonb,
    'Symptoms reported worsening at night.',
    '["Urgent review if worsening"]'::jsonb,
    'worsening',
    6,
    NULL
  ),
  (
    '7a000000-0000-0000-0000-000000000003',
    '+33670000103',
    '72000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000003',
    now() - interval '1 day',
    now() - interval '1 day' + interval '7 minutes',
    420,
    'Reminder call',
    '["Migraine"]'::jsonb,
    'Patient confirms attendance.',
    '["Hydrate before consultation"]'::jsonb,
    'stable',
    2,
    NULL
  ),
  (
    '7a000000-0000-0000-0000-000000000004',
    '+33670000104',
    '72000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000004',
    now() - interval '1 day',
    now() - interval '1 day' + interval '11 minutes',
    660,
    'Consultation call',
    '["Low-back pain","Radiation to leg"]'::jsonb,
    'Prescription discussed and email confirmed.',
    '["Posture advice"]'::jsonb,
    'improvement',
    4,
    NULL
  )
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  doctor_id = EXCLUDED.doctor_id,
  appointment_id = EXCLUDED.appointment_id,
  started_at = EXCLUDED.started_at,
  ended_at = EXCLUDED.ended_at,
  duration_seconds = EXCLUDED.duration_seconds,
  reason = EXCLUDED.reason,
  symptoms = EXCLUDED.symptoms,
  summary = EXCLUDED.summary,
  recommendations = EXCLUDED.recommendations,
  evolution = EXCLUDED.evolution,
  urgency_score = EXCLUDED.urgency_score,
  recording_url = EXCLUDED.recording_url;

-- PRESCRIPTIONS
INSERT INTO prescriptions (
  id, appointment_id, patient_id, doctor_id, status, issued_at, notes
)
VALUES
  (
    '7b000000-0000-0000-0000-000000000001',
    '76000000-0000-0000-0000-000000000001',
    '+33670000101',
    '72000000-0000-0000-0000-000000000001',
    'validated',
    now() - interval '3 day' + interval '18 minutes',
    'Routine prescription'
  ),
  (
    '7b000000-0000-0000-0000-000000000002',
    '76000000-0000-0000-0000-000000000002',
    '+33670000102',
    '72000000-0000-0000-0000-000000000001',
    'draft',
    NULL,
    'To be finalized at consultation'
  ),
  (
    '7b000000-0000-0000-0000-000000000003',
    '76000000-0000-0000-0000-000000000003',
    '+33670000103',
    '72000000-0000-0000-0000-000000000001',
    'draft',
    NULL,
    'Migraine management plan'
  ),
  (
    '7b000000-0000-0000-0000-000000000004',
    '76000000-0000-0000-0000-000000000004',
    '+33670000104',
    '72000000-0000-0000-0000-000000000001',
    'sent',
    now() - interval '1 day' + interval '19 minutes',
    'Sent via Resend'
  )
ON CONFLICT (id) DO UPDATE
SET
  appointment_id = EXCLUDED.appointment_id,
  patient_id = EXCLUDED.patient_id,
  doctor_id = EXCLUDED.doctor_id,
  status = EXCLUDED.status,
  issued_at = EXCLUDED.issued_at,
  notes = EXCLUDED.notes,
  updated_at = now();

-- PRESCRIPTION ITEMS
INSERT INTO prescription_items (
  id, prescription_id, medication_name, dosage, frequency, duration, instructions, is_ai_suggested
)
VALUES
  ('7c000000-0000-0000-0000-000000000001', '7b000000-0000-0000-0000-000000000001', 'Paracetamol', '1000mg', 'Every 8h if needed', '3 days', 'After meal', true),
  ('7c000000-0000-0000-0000-000000000002', '7b000000-0000-0000-0000-000000000002', 'Salbutamol', '100mcg', '1-2 puffs as needed', '5 days', 'Use spacer', true),
  ('7c000000-0000-0000-0000-000000000003', '7b000000-0000-0000-0000-000000000003', 'Sumatriptan', '50mg', 'At onset, may repeat once', 'As needed', 'Max 2/day', true),
  ('7c000000-0000-0000-0000-000000000004', '7b000000-0000-0000-0000-000000000004', 'Ibuprofen', '400mg', '3 times/day', '5 days', 'With food', true)
ON CONFLICT (id) DO UPDATE
SET
  prescription_id = EXCLUDED.prescription_id,
  medication_name = EXCLUDED.medication_name,
  dosage = EXCLUDED.dosage,
  frequency = EXCLUDED.frequency,
  duration = EXCLUDED.duration,
  instructions = EXCLUDED.instructions,
  is_ai_suggested = EXCLUDED.is_ai_suggested;

-- NOTIFICATIONS
INSERT INTO notifications (
  id, user_id, type, title, message, related_entity_type, related_entity_id, read_at
)
VALUES
  (
    '7d000000-0000-0000-0000-000000000001',
    '71000000-0000-0000-0000-000000000001',
    'reminder',
    'Consultation done',
    'Alice consultation has been completed.',
    'appointment',
    '76000000-0000-0000-0000-000000000001',
    now() - interval '2 day'
  ),
  (
    '7d000000-0000-0000-0000-000000000002',
    '71000000-0000-0000-0000-000000000001',
    'alert',
    'Asthma risk',
    'Bruno reported nocturnal dyspnea.',
    'appointment',
    '76000000-0000-0000-0000-000000000002',
    NULL
  ),
  (
    '7d000000-0000-0000-0000-000000000003',
    '71000000-0000-0000-0000-000000000002',
    'system',
    'Daily sync',
    'Data sync completed successfully.',
    'job',
    NULL,
    now() - interval '8 hour'
  ),
  (
    '7d000000-0000-0000-0000-000000000004',
    '71000000-0000-0000-0000-000000000001',
    'document',
    'Prescription emailed',
    'Dorian prescription was sent by email.',
    'prescription',
    '7b000000-0000-0000-0000-000000000004',
    NULL
  )
ON CONFLICT (id) DO UPDATE
SET
  user_id = EXCLUDED.user_id,
  type = EXCLUDED.type,
  title = EXCLUDED.title,
  message = EXCLUDED.message,
  related_entity_type = EXCLUDED.related_entity_type,
  related_entity_id = EXCLUDED.related_entity_id,
  read_at = EXCLUDED.read_at;

-- SMS MESSAGES
INSERT INTO sms_messages (
  id, patient_id, appointment_id, message_type, body, sent_at, status, responded_at
)
VALUES
  (
    '7e000000-0000-0000-0000-000000000001',
    '+33670000101',
    '76000000-0000-0000-0000-000000000001',
    'booking_confirmation',
    'Your appointment is confirmed for today 09:00.',
    now() - interval '4 day',
    'delivered',
    now() - interval '4 day' + interval '2 minutes'
  ),
  (
    '7e000000-0000-0000-0000-000000000002',
    '+33670000102',
    '76000000-0000-0000-0000-000000000002',
    'reminder',
    'Reminder: appointment tomorrow at 09:30.',
    now() - interval '2 hour',
    'sent',
    NULL
  ),
  (
    '7e000000-0000-0000-0000-000000000003',
    '+33670000103',
    '76000000-0000-0000-0000-000000000003',
    'followup',
    'Please confirm if symptoms are stable.',
    now() - interval '1 day',
    'no_response',
    NULL
  ),
  (
    '7e000000-0000-0000-0000-000000000004',
    '+33670000104',
    '76000000-0000-0000-0000-000000000004',
    'prescription',
    'Your prescription has been sent to your email.',
    now() - interval '1 day',
    'delivered',
    now() - interval '1 day' + interval '1 minute'
  )
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  appointment_id = EXCLUDED.appointment_id,
  message_type = EXCLUDED.message_type,
  body = EXCLUDED.body,
  sent_at = EXCLUDED.sent_at,
  status = EXCLUDED.status,
  responded_at = EXCLUDED.responded_at;

-- FOLLOWUP TASKS
INSERT INTO followup_tasks (
  id, patient_id, prescription_id, scheduled_at, followup_type, status, attempt_number, notes
)
VALUES
  (
    '7f000000-0000-0000-0000-000000000001',
    '+33670000101',
    '7b000000-0000-0000-0000-000000000001',
    now() + interval '1 day',
    'call',
    'pending',
    1,
    'Check headache evolution'
  ),
  (
    '7f000000-0000-0000-0000-000000000002',
    '+33670000102',
    '7b000000-0000-0000-0000-000000000002',
    now() + interval '2 day',
    'sms',
    'pending',
    1,
    'Asthma control reminder'
  ),
  (
    '7f000000-0000-0000-0000-000000000003',
    '+33670000103',
    '7b000000-0000-0000-0000-000000000003',
    now() - interval '1 day',
    'call',
    'completed',
    1,
    'Migraine follow-up completed'
  ),
  (
    '7f000000-0000-0000-0000-000000000004',
    '+33670000104',
    '7b000000-0000-0000-0000-000000000004',
    now() + interval '3 day',
    'sms',
    'sent',
    1,
    'Prescription adherence check'
  )
ON CONFLICT (id) DO UPDATE
SET
  patient_id = EXCLUDED.patient_id,
  prescription_id = EXCLUDED.prescription_id,
  scheduled_at = EXCLUDED.scheduled_at,
  followup_type = EXCLUDED.followup_type,
  status = EXCLUDED.status,
  attempt_number = EXCLUDED.attempt_number,
  notes = EXCLUDED.notes;

COMMIT;
