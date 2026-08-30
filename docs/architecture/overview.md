# Architecture Overview

> MannerAI Meetings Platform — scaffolding documentation.

**Entry point:** For the consolidated foundation reference covering Phases 2.1–2.5, see [project-foundation.md](./project-foundation.md).

## System context

The platform ingests meeting recordings and transcripts, runs AI pipelines for summaries and extractions, indexes content for semantic search, and exposes a React dashboard via an API gateway.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, uploads, transcripts, audio processing |
| ai-service | Agents, LLM pipelines, prompts |
| search-service | Chunking, embeddings, Qdrant retrieval |
| worker-service | Async jobs (Celery) |

## Data stores

- **PostgreSQL** — relational transactional data (users, meetings, AI artifacts)
- **Redis** — cache, sessions, Celery broker
- **Qdrant** — vector index for transcript chunks

## Persistence layer

- **SQLAlchemy 2.0 async** + **asyncpg** for PostgreSQL access
- **Alembic** for schema migrations (see `database/postgresql/migrations.md`)
- **Pydantic schemas** in `backend/shared/schemas/` for shared API/domain DTOs
- **SQLAlchemy ORM models** in `backend/shared/database/models/` (TODO)

## Logging

- Centralized logging in `backend/shared/utils/` (see `docs/architecture/logging.md`)
- Development/testing: human-readable logs
- Production: JSON structured logs
- Request correlation via `X-Request-ID`

## Exception handling

- Standardized error envelope in `backend/shared/exceptions/` (see `docs/architecture/exceptions.md`)
- Shared FastAPI exception handlers registered via service bootstrap
- Safe client-facing errors; tracebacks logged server-side only

## API design

- Public API versioned at `/api/v1` on the gateway (see `docs/architecture/api-design.md`)
- Internal services use unversioned routes
- Pagination, naming, and response conventions documented in Phase 2.4

## Database

- Async SQLAlchemy 2.x + asyncpg (see `docs/architecture/database.md`)
- Shared infrastructure in `backend/shared/database/`
- Alembic migrations at `backend/migrations/`
- meeting-service owns PostgreSQL connectivity in Phase 2.5

## TODO

- Sequence diagrams for upload → process → index flow
- Security boundary (internal vs public APIs)
- Multi-tenancy model
