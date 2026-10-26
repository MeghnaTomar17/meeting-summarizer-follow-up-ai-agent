# Architecture Overview

> MannerAI Meetings Platform — current AI, background job, and vector data boundaries through Phase 10.6.

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

Phase 10.1 defines a Search-owned transcript chunk and vector payload contract.
Phase 10.2 adds the provider adapter/service boundary, 10.3 prepares complete
typed batches, 10.4 persists those batches through a Search-owned Qdrant
repository, and 10.5 adds authenticated owner-scoped retrieval; PostgreSQL
remains the source of truth.
See the Phase 10 sections below.

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

The worker and producer coordinator require migration 0006 to be applied. The
opt-in PostgreSQL integration test requires `RUN_POSTGRES_INTEGRATION=1` and a
database already migrated through head. The
opt-in Redis worker test still requires a reachable Redis-compatible broker;
neither service is started by ordinary tests.

Phase 9 validation checkpoint: PostgreSQL integration **2/2 passed** with no
skips, including persisted lease reclamation, a fresh attempt/token, stale
completion and failure fencing, and final state persistence. Phase 9.4
lifecycle tests passed **11/11**; database regressions passed **19 tests**
(1 skipped), and the Phase 5 PostgreSQL regression passed **1/1**. Live Redis
execution was not validated. Docker/platform execution remains deferred.

## Phase 10 vector-search architecture and embedding provider (through 10.6)

PostgreSQL remains authoritative for meetings, transcripts, users, and domain
results. Qdrant is a derived retrieval index containing transcript chunks and
the metadata required to identify and authorize each source; it is not a
second copy of Meeting or Transcript entities.

The canonical source is the shared `NormalizedTranscript`, produced from the
Meeting Service `TranscriptInDB` DTO by `normalize_transcript()`. This keeps
the established checks and ordering (meeting/transcript binding, unique
nonnegative segment indices, timestamps, and segment order) in one place for
both AI and Search. Chunks combine consecutive complete segments toward a
configurable character target (default 2000); a long segment remains intact.
Chunk text preserves source text, with speaker names stored as metadata.
Metadata preserves meeting/transcript IDs, chunk position, each represented
source segment's index, optional speaker and timestamps, chunk time bounds,
language, owner, and organization.

Point IDs are deterministic UUIDv5 values over a versioned namespace and
`meeting_id`, `transcript_id`, and `chunk_index`. A content change at the same
position therefore has the same point identity. Re-indexing removes stale
positions for the transcript, and deletion removes points by meeting or
transcript identity through the repository described below.

`SearchSettings` defines collection name `meeting_chunks`, vector dimension
(`EMBEDDING_DIMENSIONS`, default 1536), distance (`Cosine` by default), model
provider/model identity, and chunk-size target. The provider-neutral
`EmbeddingProvider` request/response contracts bind vectors to that model
identity and validate dimensionality and finite values. `EmbeddingService`
accepts text or existing transcript chunks through that boundary. The
Search-owned OpenAI adapter uses the already-declared SDK dependency;
provider/model/dimensions are checked and vectors are validated for shape and
finite values. Credentials stay in `SecretStr` runtime configuration and
never enter embedding requests, responses, or sanitized failures. The optional
`EMBEDDING_BASE_URL` and timeout are runtime configuration, not domain metadata.

Payload ownership metadata maps `owner_id` to the persisted
`Meeting.created_by` and also carries `organization_id`. Future retrieval
must derive allowed scope from authenticated identity and server-side
MeetingService authorization; client-supplied IDs cannot establish authority.
Current Meeting authorization is creator-based, and organization membership
is not modeled, so organization filtering alone is not an authorization rule.
No search endpoint or RAG prompt path is part of 10.1.

When transcripts are replaced or edited, the authoritative PostgreSQL
transcript remains intact and the derived points must be re-indexed; meeting
deletion requires cross-store point cleanup. Index failure must not roll back
or corrupt the PostgreSQL source. Durable retry/reconciliation and atomic
index replacement are later work. A model or dimension change requires a
compatible collection/rebuild rather than mixing incompatible vectors.

Phase 10.2 adds the configured provider boundary and OpenAI adapter, without a
live embedding API requirement. Phase 10.3 adds a Search-owned pipeline that
returns a typed, complete vector-index batch. Provider failure aborts the
batch; empty transcripts return an empty batch.

Phase 10.4 adds `QdrantVectorRepository`: explicit collection initialization
and dimension/distance validation, deterministic point upserts, transcript
replacement by upserting desired points before deleting stale IDs, and
transcript/meeting filter deletion. These operations are not atomic across
Qdrant and PostgreSQL; a retry can reconcile point IDs after partial failure.
The repository has fake-client coverage. The opt-in live Qdrant integration
test was not run, so server operation is unverified.

