# MannerAI Meetings Platform

Meeting intelligence platform project: transcript processing and typed AI summaries, action items, decisions, follow-ups, with semantic search and analytics planned for later phases.

## Status

**Current status: Phase 9 — Redis, Celery, and durable job lifecycle COMPLETE.** PostgreSQL migration `0006_processing_jobs` is applied at Alembic head. The application job record owns lifecycle state, attempts, retry timing, sanitized failures, leases, and results; workers verify dedicated signed authorization before row-locked claims. PostgreSQL persistence, concurrent claims, expired-lease reclamation, stale-token fencing, and terminal-state persistence passed opt-in integration tests. Redis/Celery transport and worker integration are implemented, but live broker execution was not validated because Redis was unavailable in the development environment. No Celery result backend or exactly-once guarantee is provided. **Next: Phase 10 — Vector Search & RAG.** See the [AI processing architecture](docs/architecture/overview.md) and [current project foundation](docs/architecture/project-foundation.md).

**Development mode:** test in a Python virtual environment. Full Docker stack testing is deferred to the final phase.

## Stack

| Layer | Technologies |
|-------|----------------|
| Frontend | React, TypeScript, Vite, TailwindCSS |
| Backend | FastAPI (microservices) |
| Data | PostgreSQL for current domain persistence; Redis is the configured Celery broker; Qdrant remains future work |
| AI | Provider-neutral contracts and five agents; OpenAI adapter implemented; no public processing route |
| Workers | Phase 8 executor integrated with the Phase 9 Celery worker and signed identity boundary |
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
| gateway-service | 8000 | Authentication and public meeting/domain API routing |
| meeting-service | 8001 | Meeting, transcript, and domain-result APIs and persistence |
| ai-service | 8002 | Transcript-to-domain-input AI processing; no database persistence side effects |
| search-service | 8003 | Health probes; embeddings, retrieval, and vector search remain deferred |
| worker-service | 8004 | Health probes and Phase 9 Celery background job execution |

## Development

See [`docs/architecture/project-foundation.md`](docs/architecture/project-foundation.md) for the current implementation boundary, [`docs/engineering/problems-and-solutions.md`](docs/engineering/problems-and-solutions.md) for the engineering history, and [`docs/study/phase-3-study-guide.md`](docs/study/phase-3-study-guide.md) for Phase 3–5 study notes.

## License

TBD

