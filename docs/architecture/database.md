# Database Architecture

> MannerAI Meetings Platform — PostgreSQL persistence boundary and schema definitions through Phase 7.

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

**Current ownership:** gateway-service initializes PostgreSQL for users and
refresh sessions; meeting-service initializes it for meetings, transcripts,
summaries, tasks, decisions, and follow-ups. MeetingInsight ORM/schema and
repository support are defined in Meeting Service, but its migration is
unapplied and its table is not assumed to exist in the current database. Both
services use the shared async engine/session infrastructure and canonical
Alembic schema for applied migrations.

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
- Repositories execute queries; application services own transaction boundaries.
- On exception, the session dependency rolls back before re-raising.

`flush` and `commit` are intentionally separate. Repositories flush pending SQL
so generated values and constraint errors are available inside the current
transaction. Authentication, user, meeting, and meeting-result services commit successful
writes only after their use case; repositories do not commit or rollback. The
request-scoped dependency rolls back when an exception escapes.

## Phase 4 identity and refresh-session schema

The migration chain is `0001_meetings_transcripts` → `0002_users` →
`0003_refresh_sessions`. The `users` table stores canonical email and
`password_hash`; plaintext passwords are not persisted. `refresh_sessions`
stores a UUID, `user_id` foreign key with `ON DELETE CASCADE`, unique
`token_hash`, timezone-aware `expires_at`, and nullable `revoked_at`. Indexes
support user lookup and expiration cleanup. The refresh token itself is never
stored.

Gateway uses `UserRepository` and `RefreshSessionRepository`; both perform
persistence operations only. `AuthenticationService` coordinates login,
rotation, logout, validation, and commits. Refresh looks up the hash with
`SELECT ... FOR UPDATE`, validates the locked session and user, revokes the old
row, inserts the replacement, and commits as one transaction. This serializes
same-token refreshes under PostgreSQL's normal transaction isolation; the
opt-in integration test is the intended real-database verification.

At the Phase 4 security-testing checkpoint, the configured PostgreSQL reported
revision `0001_meetings_transcripts`, without `users` or `refresh_sessions`.
The migration and test status at that historical checkpoint is superseded by
the Phase 5 synchronization record below.

## Phase 5 persistent Meeting domain

Revision `0004_meeting_domain_results` follows `0003_refresh_sessions` and
defines Summary, Task, Decision, and FollowUp persistence. Each belongs to one
Meeting; Meeting has zero or many of each result and database foreign keys
cascade child deletion. `Meeting.transcript` is one-to-one (unique transcript
`meeting_id`). `Meeting.summaries`, `.tasks`, `.decisions`, and `.followups` are
one-to-many relationships. A Task may have zero or one User assignee, while a
User may be assigned many Tasks. The `assignee_id → users.id` foreign key uses
`ON DELETE SET NULL`; deleting an assignee preserves the Task.

Summary `version` is positive and defaults to 1. The database enforces unique
`(meeting_id, version)` using `uq_summaries_meeting_version`; the repository's
latest-version query selects the greatest version. The Summary API route
currently creates version 1 only (the create request has no version field);
service-level creation accepts an explicit version. Version progression is
not automatic.

Summary and Decision retain the `created_at` fields in their current shared
schemas; Task also has `updated_at` for its workflow state; Followup retains
the contract's `created_at`, schedule, and send timestamps. Statuses use native
PostgreSQL enums whose values match the Pydantic contracts. JSONB holds the
existing list-shaped `key_topics`, `participants`, and `recipients` values.

Phase 7.4 defines `MeetingInsight` as one immutable snapshot per typed insight
candidate. Its columns are UUID `id`, required UUID `meeting_id`, required
`meeting_insight_category` `category`, required `title` and `description` text,
and required timezone-aware `created_at` with a database `now()` default. It
has no `updated_at`, status, version, processing run ID, or provider metadata.
`Meeting.insights` is a one-to-many ORM relationship with `delete-orphan`; the
foreign key cascades on Meeting deletion. The shared `InsightCategory` enum
supplies the same controlled values to validation and the native PostgreSQL
enum. There is no semantic deduplication or replacement policy, so similar
findings from separate runs may coexist.