Phase 10.5 adds strict shared request/response DTOs, Search-side verification
of Gateway-signed RS256 internal principals addressed to `search-service`,
single-query embedding through the existing provider, Qdrant `owner_id`
filtering, and the public Gateway `POST /api/v1/search` proxy. Search derives
owner scope only from the verified principal subject; it ignores arbitrary
identity headers and rejects scope fields in the request body. The Qdrant
query always includes the mandatory owner filter before vector search. Results
are validated against the persisted chunk payload and point ID; owner and
organization metadata, raw payloads, and vectors are not returned.

Current Meeting authorization is creator-based and organization membership is
not modeled, so retrieval is owner-only. Search requires its own configured
verification public key in production; Gateway retains the signing private
key. Docker/Compose wiring was not changed in this block, so production
deployment must supply the matching Search public key through its runtime
configuration. Phase 10.6 hardens the Gateway proxy's non-success handling,
including timeouts and redirects, and adds focused authentication, forwarding,
and sanitization regression coverage. The opt-in live Qdrant repository test
verifies deterministic similarity ranking and owner isolation against the local
server. It does not verify live embedding-provider calls or a deployed
Gateway-to-Search-to-Qdrant path. Search `/health/ready` remains process-level
and does not establish provider or Qdrant availability. Durable indexing jobs,
generated-answer RAG, reranking, and hybrid retrieval remain deferred. Phase 11
Block 3 below describes how the existing retrieval response can serve as
retrieval-only RAG context.

### Phase 11 Block 1: persisted transcript indexing

The authenticated Gateway route `POST /api/v1/search/meetings/{meeting_id}/index`
orchestrates indexing without moving search logic into Meeting Service. It uses
the existing Gateway-signed `meeting-service` principal to request an internal
index source. Meeting Service verifies creator ownership, loads the persisted
transcript from PostgreSQL, and returns it with the meeting's stored
`organization_id`; the source carries no owner field. The Gateway forwards this
source to Search using the existing Search-audience principal, and Search
constructs `TranscriptIndexScope.owner_id` only from the verified token subject.
The authenticated caller supplies only the meeting ID.

Search runs the existing normalizer/chunker/embedding pipeline synchronously,
prepares every vector before Qdrant mutation, then uses the repository's
initialize/upsert-and-prune contract. Provider or preparation failures leave
the existing point set untouched. A source-not-found or authorization failure
stops in Meeting Service and cannot become an empty replacement. A genuinely
empty persisted transcript is a valid empty batch and removes the transcript's
existing points. Upsert and stale deletion are not atomic; a stale deletion
failure may leave old and new chunks together until a retry. The worker's
`run_embedding_job` remains unimplemented, so this block does not claim durable
background execution. Live provider, PostgreSQL, and deployed
Gateway-to-Search integration require separate live checks; mocked tests do
not establish those integrations.

### Phase 11 Block 3: similarity and RAG retrieval scope

The existing authenticated `POST /search` performs vector top-k retrieval at
the transcript-chunk level for a text query. Qdrant applies the mandatory
verified-owner filter; the repository validates the stored chunk payload,
embedding identity, and deterministic chunk ID before returning results with
raw similarity scores and source provenance. This already provides a
similarity-search operation, so no alias endpoint is added. The current
contract does not define chunk-ID-seeded similarity or meeting-level
aggregation; the latter would require an agreed aggregation and ranking rule.

The same validated result DTO can serve as retrieval-only RAG context: it
includes relevant chunk text and meeting, transcript, chunk, segment, timing,
language, and score metadata. No separate context assembly API is necessary
for that contract. Search does not call an LLM or generate answers. AI Service's
existing agents process a supplied transcript into typed meeting-domain
outputs; their current flow does not retrieve Search results. The Phase 11
roadmap does not say whether RAG means retrieval-only or generated answers, so
an answer-generation integration would require a scope decision before it is
designed.

### Phase 12 Block 1: structured cross-meeting evidence

The authenticated Gateway exposes `POST /api/v1/intelligence/structured-data`
and forwards a bounded query to Meeting Service using a Gateway-signed
`meeting-service` principal. Meeting Service derives the owner from that
verified principal and applies `Meeting.created_by` scope to each meetings,
tasks, decisions, and insights query. The response contains separate pages
with stable record IDs and meeting provenance. The optional time window uses
meeting `scheduled_at` and child `created_at` fields; unresolved tasks are
`open` or `in_progress`, while overdue tasks have `due_at` before the current
Meeting Service clock and are not `done` or `cancelled`.

This block only exposes structured evidence. It does not resolve project
entities, identify recurring issues, query Qdrant, call an LLM, or generate
answers. Project association remains approximate until a product model exists;
recurrence detection and RAG answer orchestration remain later work. Search
Service continues to own semantic/vector retrieval.

### Phase 12 Block 2: structured and semantic evidence composition

Gateway's authenticated `POST /api/v1/intelligence/evidence` composes the
Block 1 structured-data contract with Search Service's existing semantic
search contract. It passes the Gateway-authenticated user and request ID to
both clients; each client signs a separate audience-bound internal principal.
Meeting Service remains responsible for PostgreSQL queries and Search
Service remains responsible for embeddings, Qdrant queries, and owner
filtering. Gateway validates both established response schemas and returns a
typed evidence bundle with structured-record and transcript-chunk provenance.

