# Architecture Overview

> MannerAI Meetings Platform — current AI and process-local job boundary after Phase 8.

**Entry point:** For the consolidated current reference and Phase 7 checkpoint, see [project-foundation.md](./project-foundation.md).

## System context

The platform persists meetings, transcripts, and domain results behind a Gateway and Meeting Service. Phase 7 implements and tests the AI application path from a caller-supplied transcript through normalization, orchestration, five agents, an injected provider, typed output validation, and domain mapping. `AIProcessingService` returns trusted, domain-ready inputs with operation-level failures; it does not retrieve transcripts from storage or persist results. Phase 8 adds a process-local job-submission boundary whose executor delegates to that existing service. The OpenAI adapter is one `ModelProvider` implementation. Deterministic integration tests use a test-only provider and make no network calls.

## Current AI processing boundary (Phase 7)

```text
Caller supplies ProcessingRequest + trusted TranscriptInDB
                         ↓
              transcript normalization
                         ↓
                    AgentInput
                         ↓
                AIProcessingService
                         ↓
              AIProcessingOrchestrator
                         ↓
       Summary / Task / Decision / FollowUp / Insight agents
                         ↓
               injected ModelProvider
                         ↓
          structured JSON → typed Pydantic output
                         ↓
                 domain mapping
                         ↓
             domain-ready input DTOs
                         ↓
       caller-owned application/persistence decision
```

Agents receive application input and do not query the database. Provider SDKs
remain behind the `ModelProvider` protocol; OpenAI is a concrete adapter, while
tests inject deterministic structured responses. The application supplies
meeting/transcript identity, and model output cannot replace it. Structured
validation checks shape and types, not whether a claim is semantically true.
Successful mappings are not automatically written to PostgreSQL. MeetingInsight
has persistence models and a repository, but no automatic AI-to-database path.

The implemented AI-processing path is synchronous orchestration in-process; it
does not mean HTTP requests are queued or processed in the background. Phase 8
adds a separate, framework-neutral submission/execution boundary described
below. Redis/Celery, retries, durable job state, public AI endpoints, and
frontend workflow integration remain future work.

## Phase 8 job boundary (framework-neutral, in-process)

```text
Caller → JobSubmissionPort → AIProcessingJob (queued)
                                  ↓ explicit local dispatch
                         AIProcessingJobExecutor
                                  ↓
                   TranscriptInputProvider
                                  ↓
                  verified TranscriptInDB DTO
                                  ↓
                        AIProcessingService
                                  ↓
                existing orchestration and mapping path
```

`AIProcessingJob` carries a stable UUID, meeting/transcript IDs, requested
operations, optional context, timestamps, controlled status, and sanitized
failure/result metadata. Its lifecycle allows `queued → running → completed`,
`queued/running → failed`, or `running → partially_failed`. The executor
resolves and validates transcript identity, constructs the existing
`ProcessingRequest`, and delegates to `AIProcessingService`; it does not
duplicate AI processing or persist results. Per-operation failures remain in
`AIProcessingResult`; total AI failure, invalid input, mapping failure, and
unexpected execution failure produce distinct safe job failures.

`TranscriptInputProvider` is an application port that resolves exactly the
meeting/transcript pair in the job and returns the shared `TranscriptInDB`
contract. The executor checks both IDs before delegating. The existing
`AIProcessingService` then applies the Phase 7 normalization path, which
preserves segment order, speaker, timestamps, language, and trusted IDs.
Agents and the AI service remain unaware of ORM/database access. The AI result
contains domain-ready inputs but is not automatically persisted.

Gateway's `get_trusted_execution_context` depends on `get_current_user`, which
validates the access token and loads the persisted user. It issues a frozen
`TrustedExecutionContext` containing only the user UUID and an opaque context
binding ID. `AIProcessingJob.from_authenticated_context()` binds both values
to the job; substitutions to either the context or its principal are rejected.
The job has no arbitrary `user_id` input. The executor passes the
same context to `MeetingServiceTranscriptInputProvider`, which delegates to
`MeetingService.get_transcript()`. The existing service enforces ownership
through `require_owned_meeting()` before reading the transcript. The provider
then verifies the requested transcript ID. A missing context fails the job;
a different user's context is rejected by the existing ownership check. AI
services/agents receive no authentication context.

