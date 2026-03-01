# MedVoice Care Connect

This repository now includes Docker + Docker Compose for one-command startup of:

- `backend` (FastAPI API on port `8000`)
- `telephony-agent` (`backend/agents/telephony_agent.py`)
- `frontend` (Nginx serving React app on port `8080`)

## Run everything with one command

1. Create your env file for backend + agent:

```bash
cp backend/.env.example backend/.env
```

If you want appointment/call/patient records persisted to your SQL schema, set `DATABASE_URL` in `backend/.env`.

2. Start the full stack:

```bash
docker compose up --build
```

Then open:

- Frontend: `http://localhost:8080`
- Backend health: `http://localhost:8000/api/health`

## Useful commands

```bash
# Run in background
docker compose up --build -d

# Stop everything
docker compose down

# Stream only telephony agent logs
docker compose logs -f telephony-agent
```

When a call is active, the agent container prints committed transcript lines in this format:

```text
[TRANSCRIPT][USER][interrupted=False] ...
[TRANSCRIPT][ASSISTANT][interrupted=False] ...
```