Failure of either source, or a malformed downstream response, fails the whole
request with a sanitized service error. Empty sources remain empty. This block
does not query databases or vector stores directly, invoke an LLM, resolve
projects, infer missed deadlines, detect recurrence, or generate an answer.

### Phase 12 Block 3: evidence-grounded answers

The authenticated Gateway `POST /api/v1/intelligence/questions` uses the
Block 2 service to retrieve owner-scoped structured and transcript evidence,
then calls AI Service with an `ai-service` audience-bound principal and the
same request ID. AI Service owns prompt construction and generation through
the existing provider-neutral adapter and structured-output validation path.
It has no database or Qdrant access. The AI response can refer only to record
IDs in the supplied bundle; AI Service resolves those IDs back to citation
metadata from the trusted bundle before returning it.

Empty evidence produces an explicit insufficient-evidence response without a
provider call. Retrieved transcript content is marked as untrusted data in the
prompt. Task and time semantics follow the Block 1 definitions. Possible
recurring themes require cited evidence from distinct meetings, but no numeric
recurrence threshold is asserted. Project matching remains limited to explicit
names and meeting titles/descriptions. Citation validation prevents invented
IDs and metadata substitution; it does not semantically verify every answer
claim, so generated answers remain bounded by the provider's interpretation.

Gateway derives UTC month boundaries for “this month” questions, applies the
half-open interval to Block 1 structured queries, and passes the returned
meeting IDs as an additional Search filter. Search always combines that filter
with the authenticated owner filter. Overdue and unresolved task questions
select Block 1's corresponding task filters. Repeated-deadline answers require
overdue task citations spanning distinct meetings; no recurrence threshold is
introduced.

### Phase 13 Block 1: dashboard analytics

The authenticated Gateway `GET /analytics/overview` proxies to Meeting
Service, which owns PostgreSQL aggregate queries. Every metric is scoped by
joining records to meetings whose `created_by` matches the verified internal
principal; caller-supplied organization IDs are not used for authorization.
The response includes all-time meeting/task/decision/follow-up totals, separate
meeting and processing-job status counts, and a bounded UTC weekly meeting
series. The series defaults to 12 Monday-based calendar weeks and accepts 1–52
weeks, including zero-count buckets. Overdue tasks use the Meeting Service UTC
clock, a strict past-due comparison, and exclude completed or cancelled tasks.

The authenticated Gateway `GET /analytics/trends` adds weekly decision counts,
meeting frequency, and persisted topic counts. Decision buckets use
`Decision.created_at`; meeting frequency is the same scheduled-meeting series
as the overview. Topic trends use each owned meeting's latest summary version,
bucketed by `Meeting.scheduled_at`. Exact topic strings are lowercased, trimmed,
and whitespace-collapsed, with duplicates counted once per meeting. Non-string,
empty, malformed, and over-500-character topic entries are excluded. Similar
phrases are not merged, and the endpoint does not call an LLM.

The authenticated Gateway `GET /analytics/recurring-blockers` reads persisted
`blocker` insights through owner-scoped Meeting Service queries. Recurrence
means an exact description match after trimming, lowercasing, and collapsing
whitespace, supported by at least two distinct owned meetings; phrases are not
semantically merged. Each group carries original insight text, stable meeting
and insight UUIDs, and the insight creation timestamp. Groups are bounded and
ordered by meeting count then normalized description; evidence is capped per
group, with truncation reported. This path does not regenerate insights or
invoke an LLM.

The authenticated Gateway `GET /analytics/task-completion-trends` currently
reports a capability limitation: Task persists current status and `updated_at`,
but not a completion timestamp or transition history. The implementation does
not mislabel `updated_at` as a completion event. The authenticated Gateway
`GET /analytics/speaker-participation` aggregates valid unique segment indexes
from owned persisted transcripts in PostgreSQL. It reports segment counts by
meeting-local speaker label and separates missing, blank, or `unknown` labels;
it does not infer duration from optional timestamps or identify speakers across
meetings. Transcript text is not returned, duplicate indexes count once, and
the meeting and speaker lists are bounded with truncation indicators.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, transcripts, summaries, tasks, decisions, follow-up drafts |
| ai-service | AIProcessingService, transcript normalization, five agents, injected provider abstraction/OpenAI adapter, orchestration, typed validation and domain mapping; no database or persistence side effects |
| search-service | Health, deterministic chunking/index preparation, embeddings, Qdrant persistence, and authenticated owner-scoped retrieval |
| worker-service | Health service plus Celery configuration, trusted job verification, durable Phase 9 lifecycle, and Phase 8 execution runtime |

## Data stores

- **PostgreSQL** — users, refresh sessions, meetings, transcripts, meeting results, and durable `processing_jobs`; migration `0006_processing_jobs` is applied at head
- **Redis** — configured Celery broker; live broker execution was not validated because Redis was unavailable
- **Qdrant** — Search Service repository initializes, persists, and owner-filters the derived `meeting_chunks` index; live local repository retrieval and owner-isolation coverage passed, while deployed service integration remains unverified

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