This adds no token format and performs no JWT validation in AI code. Existing
Gateway-to-Meeting HTTP calls continue to use the Gateway-signed internal
principal; the in-process provider passes the already-established user UUID to
the existing application service.

Security invariant: **Background execution must preserve the authenticated
principal established by the trusted application boundary; it must never
derive authorization identity from arbitrary job payload data.** Public input
schemas must not accept this internal context. Phase 9 queue consumers must
accept identity only from the trusted producer channel and must never accept
client-supplied user IDs or credentials as authorization authority.

`InProcessJobSubmissionPort` is a FIFO `asyncio.Queue` that accepts a job and
returns a queued receipt; tests/development explicitly dispatch one job with
`run_next()`, which passes it to the same executor. The end-to-end integration
path uses this adapter, the actual MeetingService ownership check, the existing
Phase 7 normalization and `AIProcessingService` path, and a deterministic test
provider. Results stay in the returned job and are not persisted.

This adapter is process-local only. It does not guarantee durable jobs, retries,
at-least-once or exactly-once delivery, crash recovery, distributed locking,
queue persistence, worker concurrency, or dead-letter handling. Pending jobs
disappear on process exit. The adapter does not add concurrency or retry
semantics. The existing direct `AIProcessingService` call remains available;
Redis/Celery adapters belong to Phase 9, and no public job endpoint is
introduced here.

Phase 9 must authenticate the trusted queue producer and transport only an
explicitly defined job envelope. A worker must authenticate and validate each
message before execution, then obtain or reconstruct a trusted execution
context through a controlled mechanism. It must never trust arbitrary
`user_id` data from an untrusted producer or accept access/refresh tokens,
passwords, or provider credentials in the envelope. The worker must invoke this
same `AIProcessingJobExecutorService` and preserve its lifecycle and sanitized
error semantics. Authentication and authorization logic must remain outside
the AI service, orchestrator, and agents. The current context issuance marker
is intentionally not a serialized credential; producer authenticity must be
established before the worker creates a context.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, transcripts, summaries, tasks, decisions, follow-up drafts |
| ai-service | AIProcessingService, transcript normalization, five agents, injected provider abstraction/OpenAI adapter, orchestration, typed validation and domain mapping; no database or persistence side effects |
| search-service | Health service; chunking, embeddings, and Qdrant retrieval remain deferred |
| worker-service | Health service; distributed Celery worker execution remains deferred to Phase 9 |

## Data stores

- **PostgreSQL** — users, refresh sessions, meetings, transcripts, and Phase 5 meeting results; the MeetingInsight schema is defined but awaits migration 0005
- **Redis** — configured for future cache/broker use; not wired to AI processing
- **Qdrant** — planned vector index; retrieval integration is deferred

## Persistence layer

- **SQLAlchemy 2.0 async** + **asyncpg** for PostgreSQL access
- **Alembic** for schema migrations (see `database/postgresql/migrations.md`)
- **Pydantic schemas** in `backend/shared/schemas/` for shared API/domain DTOs
- **SQLAlchemy ORM models** in `backend/shared/database/models/` for users, refresh sessions, meetings, transcripts, summaries, tasks, decisions, follow-ups, and meeting insights
- Migration `0005_meeting_insights` is defined but unapplied; no migration is run by the AI processing service

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
- gateway-service owns user and refresh-session persistence; meeting-service owns meeting, transcript, and existing result persistence. MeetingInsight ORM/schema/repository support is defined, but migration 0005 remains unapplied.

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

## Deferred work

- Sequence diagrams for upload → process → index flow
- Organization membership and authorization for organization-wide listing
- Public AI processing API and production Gateway integration
- Redis/Celery queue and worker integration, retry policy, and delivery/idempotency guarantees (Phase 9)
- Semantic search, Qdrant/RAG, analytics, and frontend AI workflow
- Applying and PostgreSQL-validating migration `0005_meeting_insights`; it is defined but unapplied
- Docker/infrastructure work, Gmail integration, and later roadmap phases
