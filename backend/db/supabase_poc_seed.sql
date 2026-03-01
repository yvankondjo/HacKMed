-- Supabase POC seed
-- Run order:
-- 1) Execute backend/db/schema.sql in Supabase SQL Editor
-- 2) Execute this file

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Single doctor user (POC)
INSERT INTO users (id, email, password_hash, role, is_active)
VALUES (
  '10000000-0000-0000-0000-000000000001',
  'poc.doctor@medvoice.local',
  NULL,
  'doctor',
  true
)
ON CONFLICT (id) DO UPDATE
SET email = EXCLUDED.email,
    role = EXCLUDED.role,
    is_active = true,
    updated_at = now();

INSERT INTO doctors (
  id,
  user_id,
  first_name,
  last_name,
  specialty,
  phone,
  license_number
)
VALUES (
  '20000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'Laurent',
  'Martin',
  'General Practitioner',
  '+33611111111',
  'POC-LICENSE-001'
)
ON CONFLICT (id) DO UPDATE
SET first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    specialty = EXCLUDED.specialty,
    phone = EXCLUDED.phone,
    updated_at = now();

-- Patients
INSERT INTO patients (
  id,
  first_name,
  last_name,
  date_of_birth,
  sex,
  phone,
  email,
  blood_type
)
VALUES
  (
    '30000000-0000-0000-0000-000000000001',
    'Marie',
    'Dupont',
    '1978-06-15',
    'female',
    '+33612345678',
    'marie.dupont@email.com',
    'A+'
  ),
  (
    '30000000-0000-0000-0000-000000000002',
    'Jean',
    'Martin',
    '1985-03-22',
    'male',
    '+33698765432',
    'jean.martin@email.com',
    'O-'
  ),
  (
    '30000000-0000-0000-0000-000000000003',
    'Sophie',
    'Bernard',
    '1992-11-08',
    'female',
    '+33655443322',
    'sophie.bernard@email.com',
    'B+'
  )
ON CONFLICT (id) DO UPDATE
SET first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    phone = EXCLUDED.phone,
    email = EXCLUDED.email,
    updated_at = now();

INSERT INTO patient_allergies (patient_id, substance, reaction, severity, noted_at)
VALUES
  ('30000000-0000-0000-0000-000000000001', 'Penicillin', 'Rash', 'high', CURRENT_DATE),
  ('30000000-0000-0000-0000-000000000002', 'Aspirin', 'Gastric pain', 'moderate', CURRENT_DATE)
ON CONFLICT DO NOTHING;

INSERT INTO patient_conditions (patient_id, label, status, notes)
VALUES
  ('30000000-0000-0000-0000-000000000001', 'Hypertension', 'active', 'Monitoring blood pressure'),
  ('30000000-0000-0000-0000-000000000002', 'Asthma', 'active', 'Night episodes')
ON CONFLICT DO NOTHING;

-- Appointments with a single doctor
INSERT INTO appointments (
  id,
  patient_id,
  doctor_id,
  starts_at,
  ends_at,
  reason,
  status,
  location,
  created_by
)
VALUES
  (
    '40000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    date_trunc('day', now()) + interval '9 hour',
    date_trunc('day', now()) + interval '9 hour 20 minutes',
    'Blood pressure follow-up',
    'done',
    'Cabinet A',
    '10000000-0000-0000-0000-000000000001'
  ),
  (
    '40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001',
    date_trunc('day', now()) + interval '10 hour 30 minutes',
    date_trunc('day', now()) + interval '10 hour 50 minutes',
    'Asthma episode',
    'upcoming',
    'Cabinet A',
    '10000000-0000-0000-0000-000000000001'
  ),
  (
    '40000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000001',
    date_trunc('day', now()) + interval '11 hour 30 minutes',
    date_trunc('day', now()) + interval '11 hour 50 minutes',
    'Migraine follow-up',
    'upcoming',
    'Cabinet A',
    '10000000-0000-0000-0000-000000000001'
  )
