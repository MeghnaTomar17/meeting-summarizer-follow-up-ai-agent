# Architecture Overview

> MannerAI Meetings Platform — current architecture through Phase 5.

**Entry point:** For the consolidated current reference and Phase 5 checkpoint, see [project-foundation.md](./project-foundation.md).

## System context

The platform ingests meeting recordings and transcripts, runs AI pipelines for summaries and extractions, indexes content for semantic search, and exposes a React dashboard via an API gateway.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, transcripts, summaries, tasks, decisions, follow-up drafts |
| ai-service | Agents, LLM pipelines, prompts |
| search-service | Chunking, embeddings, Qdrant retrieval |
| worker-service | Async jobs (Celery) |

## Data stores

- **PostgreSQL** — users, refresh sessions, meetings, transcripts, and meeting results
- **Redis** — cache, sessions, Celery broker
- **Qdrant** — vector index for transcript chunks

## Persistence layer

- **SQLAlchemy 2.0 async** + **asyncpg** for PostgreSQL access
- **Alembic** for schema migrations (see `database/postgresql/migrations.md`)
- **Pydantic schemas** in `backend/shared/schemas/` for shared API/domain DTOs
- **SQLAlchemy ORM models** in `backend/shared/database/models/` for users, refresh sessions, meetings, transcripts, summaries, tasks, decisions, and follow-ups

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
- gateway-service owns user and refresh-session persistence; meeting-service owns meeting, transcript, and result persistence

## Public authentication boundary

Gateway routes under `/api/v1/auth` handle signup, login, refresh, logout, and
the authenticated user's profile. `get_current_user()` validates the external
access JWT, checks its type and UUID subject, then loads the user. The access
JWT carries `sub`, `type=access`, `iat`, and `exp`; invalid credentials produce
a generic authentication failure.

Login and refresh return an access JWT plus an opaque refresh token. The refresh
token is random, stored only as a SHA-256 hash, and independently associated
with its login session. Refresh rotates the token while locking the current
PostgreSQL session row. Logout revokes only the supplied session.

## Gateway → Meeting identity boundary

```text
Client access JWT → Gateway validation/user lookup
                  → Gateway signs short-lived RS256 internal principal
                  → Meeting verifies with public key
                  → authenticated user UUID reaches MeetingService
```

The internal principal includes `sub`, `type=internal_principal`, `iss`, `aud`,
`iat`, and `exp`. Gateway alone receives the signing private key; Meeting
receives the verification public key. Meeting does not trust caller-supplied
identity fields or validate the external access JWT directly.

## Meeting persistence and ownership boundary

Phase 3.1–3.4 implemented the internal meeting persistence and route path:

```
POST /meetings or GET /meetings/{meeting_id}
  ↓
MeetingService
  ↓
MeetingRepository / TranscriptRepository
  ↓
AsyncSession
  ↓
PostgreSQL
```

Gateway meeting endpoints authenticate the user and derive identity from the
validated user row. The Gateway client signs an internal principal for each
downstream request. `MeetingService` persists that identity as `created_by` and
checks ownership before reading or changing an individual meeting or its
transcript. Client-provided ownership fields are not accepted as authority.
Repositories perform persistence only; the service owns successful commits and
the session dependency rolls back on escaping exceptions.

The Phase 5 result endpoints are nested under their owning meeting and use the
same authenticated Gateway-to-Meeting identity flow. The internal
`GET /meetings?organization_id=...` listing still has no organization
membership authorization and remains internal-only. A public Meeting list
requires persisted organization membership and an authorization policy.

For the detailed, current reference see [project-foundation.md](./project-foundation.md).

## Remaining work

- Sequence diagrams for upload → process → index flow
- Organization membership and authorization for organization-wide listing
- AI, semantic search, worker, and frontend integration (Phase 6 onward; not started)
