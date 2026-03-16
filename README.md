# MedVoice Care Connect

MedVoice Care Connect is a full-stack voice clinic workflow app for:

1. Patient call intake
2. Appointment booking
3. Live consultation with transcript streaming
4. AI summary and prescription generation
5. Prescription delivery by email
6. Post-consultation outbound follow-up call

## Stack

### App stack

- Backend API: FastAPI + Pydantic
- Frontend dashboard: React + Vite + TypeScript + Tailwind
- Voice agents: LiveKit Agents
- LLM/TTS: OpenAI
- Medical STT/TTS: Speechmatics

### External integrations

- Database and persistence: PostgreSQL or Supabase via `DATABASE_URL`
- Telephony and SMS: Twilio
- Prescription email: Resend
- Appointment scheduling: Cal.com
- Realtime rooms and SIP calling: LiveKit

### Local runtime

- Container orchestration: Docker Compose
- Reverse-served frontend: Nginx in the frontend image

## Docker Architecture

`docker compose up --build` starts the local application containers:

- `backend`: FastAPI API on `http://localhost:8000`
- `frontend`: React app served on `http://localhost:8080`
- `telephony-agent`: inbound/call intake agent
- `consultation-agent`: live consultation agent
- `outbound-caller`: follow-up call agent

Important:

- Docker Compose does not start Supabase, Twilio, LiveKit, Resend, or Cal.com locally
- those services are external and are configured through `backend/.env`
- persistence works with any PostgreSQL-compatible `DATABASE_URL`, including Supabase

## Repository Map

- API entrypoint: `backend/app/main.py`
- Core orchestration: `backend/app/service.py`
- Telephony agent: `backend/agents/telephony_agent.py`
- Consultation agent: `backend/agents/consultation_agent.py`
- Outbound caller: `backend/agents/outbound_caller.py`
- Twilio integration: `backend/app/integrations/twilio_client.py`
- Resend integration: `backend/app/integrations/resend_onefile.py`
- SQL schema: `backend/db/schema.sql`
- Compose stack: `docker-compose.yml`

## Quick Start

1. Create the backend env file.

```bash
cp backend/.env.example backend/.env
```

Windows PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
```

2. Fill the required provider keys in `backend/.env`.

Required for the voice stack:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `SPEECHMATICS_API_KEY`

Common optional integrations:

- `DATABASE_URL` for PostgreSQL or Supabase persistence
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` for SMS
- `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_TO` for email delivery
- `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID` for live booking
- `SIP_OUTBOUND_TRUNK_ID` for outbound LiveKit SIP calls

3. Start the stack.

```bash
docker compose up --build
```

4. Open the app.

- Frontend: `http://localhost:8080`
- API health: `http://localhost:8000/api/health`

## Supabase / PostgreSQL

Persistence is optional but recommended for realistic usage.

- Set `DATABASE_URL` to your PostgreSQL or Supabase Postgres connection string
- apply the schema from `backend/db/schema.sql`
- for demo data, use `backend/db/supabase_poc_seed.sql`

Additional mock SQL files:

- `backend/db/mock_all_tables_4.sql`
- `backend/db/mock_4_patients.sql`

## Twilio / Resend / Cal.com / LiveKit

### Twilio

Used for SMS confirmations and reminder messages.

- configure `TWILIO_ACCOUNT_SID`
- configure `TWILIO_AUTH_TOKEN`
- configure `TWILIO_FROM_NUMBER`
- or use `TWILIO_MESSAGING_SERVICE_SID`

### Resend

Used to send prescription emails.

- configure `RESEND_API_KEY`
- configure `RESEND_FROM_EMAIL`
- optionally set `RESEND_REPLY_TO`
- optionally force delivery to a safe inbox with `RESEND_TO`

### Cal.com

Used for booking and availability lookup.

- configure `CALCOM_API_KEY`
- configure `CALCOM_EVENT_TYPE_ID`
- optionally set `CALCOM_BASE_URL` and `CALCOM_API_VERSION`

### LiveKit

Used for realtime consultation rooms and SIP-based outbound calls.

- configure `LIVEKIT_URL`
- configure `LIVEKIT_API_KEY`
- configure `LIVEKIT_API_SECRET`
- configure `SIP_OUTBOUND_TRUNK_ID` for real outbound phone calls

## Local Development Without Docker

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Key Endpoints

- `POST /api/lifecycle/consultation/start`
- `POST /api/lifecycle/consultation/transcript`
- `POST /api/lifecycle/consultation/end`
- `POST /api/consultation/summary`
- `POST /api/consultation/suggest-questions`
- `POST /api/prescription/send`
- `POST /api/reminder/followup-call`
- `POST /api/booking/calcom`
- `GET /api/dashboard/appointments`

## Troubleshooting

### Twilio "From number" mismatch

`TWILIO_FROM_NUMBER` must belong to the same Twilio account as `TWILIO_ACCOUNT_SID`.

If you use a Messaging Service, make sure `TWILIO_MESSAGING_SERVICE_SID` belongs to that same account.

### Resend test mode limitation

With `onboarding@resend.dev` and no verified domain, Resend generally allows only limited test delivery.

### Follow-up agent warnings

First-time model downloads, deprecated SDK notices, or non-fatal LiveKit warnings do not automatically mean the workflow failed.