ON CONFLICT (id) DO UPDATE
SET doctor_id = EXCLUDED.doctor_id,
    reason = EXCLUDED.reason,
    status = EXCLUDED.status,
    updated_at = now();

INSERT INTO consultations (id, appointment_id, started_at, ended_at, state, urgency_score)
VALUES (
  '50000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  now() - interval '1 hour',
  now() - interval '40 minutes',
  'ended',
  4
)
ON CONFLICT (id) DO UPDATE
SET state = EXCLUDED.state,
    ended_at = EXCLUDED.ended_at,
    updated_at = now();

INSERT INTO transcript_messages (consultation_id, sender_type, content, sent_at)
VALUES
  ('50000000-0000-0000-0000-000000000001', 'patient', 'J''ai mal a la gorge depuis 3 jours.', now() - interval '59 minutes'),
  ('50000000-0000-0000-0000-000000000001', 'doctor', 'Avez-vous eu de la fievre ?', now() - interval '58 minutes'),
  ('50000000-0000-0000-0000-000000000001', 'patient', 'Oui, autour de 38.5 hier soir.', now() - interval '57 minutes')
ON CONFLICT DO NOTHING;

INSERT INTO ai_summaries (appointment_id, consultation_id, type, summary_text, probable_diagnosis, urgency_score)
VALUES
  (
    '40000000-0000-0000-0000-000000000001',
    NULL,
    'phone_briefing',
    'Initial call briefing captured by voice agent.',
    'Possible pharyngitis',
    3
  ),
  (
    '40000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000001',
    'live_summary',
    'Live consultation summary in progress.',
    'Bacterial angina probable',
    4
  ),
  (
    '40000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000001',
    'final_report',
    'Final medical report generated.',
    'Bacterial angina probable',
    4
  )
ON CONFLICT DO NOTHING;

INSERT INTO call_records (
  patient_id,
  doctor_id,
  appointment_id,
  started_at,
  ended_at,
  duration_seconds,
  reason,
  summary,
  evolution,
  urgency_score
)
VALUES (
  '30000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  now() - interval '2 day',
  now() - interval '2 day' + interval '8 minutes',
  480,
  'Booking intake call',
  'Patient asked for a consultation booking.',
  'stable',
  4
)
ON CONFLICT DO NOTHING;

INSERT INTO prescriptions (id, appointment_id, patient_id, doctor_id, status, issued_at, notes)
VALUES (
  '60000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  'validated',
  now() - interval '30 minutes',
  'POC prescription'
)
ON CONFLICT (id) DO UPDATE
SET status = EXCLUDED.status,
    updated_at = now();

INSERT INTO prescription_items (prescription_id, medication_name, dosage, frequency, duration, instructions)
VALUES
  (
    '60000000-0000-0000-0000-000000000001',
    'Amoxicillin',
    '1g',
    '3x/day',
    '6 days',
    'After meals'
  ),
  (
    '60000000-0000-0000-0000-000000000001',
    'Paracetamol',
    '1000mg',
    'every 6h if needed',
    '5 days',
    'Max 3g/day'
  )
ON CONFLICT DO NOTHING;

INSERT INTO sms_messages (patient_id, appointment_id, message_type, body, status, sent_at)
VALUES
  (
    '30000000-0000-0000-0000-000000000001',
    '40000000-0000-0000-0000-000000000001',
    'booking_confirmation',
    'Votre rendez-vous est confirme.',
    'sent',
    now() - interval '2 day'
  ),
  (
    '30000000-0000-0000-0000-000000000001',
    '40000000-0000-0000-0000-000000000001',
    'prescription',
    'Votre ordonnance est disponible.',
    'sent',
    now() - interval '20 minutes'
  )
ON CONFLICT DO NOTHING;

INSERT INTO followup_tasks (patient_id, prescription_id, scheduled_at, followup_type, status, attempt_number, notes)
VALUES
  (
    '30000000-0000-0000-0000-000000000001',
    '60000000-0000-0000-0000-000000000001',
    now() + interval '2 day',
    'sms',
    'pending',
    1,
    'POC follow-up'
  )
ON CONFLICT DO NOTHING;

COMMIT;
