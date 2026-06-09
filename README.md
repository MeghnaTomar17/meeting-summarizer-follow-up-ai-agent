# MannerAI Meetings Platform

AI-powered meeting intelligence: transcripts, summaries, action items, decisions, follow-ups, semantic search, and analytics.

## Status

Repository scaffolding only — business logic and AI features are not implemented.

## Stack

| Layer | Technologies |
|-------|----------------|
| Frontend | React, TypeScript, Vite, TailwindCSS |
| Backend | FastAPI (microservices) |
| Data | PostgreSQL, Redis, Qdrant |
| AI | OpenAI, Gemini |
| Workers | Celery, Redis Queue |
| Ops | Docker, Docker Compose, Nginx |

## Structure

```
ai-meetings-platform/
├── frontend/          # React dashboard
├── backend/           # gateway, meeting, ai, search, worker, shared
├── database/          # PostgreSQL schema docs, Qdrant collections
├── infrastructure/    # Dockerfiles, nginx
└── docs/              # architecture, API, database
```

## Quick start (placeholder)

```bash
cp .env.example .env
docker compose up --build
```

## Services

| Service | Port (default) | Responsibility |
|---------|----------------|----------------|
| gateway-service | 8000 | Auth, routing, validation, analytics & integration APIs |
| meeting-service | 8001 | Meetings CRUD, uploads, transcripts, audio processing |
| ai-service | 8002 | Agents, pipelines, LLM clients |
| search-service | 8003 | Embeddings, semantic retrieval, vector search |
| worker-service | — | Celery/RQ background jobs |

## Development

See `docs/architecture/` for system design (to be expanded).

## License

TBD
