# Architecture Overview

> MannerAI Meetings Platform — current AI and background job boundaries through Phase 9.4.

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
below. Phases 9.1–9.4 implement Redis/Celery transport, signed distributed job
identity, worker runtime composition, and a PostgreSQL-backed lifecycle.
Migration `0006_processing_jobs` is applied at Alembic head. PostgreSQL
persistence, concurrent claims, lease reclamation/fencing, and terminal
persistence passed opt-in integration tests. Live Redis/Celery worker
execution remains unvalidated because Redis was unavailable in the development
environment. Public AI endpoints and frontend workflow integration remain
future work.

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
The Celery adapter introduced in Phase 9.1 is described next; no public job
endpoint is introduced here.

Phase 9's signed producer authorization and worker verification are described
below. A worker never derives identity from an unsigned queue field; external
access/refresh credentials, passwords, and provider credentials are excluded
from the message. Authentication stays outside the AI service, orchestrator,
and agents.

## Phase 9 Redis/Celery transport and signed job identity

Redis is the configured Celery broker. `worker-service` creates a Celery app
from environment-backed settings without connecting to Redis at import time.
Tasks accept JSON only, use UTC, default to one worker process and a prefetch
multiplier of one. Tasks use late acknowledgement and worker-loss redelivery
with a database lease to recover interrupted work. No Celery result backend
is configured: Celery is the delivery/orchestration layer, while the existing
executor owns the application lifecycle and typed result semantics. Celery
task state is not treated as the job's business status.

`AIProcessingJobEnvelope` is a strict primitive message containing only the
job, meeting, and transcript UUIDs and requested operation names. It rejects
unknown fields and invalid identifiers/operations. It excludes
`TrustedExecutionContext`, `user_id`, tokens, ORM state, and AI results. Free
form job context is also rejected by the Celery submission adapter until a
safe explicit transport schema is defined. The adapter sends through a
provided Celery publisher and propagates broker errors rather than reporting a
queued receipt on failure.

The JSON message contains the unchanged four-field primitive envelope and a
separate RS256 background-job authorization. The producer signs the
authenticated user from the already-bound `TrustedExecutionContext`; the
authorization contains issuer, audience, type, `iat`, short `exp`, unique
`jti`, authenticated subject, and exact job/meeting/transcript/operation
bindings. It is a dedicated purpose-specific credential, separate from both
the external access JWT and Gateway-to-Meeting internal principal.

The worker validates the message schema, verifies signature/issuer/audience,
purpose and lifetime, and compares every binding before issuing a
`TrustedExecutionContext`. Only then can it construct the existing job and
invoke `AIProcessingJobExecutorService`. Missing keys, malformed messages,
invalid credentials, or mismatches fail closed before transcript lookup and AI
execution. The task has no AI or agent business logic. MeetingService ownership
checks remain in the existing transcript provider.

The signing private key and worker verification public key use
`BACKGROUND_JOB_SIGNING_PRIVATE_KEY` and
`BACKGROUND_JOB_VERIFICATION_PUBLIC_KEY`. Production settings require valid
RSA-2048-or-stronger PEM keys. Use a dedicated pair, never external JWT or
internal-principal keys. Local development may omit keys, in which case
distributed submission/verification cannot proceed.

The default authorization lifetime is 120 seconds (maximum 300 seconds); the
worker allows five seconds of clock skew. It is job-bound and cannot authorize
a different envelope. A captured intact message can still be replayed for the
same job while valid (including the skew allowance): there is no durable
job/idempotency store to coordinate one-time consumption. `jti` is unique
metadata, not replay prevention. Durable replay protection belongs with the
later persistent job/idempotency system; no process-local cache is claimed as
distributed protection. Phase 8's process-local adapter remains available.

Celery 5.4 and Redis client 5.2 are already declared in `requirements.txt`; no
dependency was added. Redis is not installed or running in the current local
environment, so this block validates configuration and mocked task/publisher
behavior only. It does not claim live broker or worker integration.

At worker startup, a runtime factory composes the existing Phase 8 executor
with the AI processing service and Meeting Service transcript provider. The
runtime is not created when importing the Celery app; worker startup configures
it, and each executed job scopes its database engine/session and model provider
to that execution. The broker is configured through `CELERY_BROKER_URL`
(`redis://localhost:6379/1` by default). Connection, socket-connect, and
socket-operation timeouts default to 5, 5, and 10 seconds.

The Phase 9.3 baseline used early acknowledgement. Phase 9.4 replaces that
delivery policy with late acknowledgement, worker-loss redelivery, and the
PostgreSQL lifecycle claim/lease described below.

