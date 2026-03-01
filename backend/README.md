## MedVoice Care Connect Backend

Backend API and LiveKit voice agents for the patient lifecycle:

1. Patient call
2. Day-before confirmation
3. Consultation live
4. Consultation end + prescription
5. Post-consultation follow-up

### Full startup with Docker Compose (recommended)

From the repository root (`HacKMed/`):

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Started services:

- Backend API: `http://localhost:8000`
- Frontend: `http://localhost:8080`
- Voice agent (`agents/telephony_agent.py`) in the `telephony-agent` service
- Consultation agent (`agents/consultation_agent.py`) in the `consultation-agent` service

View conversation logs (caller + assistant):

```bash
docker compose logs -f telephony-agent
docker compose logs -f consultation-agent
```

Example transcript line:

```text
[TRANSCRIPT][USER][interrupted=False] Hello doctor
```

### Start API

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Start LiveKit Agent

```bash
python agents/telephony_agent.py dev
```

### Required environment variables

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=xxxx
LIVEKIT_API_SECRET=xxxx
CONSULTATION_AGENT_NAME=medvoice-consultation
CONSULTATION_AUTO_DISPATCH=true
LIVEKIT_OUTBOUND_AGENT_NAME=outbound-caller
SIP_OUTBOUND_TRUNK_ID=<your-livekit-sip-outbound-trunk-id>
FOLLOWUP_TEST_PHONE=0784221830
OUTBOUND_CALL_LANGUAGE=en
OPENAI_API_KEY=xxxx
SPEECHMATICS_API_KEY=xxxx
TTS_PROVIDER=speechmatics
SPEECHMATICS_VOICE=megan
SPEECHMATICS_TTS_REQUIRED=true
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=ash
OPENAI_TTS_SPEED=1.0
STT_LANGUAGE=en
STT_DOMAIN=medical
STT_OPERATING_POINT=enhanced
STT_MAX_DELAY=0.65
STT_EOU_SILENCE=0.30
OUTBOUND_STT_DOMAIN=medical
OUTBOUND_STT_OPERATING_POINT=enhanced
OUTBOUND_STT_MAX_DELAY=0.65
OUTBOUND_EOU_SILENCE=0.30
CONSULTATION_STT_DOMAIN=medical
CONSULTATION_STT_OPERATING_POINT=enhanced
CONSULTATION_STT_MAX_DELAY=0.9
CONSULTATION_ENABLE_DIARIZATION=false
CONSULTATION_INCLUDE_PARTIALS=false
CONSULTATION_DIARIZATION_SENSITIVITY=0.75
CONSULTATION_EOU_SILENCE_TRIGGER=0.55
CONSULTATION_PREFER_CURRENT_SPEAKER=true
CONSULTATION_AUTO_DIARIZE_SINGLE_PARTICIPANT=true
CONSULTATION_INCLUDE_OTHER_SPEAKER=true
CONSULTATION_MIN_TEXT_CHARS=5
CONSULTATION_SINGLE_TAG_ROLE_HEURISTIC=true
CONSULTATION_SINGLE_TAG_OVERRIDE_DELTA=4
CONSULTATION_MERGE_WINDOW_SECONDS=1.2
CONSULTATION_MERGE_SHORT_CHARS=28
CONSULTATION_MERGE_MAX_CHARS=260
CONSULTATION_FINALIZE_GRACE_SECONDS=1.0
CONSULTATION_LLM_ADJUDICATION_ENABLED=true
CONSULTATION_LLM_ADJUDICATION_MODEL=gpt-4o-mini
CONSULTATION_LLM_ADJUDICATION_MIN_TURNS=4
CONSULTATION_LLM_ADJUDICATION_CHUNK_TURNS=40
CONSULTATION_LLM_ADJUDICATION_CHUNK_MAX_CHARS=20000
CONSULTATION_FINAL_TRANSCRIPT_MAX_CHARS=0
TELEPHONY_WELCOME_MESSAGE=Hello, welcome to MedVoice Care Connect. I can help schedule your consultation today. Are you already a patient with us, or is this your first visit?

BACKEND_API_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/medvoice
DEFAULT_DOCTOR_ID=<optional-doctor-uuid-from-doctors-table>

CALCOM_API_KEY=xxxx
CALCOM_BASE_URL=https://api.cal.com/v2
CALCOM_EVENT_TYPE_ID=123456
CALCOM_TIMEZONE=Europe/Paris

TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
# Optional alternative to TWILIO_FROM_NUMBER:
# TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxx
```

### Booking + SMS confirmation endpoint

`POST /api/booking/calcom`

```json
{
  "patientId": "pat-1",
  "patientName": "Marie Dupont",
  "patientPhone": "+33612345678",
  "patientEmail": "marie@example.com",
  "reason": "Sore throat",
  "startsAt": "2026-03-01T09:00:00+01:00",
  "timezone": "Europe/Paris",
  "symptoms": ["sore throat", "fever"],
  "conditions": ["asthma"],
  "allergies": ["penicillin"],
  "conversationSummary": "Patient reports sore throat for 3 days with fever and no chest pain."
}
```

When `DATABASE_URL` is set, booking confirmation now persists:

- `patients`
- `patient_conditions`
- `patient_allergies`
- `appointments`
- `consultations`
- `transcript_messages` (if transcript is provided)
- `call_records`
- `sms_messages`
- `ai_summaries` (if summary is provided)

For telephony calls, transcript lines captured by the agent are automatically attached to booking confirmation and persisted to `transcript_messages`.

### Outbound follow-up call endpoint

`POST /api/reminder/followup-call`

```json
{
  "appointmentId": "55841ae8-b82e-4425-9f62-f978fc52634d",
  "patientId": "+33765540003",
  "patientName": "Jacob Doe",
  "patientPhone": "0784221830",
  "doctorName": "Dr. Laurent Martin"
}
```

Behavior:

- Schedules a follow-up call task in `followup_tasks`
- Dispatches LiveKit agent `outbound-caller` with patient context + prescription + history
- On call completion, inserts a record in `call_records` and updates follow-up status

### Supabase (POC)

In Supabase SQL editor, run:

1. `backend/db/schema.sql`
2. `backend/db/supabase_poc_seed.sql`

This seeds one doctor only (`Dr. Laurent Martin`) and demo patient data.
