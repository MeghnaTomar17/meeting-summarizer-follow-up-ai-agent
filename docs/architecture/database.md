# Database Architecture

> MannerAI Meetings Platform — PostgreSQL persistence and initial domain schema.

## Stack

```
FastAPI
  ↓
SQLAlchemy 2.x async (AsyncSession)
  ↓
asyncpg
  ↓
PostgreSQL
```

## Ownership

| Component | Location |
|-----------|----------|
| Declarative Base | `backend/shared/database/base.py` |
| UUID/timestamp mixins | `backend/shared/database/mixins.py` |
| Async engine | `backend/shared/database/engine.py` |
| Session factory + dependency | `backend/shared/database/session.py` |
| Connectivity helper | `backend/shared/database/health.py` |
| ORM models | `backend/shared/database/models/` |
| Alembic migrations | `backend/migrations/` |
| Pydantic API schemas | `backend/shared/schemas/` (separate layer) |

**Phase 2.5:** only `meeting-service` initializes PostgreSQL. Other services do not connect yet.

## Engine vs session

| Object | Scope | Purpose |
|--------|-------|---------|
| `AsyncEngine` | Process-wide singleton | Connection pooling |
| `async_sessionmaker` | Process-wide singleton | Creates sessions |
| `AsyncSession` | Request/task scoped | Unit of work for queries |

The engine is created during application lifespan startup and disposed on shutdown.

## Transaction boundaries

```
Route → Service → Repository → AsyncSession → commit/rollback
```

- `get_db_session()` yields a session but does **not** auto-commit.
- Repositories execute queries; the service layer owns transaction boundaries.
- On exception, the session dependency rolls back before re-raising.

`flush` and `commit` are intentionally separate. A repository flushes pending
SQL so generated values and constraint errors are available inside the current
transaction. `MeetingService` commits only after its full successful use case;
reads never commit. Repositories do not rollback, because the dependency owns
that exception path.

## Implemented Phase 3 domain schema

Revision `0001_meetings_transcripts` (file:
`backend/migrations/versions/0001_create_meetings_and_transcripts.py`) is the
initial applied domain schema. It creates:

- native `meeting_status` values, in order: `pending`, `processing`, `ready`, `failed`;
- `meetings`, including required UUID ownership fields, `JSONB` participants,
  timezone-aware timestamps, and a lowercase status server default;
- `transcripts`, including unique `meeting_id`, `JSONB` segments, nullable
  language, and a foreign key to `meetings.id` with `ON DELETE CASCADE`;
- `ix_meetings_organization_id`, `ix_meetings_created_by`, and unique
  `ix_transcripts_meeting_id`.

The ORM uses `values_callable` so SQLAlchemy persists enum values (`pending`)
instead of Python member names (`PENDING`). `Meeting.transcript` is a one-to-one
relationship (`uselist=False`) and uses `delete-orphan` for aggregate ownership.
`organization_id` and `created_by` are UUID fields, **not foreign keys**: no
organization/user ORM tables exist yet.

## Implemented data-access and use-case boundaries

`MeetingRepository` and `TranscriptRepository` receive an `AsyncSession`, use
SQLAlchemy 2.0 `select`/`execute`, return ORM entities, and add/flush writes.
They do not emit DTOs, make business decisions, commit, or rollback.

`MeetingService` receives the session and repositories. It converts string UUIDs
to `uuid.UUID`, converts the distinct Pydantic and ORM status enums by value,
serializes transcript segments with `model_dump()`, raises application errors,
maps entities back to DTOs, and commits successful writes. It implements
creation, lookup, organization listing, status updates, transcript creation,
lookup, and replacement. Phase 3.4 wires its create/get meeting use cases to
internal meeting-service routes; the service remains independent of FastAPI.

## Internal route composition (Phase 3.4)

