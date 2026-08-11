# MannerAI Meetings Platform

AI-powered meeting intelligence: transcripts, summaries, action items, decisions, follow-ups, semantic search, and analytics.

## Status

**Phase 1 complete** — Docker Compose stack, health checks, and service containers are wired. Business logic and AI features are not implemented yet.

**Development mode:** test in a Python virtual environment. Full Docker stack testing is deferred to the final phase.

## Stack

| Layer | Technologies |
|-------|----------------|
| Frontend | React, TypeScript, Vite, TailwindCSS |
| Backend | FastAPI (microservices) |
| Data | PostgreSQL, Redis, Qdrant |
| AI | OpenAI, Gemini |
| Workers | Celery, Redis |
| Ops | Docker, Docker Compose, Nginx |

## Structure

```
meeting-summarizer-follow-up-ai-agent/
├── frontend/          # React dashboard
├── backend/           # gateway, meeting, ai, search, worker, shared
├── scripts/           # setup and local run helpers
├── database/          # PostgreSQL schema docs, Qdrant collections
├── infrastructure/    # Dockerfiles, nginx
└── docs/              # architecture, API, database
```

## Clone on a new device

```bash
git clone https://github.com/MeghnaTomar17/meeting-summarizer-follow-up-ai-agent.git
cd meeting-summarizer-follow-up-ai-agent
```

**Windows**

```powershell
.\scripts\setup.ps1
.\scripts\start-infra.ps1          # optional: Postgres, Redis, Qdrant via Docker
.\scripts\run-service.ps1 gateway  # start gateway on :8000
```

**macOS / Linux**

```bash
chmod +x scripts/*.sh
./scripts/setup.sh
./scripts/start-infra.sh           # optional: Postgres, Redis, Qdrant via Docker
./scripts/run-service.sh gateway   # start gateway on :8000
```

Then verify:

```bash
curl http://localhost:8000/health
```

### What gets committed vs ignored

| Committed | Not committed (local only) |
|-----------|----------------------------|
| Source code, Dockerfiles, `.env.example` | `.env` (secrets) |
| Pinned `requirements.txt` | `.venv/` |
| Setup scripts | `node_modules/`, build artifacts |

Copy `.env.example` → `.env` on each machine. Never commit `.env`.

## Local development (venv)

1. **Setup once:** `scripts/setup.ps1` or `scripts/setup.sh`
2. **Data stores (optional):** `scripts/start-infra.ps1` — runs only Postgres, Redis, Qdrant in Docker
3. **Run a service:** `scripts/run-service.ps1 gateway|meeting|ai|search|worker`

`.env.example` uses `localhost` URLs for venv development. Docker Compose overrides service URLs when running the full stack.

## Docker (full stack — test at end)

```bash
cp .env.example .env
docker compose up --build
```

Verify services:

```bash
curl http://localhost:8000/health          # gateway
curl http://localhost:8001/health          # meeting-service
curl http://localhost:8002/health          # ai-service
curl http://localhost:8003/health          # search-service
curl http://localhost:8004/health          # worker-service
curl http://localhost/health               # nginx → gateway
```

## Health endpoints

Each service exposes:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness (used by Docker) |
| `GET /health/live` | Explicit liveness probe |
| `GET /health/ready` | Readiness (dependency checks in Phase 2) |

## Services

| Service | Port (default) | Responsibility |
|---------|----------------|----------------|
| gateway-service | 8000 | Auth, routing, validation, analytics & integration APIs |
| meeting-service | 8001 | Meetings CRUD, uploads, transcripts, audio processing |
| ai-service | 8002 | Agents, pipelines, LLM clients |
| search-service | 8003 | Embeddings, semantic retrieval, vector search |
| worker-service | 8004 | Celery background jobs (HTTP health in Phase 1; worker process in Phase 7) |

## Development

See `docs/architecture/` for system design (to be expanded).

## License

TBD

