# MedVoice Care Connect

MedVoice Care Connect is a full-stack voice-clinic workflow app with:

- a FastAPI backend
- a React frontend dashboard
- LiveKit voice agents for consultation and outbound follow-up calls
- optional persistence to PostgreSQL/Supabase
- optional prescription email delivery via Resend

## What This Project Covers

The product lifecycle implemented in this repo:

1. Patient call and appointment intake
2. Day-before confirmation
3. Live consultation with transcript streaming
4. AI summary + prescription generation
5. Prescription send via email
6. Post-consultation outbound follow-up call

## Architecture

Services started by Docker Compose:

- `backend`: FastAPI API (`http://localhost:8000`)
- `frontend`: React app served by Nginx (`http://localhost:8080`)
- `telephony-agent`: live telephony/voice workflow agent
- `consultation-agent`: live consultation agent
- `outbound-caller`: post-consultation follow-up caller agent

Main files:

- Backend API entrypoint: `backend/app/main.py`
- Core logic: `backend/app/service.py`
- Resend email integration: `backend/app/integrations/resend_onefile.py`
- Twilio SMS integration: `backend/app/integrations/twilio_client.py`
- Compose stack: `docker-compose.yml`

## Quick Start (Recommended)

1. Prepare environment variables:

```bash
cp backend/.env.example backend/.env
```

Windows PowerShell equivalent:

```powershell
Copy-Item backend/.env.example backend/.env
```

2. Fill required keys in `backend/.env`:

- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `SPEECHMATICS_API_KEY`

Optional but commonly used:

- `DATABASE_URL` for persistence
- `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_TO` for prescription email
- `TWILIO_*` for SMS confirmation

3. Start everything:

```bash
docker compose up --build
```

Important: use `--build` (double dash), not `-build`.

4. Open:

- Frontend: `http://localhost:8080`
- Backend health check: `http://localhost:8000/api/health`

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

## Testing

Backend tests:

```bash
cd backend
pytest -q
```

Frontend tests:

```bash
cd frontend
npm test
```

## Troubleshooting

### Twilio error: "Mismatch between the 'From' number and the account"

`TWILIO_FROM_NUMBER` must belong to the same `TWILIO_ACCOUNT_SID` account.

If you use a Messaging Service, set `TWILIO_MESSAGING_SERVICE_SID` and ensure it is in the same account.

### Resend test mode limitation

With `onboarding@resend.dev` and no verified domain, Resend usually only allows sending to the account owner/verified test recipient.

### Follow-up warnings in logs

Warnings like deprecated LiveKit options or first-time VAD model download are non-fatal and do not necessarily indicate API failure.

## Mock Data

SQL mock files are available in:

- `backend/db/mock_all_tables_4.sql`
- `backend/db/mock_4_patients.sql`

Use them to seed demo records quickly in your database.