The mounted meeting-service router exposes internal `POST /meetings` and
`GET /meetings/{meeting_id}`. It is not the future gateway `/api/v1/meetings`
API: authentication, gateway forwarding, and `MeetingServiceClient` are not
implemented. Building the internal route slice first validates the service
architecture independently rather than presenting an unauthenticated route as a
final public contract.

```
HTTP request
  ↓
FastAPI route
  ↓
Depends(get_meeting_service)
  ↓
Depends(get_db_session)
  ↓
request-scoped AsyncSession
  ↓
MeetingRepository + TranscriptRepository
  ↓
MeetingService
  ↓
repository method → AsyncSession → PostgreSQL
```

`get_meeting_service` constructs the repositories and `MeetingService` once per
request from the injected session. This avoids duplicating composition in every
endpoint while keeping routes free of SQL and transaction handling.
`get_db_session()` obtains a session from the shared factory, yields it for the
request, and rolls it back only if an exception propagates. On success it does
not auto-commit: `MeetingService` remains the successful-write commit boundary,
while reads do not commit.

Routes accept validated Pydantic input and delegate: POST calls
`MeetingService.create_meeting()` and returns `MeetingPublic` with HTTP 201;
GET passes its string path parameter to `MeetingService.get_meeting()` and
returns `MeetingPublic` with HTTP 200. Routes do not construct ORM models,
convert UUIDs, execute SQL, commit, rollback, impose business rules, or catch
and manually translate `AppError` instances. Existing handlers convert missing
meetings to a 404 `ErrorResponse`, invalid UUIDs to 422, and unexpected errors
to a safe 500; request IDs remain included.

Transcript creation requires an existing meeting and rejects an existing
transcript with `ConflictError`; replacement requires an existing transcript and
does not create one. No status-transition graph or PostgreSQL upsert has been
introduced because neither behavior is established.

### Deferred alignment

The database/ORM permits `Transcript.language = NULL`, while `TranscriptInDB`
requires a non-null string. The service maps stored `NULL` to `"en"`; this keeps
the DTO valid but is not lossless. Future work must choose either a nullable DTO
or a non-null database column/default. ORM and Pydantic `MeetingStatus` remain
separate definitions with explicit `.value` mapping.

## Configuration

From `SharedSettings` (Phase 2.1):

| Setting | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async connection URL |
| `DATABASE_POOL_SIZE` | `10` | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | `10` | Extra connections beyond pool |
| `DATABASE_POOL_TIMEOUT` | `30` | Seconds to wait for a connection |
| `DATABASE_POOL_RECYCLE` | `1800` | Recycle connections after seconds |
| `DATABASE_ECHO` | `false` | SQLAlchemy echo (dev only) |

Credentials come from `.env` — never logged.

## Health vs readiness

| Endpoint | PostgreSQL check? |
|----------|-------------------|
| `/health` | No |
| `/health/live` | No — process liveness only |
| `/health/ready` | Yes — `SELECT 1` on meeting-service only |

When PostgreSQL is unavailable, meeting-service `/health/ready` returns HTTP 503 with the standardized error envelope.

## Alembic workflow

See [`database/postgresql/migrations.md`](../../database/postgresql/migrations.md).

Run from repository root:

```bash
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
```

## Local PostgreSQL setup

1. Install PostgreSQL 16+ locally.
2. Create the database:

```sql
CREATE DATABASE mannerai_meetings;
```

3. Copy `.env.example` → `.env` and set `DATABASE_URL` with your local credentials.
4. Start meeting-service and verify `/health/ready`.

## Security

- `DATABASE_URL` is in the logging sensitive-field denylist.
- Readiness failures return safe messages — no raw PostgreSQL errors to clients.
- ORM models must not be exposed as API `response_model` — use Pydantic `*Public` schemas.

## ORM model conventions

- UUID primary keys via `UUIDPrimaryKeyMixin`
- Timestamps via `TimestampMixin` (`TIMESTAMPTZ`)
- Business models imported in `shared/database/models/__init__.py` for Alembic discovery
