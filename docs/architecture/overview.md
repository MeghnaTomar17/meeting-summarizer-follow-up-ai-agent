# Architecture Overview

> MannerAI Meetings Platform — current architecture through Phase 3.3.

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
- **SQLAlchemy ORM models** in `backend/shared/database/models/` for meetings and transcripts

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
- meeting-service owns PostgreSQL connectivity and the current meeting/transcript persistence use cases

## Current meeting persistence boundary

Phase 3.1–3.3 implemented the internal persistence path:

```
Route (not wired yet)
  ↓
MeetingService
  ↓
MeetingRepository / TranscriptRepository
  ↓
AsyncSession
  ↓
PostgreSQL
```

`MeetingService` maps Pydantic DTOs to ORM entities, coordinates multi-step
use cases, and commits successful writes. Repositories use SQLAlchemy 2.0 async
queries, add/flush entities, and return ORM entities; they do not commit,
rollback, or return API DTOs. The FastAPI session dependency rolls back when an
exception propagates. The meeting and transcript routers are still scaffolded
and are not mounted, so this is not yet an HTTP API implementation.

For the detailed, current reference see [project-foundation.md](./project-foundation.md).

## TODO

- Sequence diagrams for upload → process → index flow
- Security boundary (internal vs public APIs)
- Multi-tenancy model
