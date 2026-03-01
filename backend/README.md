## MedVoice Care Connect Backend

Backend API et agent voix LiveKit pour le cycle patient:

1. Appel patient
2. Confirmation J-1
3. Consultation live
4. Fin consultation + ordonnance
5. Suivi post-consultation

### Démarrage complet avec Docker Compose (recommandé)

Depuis la racine du repo (`HacKMed/`):

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Services lancés:

- Backend API: `http://localhost:8000`
- Frontend: `http://localhost:8080`
- Agent voix (`agents/telephony_agent.py`) dans le service `telephony-agent`

Voir les logs de conversation (caller + assistant):

```bash
docker compose logs -f telephony-agent
```

Exemple de ligne de transcript:

```text
[TRANSCRIPT][USER][interrupted=False] Bonjour docteur
```

### Démarrage API

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Démarrage Agent LiveKit

```bash
python agents/telephony_agent.py dev
```

### Variables d'environnement requises

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=xxxx
LIVEKIT_API_SECRET=xxxx
OPENAI_API_KEY=xxxx
SPEECHMATICS_API_KEY=xxxx

BACKEND_API_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/medvoice
DEFAULT_DOCTOR_ID=<optional-doctor-uuid-from-doctors-table>

CALCOM_API_KEY=xxxx
CALCOM_BASE_URL=https://api.cal.com/v2
CALCOM_EVENT_TYPE_ID=123456
CALCOM_TIMEZONE=Europe/Paris

# Optional (Twilio disabled in current POC)
# TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
# TWILIO_AUTH_TOKEN=xxxx
# TWILIO_FROM_NUMBER=+1XXXXXXXXXX
```

### Endpoint booking + SMS confirmation

`POST /api/booking/calcom`

```json
{
  "patientId": "pat-1",
  "patientName": "Marie Dupont",
  "patientPhone": "+33612345678",
  "patientEmail": "marie@example.com",
  "reason": "Douleur gorge",
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

### Supabase (POC)

In Supabase SQL editor, run:

1. `backend/db/schema.sql`
2. `backend/db/supabase_poc_seed.sql`

This seeds one doctor only (`Dr. Laurent Martin`) and demo patient data.