The opt-in live execution test is
`RUN_REDIS_CELERY_INTEGRATION=1 python -m unittest backend.tests.test_phase9_3_redis_celery.LiveRedisCeleryExecutionTests -v`.
It starts a real Celery worker, submits through the signed producer adapter,
and uses a deterministic model provider while exercising Meeting Service
ownership checks. It makes no OpenAI calls. Redis is unavailable in the current
environment, so live broker execution remains unvalidated here. The opt-in
test is the validation path when Redis is available; implementation and
offline boundary tests do not count as live broker validation.

### Phase 9.4 durable lifecycle and reliability

`processing_jobs` is the authoritative application lifecycle record, keyed by
the existing application `job_id`. The producer-side
`ApplicationJobSubmissionService` registers the job with the authenticated
owner before publishing the signed envelope. Reusing the same ID with the
same meeting, transcript, owner, and operations returns the same logical row;
rebinding the ID is rejected. There is no public job-status API.

The state machine is `queued → running → completed | partial | failed`, with
`running → queued` for a classified transient failure and a new atomic claim.
An expired `running` lease may be reclaimed as a new attempt. Terminal states
are immutable. PostgreSQL `SELECT FOR UPDATE` serializes registration/claim/
completion; a random lease token prevents an expired worker from overwriting
the newer attempt. The worker verifies the Phase 9.2 signature and exact
bindings before loading the lifecycle row. It then runs MeetingService
ownership and transcript validation before acquiring an execution claim; a
rejected target is marked failed without incrementing attempts or invoking AI.

The application increments `attempt_count` only when it atomically claims a
queued/due job. Defaults are three total claims, exponential delays of 2/4
seconds capped at 60 seconds, a 16-minute lease, and a 15-minute Celery hard
task limit. Celery retry count is scheduling only; the database attempt count
decides whether another execution is allowed. Provider unavailable/timeout
failures and unexpected worker execution failures are retryable. Validation,
authorization, ownership/transcript, malformed-message, and application
processing failures are terminal. Partial results are persisted with their
successful operation outputs and sanitized failed-operation details and are
not retried wholesale.

Workers use late acknowledgement and reject worker-lost tasks for redelivery.
An active lease makes duplicate delivery a deferred no-op; terminal delivery
returns `already_terminal`. This is at-least-once execution with PostgreSQL
claim/idempotency protection, not exactly-once processing or universal
idempotency. If PostgreSQL is unavailable before a claim or a broker cannot
schedule an already-persisted retry, a queued record may require operational
redrive. Redis is only transport; durable lifecycle requires PostgreSQL.

Apply the new forward migration through head before running the worker or
producer coordinator. The opt-in PostgreSQL integration test requires
`RUN_POSTGRES_INTEGRATION=1` and a database already migrated through head. The
opt-in Redis worker test still requires a reachable Redis-compatible broker;
neither service is started by ordinary tests.

Phase 9 validation checkpoint: PostgreSQL integration **2/2 passed** with no
skips, including persisted lease reclamation, a fresh attempt/token, stale
completion and failure fencing, and final state persistence. Phase 9.4
lifecycle tests passed **11/11**; database regressions passed **19 tests**
(1 skipped), and the Phase 5 PostgreSQL regression passed **1/1**. Live Redis
execution was not validated. Docker/platform execution remains deferred.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, transcripts, summaries, tasks, decisions, follow-up drafts |
| ai-service | AIProcessingService, transcript normalization, five agents, injected provider abstraction/OpenAI adapter, orchestration, typed validation and domain mapping; no database or persistence side effects |
| search-service | Health service; chunking, embeddings, and Qdrant retrieval remain deferred |
| worker-service | Health service plus Celery configuration, trusted job verification, and Phase 8 execution runtime |

## Data stores

- **PostgreSQL** — users, refresh sessions, meetings, transcripts, meeting results, and durable `processing_jobs`; migration `0006_processing_jobs` is applied at head
- **Redis** — configured Celery broker; live broker execution was not validated because Redis was unavailable
- **Qdrant** — planned vector index; retrieval integration is deferred

## Persistence layer

- **SQLAlchemy 2.0 async** + **asyncpg** for PostgreSQL access
- **Alembic** for schema migrations (see `database/postgresql/migrations.md`)
- **Pydantic schemas** in `backend/shared/schemas/` for shared API/domain DTOs
- **SQLAlchemy ORM models** in `backend/shared/database/models/` for users, refresh sessions, meetings, transcripts, summaries, tasks, decisions, follow-ups, and meeting insights
- The AI processing service does not run migrations or persist mapped meeting results; database schema lifecycle is managed separately through Alembic

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
- gateway-service owns user and refresh-session persistence; meeting-service owns meeting, transcript, and result persistence. PostgreSQL is at Alembic head `0006_processing_jobs`; the shared job lifecycle owns `processing_jobs`.

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
- Live Redis/Celery worker execution validation (Phase 9 implementation is complete; broker validation awaits an available Redis service)
- Semantic search, Qdrant/RAG, analytics, and frontend AI workflow
- Docker/infrastructure work, Gmail integration, and later roadmap phases