The AI mapper produces `MeetingInsightBase` values with a trusted meeting ID;
it does not persist them. `MeetingInsightRepository` provides create,
get-by-ID, and meeting-scoped list queries, flushing writes without committing.
There is no insight-specific domain service or public route. Revision
`0005_meeting_insights` defines the schema but is currently unapplied and has
not been validated against PostgreSQL. Applying it remains a deliberate future
database action; the presence of ORM metadata does not mean the live database
contains the table.

### Result indexes and query behavior

- `uq_summaries_meeting_version`: unique per-meeting version constraint.
- `ix_summaries_meeting_version_desc`: meeting/version descending lookup.
- `ix_tasks_meeting_status`, `ix_tasks_assignee_status`: Task filtering.
- `ix_decisions_meeting_id`, `ix_followups_meeting_id`: meeting-scoped lists.
- `ix_meeting_insights_meeting_id`: meeting-scoped insight listing.
- Meeting foreign keys cascade deletes; the Task assignee foreign key sets the
  reference to `NULL` when a User is deleted.
- `0004_meeting_domain_results` defines `ck_summaries_version_positive` and
  native `task_status` / `followup_status` enums matching the Pydantic values.
  JSONB stores `key_topics`, decision `participants`, and follow-up `recipients`.

### Repository and service boundary

Repositories use `AsyncSession.execute(select(...))` and return ORM rows; they
flush writes but do not commit or roll back. Meeting-domain services own
successful-write commits, map rows to Pydantic DTOs, and enforce ownership
through `MeetingService.require_owned_meeting()`. Result mappers read scalar
columns rather than traversing ORM relationships, avoiding implicit async lazy
loads and relationship-driven N+1 queries.

Meeting-scoped repository lists are deterministic: Summary versions ascending
then ID (latest lookup descending), Tasks and FollowUps by `created_at DESC,
id DESC`, and Decisions by `created_at ASC, id ASC`. Task and FollowUp
repositories add status predicates to SQL queries. API lists use the shared
pagination schemas/helper.

### PostgreSQL Phase 5 synchronization

The verified local development database began at `0001_meetings_transcripts`.
After target verification, `alembic upgrade head` applied `0002_users`,
`0003_refresh_sessions`, and `0004_meeting_domain_results`. Final
`alembic current` reports `0004_meeting_domain_results (head)` and
`alembic check` reports no pending upgrade operations. Seven opt-in PostgreSQL
tests passed, covering refresh-session lifecycle plus Phase 5 result
persistence/retrieval, Summary unique versions/latest ordering, Task/FollowUp
status filters, assignee `SET NULL`, and Meeting-child `ON DELETE CASCADE`.

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

## Meeting route composition (Phase 3.4 baseline, extended in Phase 4)

Meeting Service exposes internal unversioned meeting and transcript routes.
Gateway exposes authenticated public meeting and transcript routes under
`/api/v1/meetings` and forwards them using `MeetingServiceClient`. The internal
organization-wide list route remains without identity or membership
authorization; organization membership is pending.

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
request from the injected session. The Gateway similarly composes its client
from settings and derives the user identity from the authenticated access JWT.
This keeps routes free of SQL and business transaction handling.
`get_db_session()` obtains a session from the shared factory, yields it for the
request, and rolls it back only if an exception propagates. On success it does
not auto-commit: `MeetingService` remains the successful-write commit boundary,
while reads do not commit.

Routes accept validated Pydantic input and delegate. Authenticated Gateway
operations call the client, which sends a signed internal principal. Meeting
Service validates that principal, and its service checks `created_by` for
individual meeting/transcript access. Routes do not construct ORM models,
execute SQL, commit, rollback, or manually translate `AppError` instances.
Central handlers keep error responses safe and include request IDs.

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
