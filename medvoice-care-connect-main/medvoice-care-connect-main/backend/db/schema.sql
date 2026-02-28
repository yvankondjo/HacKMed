-- USERS
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT,
  role TEXT CHECK (role IN ('doctor', 'patient', 'admin')) NOT NULL,
  is_active BOOLEAN DEFAULT true,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- DOCTORS
CREATE TABLE doctors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID UNIQUE REFERENCES users(id),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  specialty TEXT,
  phone TEXT,
  avatar_url TEXT,
  license_number TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- PATIENTS
CREATE TABLE patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID UNIQUE REFERENCES users(id),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  date_of_birth DATE,
  sex TEXT CHECK (sex IN ('female', 'male', 'other', 'unknown')),
  phone TEXT,
  email TEXT,
  blood_type TEXT,
  address TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- PATIENT ALLERGIES
CREATE TABLE patient_allergies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id) ON DELETE CASCADE,
  substance TEXT NOT NULL,
  reaction TEXT,
  severity TEXT CHECK (severity IN ('low', 'moderate', 'high', 'unknown')),
  noted_at DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- PATIENT CONDITIONS
CREATE TABLE patient_conditions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  start_date DATE,
  end_date DATE,
  status TEXT CHECK (status IN ('active', 'resolved', 'unknown')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- APPOINTMENTS
CREATE TABLE appointments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id),
  doctor_id UUID REFERENCES doctors(id),
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  reason TEXT,
  status TEXT CHECK (status IN ('upcoming', 'confirmed', 'in_progress', 'done', 'cancelled', 'no_show')) DEFAULT 'upcoming',
  location TEXT,
  notes TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- CONSULTATIONS
CREATE TABLE consultations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  appointment_id UUID UNIQUE REFERENCES appointments(id),
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  state TEXT CHECK (state IN ('not_started', 'active', 'ended')) DEFAULT 'not_started',
  urgency_score INT CHECK (urgency_score BETWEEN 0 AND 10),
  detected_symptoms JSONB,
  safety_alerts JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- TRANSCRIPT MESSAGES
CREATE TABLE transcript_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consultation_id UUID REFERENCES consultations(id) ON DELETE CASCADE,
  sender_type TEXT CHECK (sender_type IN ('doctor', 'patient', 'ai')) NOT NULL,
  sender_id UUID,
  content TEXT NOT NULL,
  sent_at TIMESTAMPTZ DEFAULT now(),
  meta JSONB
);

-- AI SUMMARIES
CREATE TABLE ai_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  appointment_id UUID REFERENCES appointments(id),
  consultation_id UUID REFERENCES consultations(id),
  type TEXT CHECK (type IN ('phone_briefing', 'live_summary', 'final_report')) NOT NULL,
  summary_text TEXT,
  probable_diagnosis TEXT,
  recommendations JSONB,
  symptoms JSONB,
  urgency_score INT,
  model_info JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- CALL RECORDS
CREATE TABLE call_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id),
  doctor_id UUID REFERENCES doctors(id),
  appointment_id UUID REFERENCES appointments(id),
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  duration_seconds INT,
  reason TEXT,
  symptoms JSONB,
  summary TEXT,
  recommendations JSONB,
  evolution TEXT CHECK (evolution IN ('improvement', 'stable', 'worsening', 'unknown')),
  urgency_score INT,
  recording_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- PRESCRIPTIONS
CREATE TABLE prescriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  appointment_id UUID REFERENCES appointments(id),
  patient_id UUID REFERENCES patients(id),
  doctor_id UUID REFERENCES doctors(id),
  status TEXT CHECK (status IN ('draft', 'validated', 'sent', 'cancelled')) DEFAULT 'draft',
  issued_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- PRESCRIPTION ITEMS
CREATE TABLE prescription_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prescription_id UUID REFERENCES prescriptions(id) ON DELETE CASCADE,
  medication_name TEXT NOT NULL,
  dosage TEXT,
  frequency TEXT,
  duration TEXT,
  instructions TEXT,
  is_ai_suggested BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- NOTIFICATIONS
CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  type TEXT CHECK (type IN ('reminder', 'document', 'alert', 'system')) NOT NULL,
  title TEXT,
  message TEXT NOT NULL,
  related_entity_type TEXT,
  related_entity_id UUID,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- SMS MESSAGES
CREATE TABLE sms_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id),
  appointment_id UUID REFERENCES appointments(id),
  message_type TEXT CHECK (message_type IN ('booking_confirmation', 'reminder', 'prescription', 'followup')) NOT NULL,
  body TEXT NOT NULL,
  sent_at TIMESTAMPTZ DEFAULT now(),
  status TEXT CHECK (status IN ('sent', 'delivered', 'no_response', 'failed')) DEFAULT 'sent',
  responded_at TIMESTAMPTZ
);

-- FOLLOWUP TASKS
CREATE TABLE followup_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID REFERENCES patients(id),
  prescription_id UUID REFERENCES prescriptions(id),
  scheduled_at TIMESTAMPTZ NOT NULL,
  followup_type TEXT CHECK (followup_type IN ('sms', 'call')) NOT NULL,
  status TEXT CHECK (status IN ('pending', 'sent', 'completed', 'failed')) DEFAULT 'pending',
  attempt_number INT DEFAULT 1,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- INDEXES
CREATE INDEX idx_appointments_doctor_date ON appointments(doctor_id, starts_at);
CREATE INDEX idx_appointments_patient_date ON appointments(patient_id, starts_at);
CREATE INDEX idx_transcript_consultation_time ON transcript_messages(consultation_id, sent_at);
CREATE INDEX idx_call_records_patient_time ON call_records(patient_id, started_at);
CREATE INDEX idx_prescriptions_patient_time ON prescriptions(patient_id, issued_at);
CREATE INDEX idx_sms_patient ON sms_messages(patient_id, sent_at);
CREATE INDEX idx_followup_scheduled ON followup_tasks(scheduled_at, status);
