# Engineering Problems and Solutions

This is a factual record of meaningful issues encountered through Phase 9.
It complements the current architecture documents; it does not turn deferred
design choices into completed work.

Earlier issues remain under their original checkpoint numbers. Phase 9 entries
below record actual implementation and validation events, including the live
Redis limitation and PostgreSQL lifecycle evidence.

## PS-001 — Test framework assumption

### Context

The project needed a repeatable validation command.

### Symptom

`pytest` was unavailable, and `python -m pytest` reported `No module named pytest`.

### Investigation

Repository inspection showed tests subclass `unittest.TestCase` and need no
third-party test runner.

### Root Cause

The test framework had been assumed instead of inferred from project code.

### Solution and validation

Use `python -m unittest discover -s backend/tests -p "test_*.py"`. It is the
project's standard command; no dependency was added.

### Engineering Lesson / Interview Talking Point

“I first inspect a repository’s test conventions. In this project the built-in
`unittest` runner was intentional and sufficient, so installing pytest would
have changed the environment without solving a project problem.”

## PS-002 — Alembic revision identifier boundary

### Context

The first domain migration was being applied to PostgreSQL.

### Symptom

Alembic attempted to insert `0001_create_meetings_and_transcripts` into
`alembic_version.version_num` and PostgreSQL raised a `StringDataRightTruncationError`
for the default `VARCHAR(32)` version field.

### Investigation and root cause

The original revision identifier was longer than the default Alembic column
allows. The exact hidden cause of the observed boundary behavior was not
conclusively established, so no claim about invisible characters is made.

### Solution

The migration revision and docstring were changed to the concise,
non-conflicting `0001_meetings_transcripts`; operations and
`down_revision = None` were unchanged.

### Validation

`alembic heads`, `alembic history`, migration execution, and post-migration
schema verification succeeded.

### Engineering Lesson / Interview Talking Point

“Migration identifiers are stored data, not merely filenames. I kept the first
revision short enough for Alembic’s default version table rather than changing
database internals or manually editing migration state.”

## PS-003 — SQLAlchemy enum persistence mismatch

### Context

`MeetingStatus` uses readable Python names (`PENDING`, `PROCESSING`, `READY`,
`FAILED`) but PostgreSQL must store lowercase lifecycle values.

### Investigation and root cause

SQLAlchemy enum persistence can use member names unless configured otherwise.
That would not agree with the migration’s lowercase PostgreSQL enum values.

### Solution

The ORM enum declares `values_callable=lambda enum_cls: [member.value for
member in enum_cls]`; the migration creates exactly `pending`, `processing`,
`ready`, `failed` in that order.

### Validation

The applied enum schema and model tests were checked, and service mapping uses
`.value` at the ORM/Pydantic boundary.

### Engineering Lesson / Interview Talking Point

“I distinguish an enum member’s Python name from its persisted value. The ORM
and migration must agree exactly, especially with a native PostgreSQL enum.”

## PS-004 — Repository transaction ownership

### Context

Repositories and service use cases needed clear transaction boundaries.

### Solution

Repositories only `add`, `execute`, and `flush`. `MeetingService` commits after
successful writes; `get_db_session()` rolls back when an exception propagates.

### Why this solution

A service can later coordinate multiple repositories in one atomic transaction.
A repository-level commit would make that boundary fragmented and harder to
reason about.

### Validation / Interview Talking Point

Repository and service tests assert no repository commits and one successful
service commit. “`flush` sends pending work so constraints/IDs can be observed
inside the transaction; `commit` makes the whole use case durable.”

## PS-005 — Duplicate MeetingStatus definitions

### Context and solution

The ORM and Pydantic layers both define `MeetingStatus`, with matching lowercase
values. The service maps them explicitly by `.value`.

### Why this solution

The two layers have different responsibilities: database persistence and
API/domain contracts. Consolidating ownership may be useful later, but was not
casually mixed into the persistence slice.

### Engineering Lesson

Matching names do not make types interchangeable; explicit conversion makes a
boundary visible and safe.

## PS-006 — Transcript language nullability mismatch

### Context

The migration/ORM permit nullable `Transcript.language`, while `TranscriptInDB`
requires a string.

### Current behavior

`MeetingService` maps stored `NULL` to `"en"` for DTO validity.

### Limitation and future decision

This is internally consistent but not lossless. A later schema decision must
either make the DTO nullable or make the database field non-null with an
appropriate default. Neither option has been selected yet.

### Interview Talking Point

“I documented the mismatch instead of disguising it as complete. The current
normalization protects the API contract, but I would align the two layers before
depending on language fidelity.”

## PS-007 — Test runner, async support, and import-path setup

### Context

Python projects often use pytest and, for async tests, pytest-asyncio. The
project's tests run from the repository root while `backend` is the package root
for shared modules.

### Symptom / consideration

`pytest` was investigated but was not installed. This was not an application
bug. Repository inspection also established that `backend` must be available on
Python's import path for discovery, for example through `PYTHONPATH=backend` or
the equivalent project-specific environment setup.

### Investigation and root cause

Tests use `unittest.TestCase`, `unittest.main()`, and standard discovery. Async
unit tests call `asyncio.run()`; there are no pytest async markers or pytest-style
`async def` tests. Therefore neither pytest nor pytest-asyncio is required.

### Solution and validation

Use `python -m unittest discover -s backend/tests -p "test_*.py"` in an
environment where the backend imports resolve. The existing virtual environment
ran the suite successfully.

### Engineering Lesson / Interview Talking Point

“Async code does not automatically require pytest-asyncio. I checked how this
repository actually executes async tests and used its standard-library runner
and import-path setup rather than adding a test framework by assumption.”

## PS-008 — Fast unit tests without requiring PostgreSQL

### Context

Repositories and services needed behavioral tests without making everyday
development depend on a running database.

### Solution

Repository tests mock `AsyncSession` operations such as `execute` and `flush`.
Service tests mock repositories and session `commit` behavior. They verify query
intent, entity mutation, DTO/ORM mapping, error behavior, and transaction
ownership deterministically and quickly.

### Tradeoff and validation

Mocks cannot prove actual PostgreSQL behavior, so they complement—not replace—
the opt-in PostgreSQL integration test. The default suite skips that integration
test; with `RUN_POSTGRES_INTEGRATION=1`, it can exercise real PostgreSQL. The
skip is expected, not a failure.

### Engineering Lesson / Interview Talking Point

“Unit tests prove the layer contract without a database on every run; the
separate opt-in integration path proves real database connectivity/behavior.
Using both gives fast feedback without mistaking mocks for database validation.”

## PS-009 — Docker availability versus actual PostgreSQL connectivity

### Context

Before the initial migration, the environment had to be identified safely.

### Symptom

Docker was unavailable during inspection, but PostgreSQL was reachable at
`localhost:5432`.

### Investigation and root cause

Docker Compose exposes PostgreSQL on port 5432, but Docker's unavailability
meant the reachable server could not be identified conclusively as the Compose
container. This was an environment diagnosis, not a project failure.

### Solution and validation

The actual configured PostgreSQL connection was inspected and reached using
read-only checks. Database verification and migration work proceeded against
that reachable local instance without assuming Docker ownership.

### Engineering Lesson / Interview Talking Point

“I verified the real connection instead of inferring infrastructure state from
the compose file. A configured port describes an intended path; connectivity
checks establish what is actually available.”

## PS-010 — Phase 3.4 route-test import-path setup

### Problem

The new meeting-route test initially could not import `shared` when run directly.

### Why it happened

Tests execute from the repository root, while `shared` is rooted under
`backend`. Existing meeting repository/service tests already establish that
`backend` must be placed on Python's import path.

### How we diagnosed it

The focused `unittest` run failed before test execution with
`ModuleNotFoundError: No module named 'shared'`. Comparing the new test with the
existing meeting tests showed the missing `BACKEND_ROOT` path insertion.

### Solution

The route test adds `BACKEND_ROOT` to `sys.path` before importing shared modules,
matching the established project test convention.

### Why that solution was chosen

It scopes import setup to the test harness and leaves application import
boundaries unchanged.

### What I learned / interview explanation

“A test runner's working directory is part of the test environment. I aligned
the new test with the repository's existing backend-package setup instead of
changing application imports to accommodate one test command.”

## PS-011 — Route adapter validation without PostgreSQL

### Problem / architectural decision

Phase 3.4 needed to prove HTTP routing, dependency composition, DTO
serialization, and error propagation without duplicating database tests or
requiring a running PostgreSQL instance.

### How we diagnosed the appropriate boundary

The route handlers only delegate to `MeetingService`; repository and service
layers already have their own mock-based tests. FastAPI supports replacing a
dependency for an individual test application.

### Solution

Production resolves `get_meeting_service`, which resolves `get_db_session` and
constructs repositories/service. Route tests override `get_meeting_service` to
inject an `AsyncMock`/`MagicMock` service, then use `TestClient` to make real
HTTP requests to the application.

### Why that solution was chosen

It isolates the HTTP adapter: tests verify the router is mounted, POST returns
201 and serializes `MeetingPublic`, GET forwards the ID, and existing exception
handlers emit standardized 404/422 responses. It does not falsely claim to
validate PostgreSQL behavior; the opt-in integration test remains the real
database check.

### What I learned / interview explanation

“Dependency overrides let me test the route contract at the service boundary.
I can exercise FastAPI validation, response models, and centralized errors with
no database, while retaining separate repository/service and integration tests
for lower layers.”

## PS-012 — Password-hash backend compatibility

### Context and resolution

During authentication work, the bcrypt backend presented a compatibility issue
in the development environment. The password helper uses Passlib's
`pbkdf2_sha256` scheme for new hashes. Passwords remain one-way hashed; this did
not introduce encryption or plaintext storage.

### Engineering lesson / interview talking point

“I choose a password-hashing scheme that works with the actual runtime and
verify behavior in tests. The implementation stores a password hash, never the
password, and isolates the scheme behind helper functions.”

## PS-013 — Malformed stored password hashes fail as authentication

### Context and resolution

`verify_password()` catches Passlib `UnknownHashError` and `ValueError` and
returns `False`. The login service then uses the same generic invalid-email-or-
password response used for a wrong password or unknown email.

### Engineering lesson / interview talking point

“A corrupt or unsupported stored hash is an authentication failure, not a
reason to expose a verifier exception as a server error. The public response
does not reveal which credential check failed.”

## PS-014 — Narrow handling of duplicate-email races

### Context and resolution

Signup and email update handle `IntegrityError` as a conflict only when the
named `uq_users_email` constraint caused it. Other integrity failures propagate
to the normal safe error path rather than being mislabeled as duplicate email.

### Engineering lesson / interview talking point

“Translate a database constraint failure only when its identity matches the
domain case. Catching every integrity error as a conflict would hide unrelated
schema or persistence failures.”

## PS-015 — Service-specific internal-principal key distribution

### Context and correction

The Gateway-to-Meeting boundary requires the Gateway to sign internal
principals and Meeting Service to verify them. Docker Compose was corrected so
the Gateway receives `INTERNAL_PRINCIPAL_PRIVATE_KEY`, Meeting receives only
`INTERNAL_PRINCIPAL_PUBLIC_KEY`, and Meeting no longer receives the shared
`.env` file. Meeting's service port is internal to the Compose network.

### Engineering lesson / interview talking point

“Signing and verification have different trust requirements. Restrict the
private key to the signer and distribute only the public key to verifiers.”

## PS-016 — Refresh-session concurrency and database evidence

### Design

Refresh uses opaque random tokens with SHA-256 hashes at rest. A PostgreSQL
`SELECT ... FOR UPDATE` locks the matching session while the service validates,
revokes, inserts a replacement, and commits. This serializes concurrent use of
one token under PostgreSQL; session state is not global to the user.

### Verification and limitation

Opt-in PostgreSQL tests were added for persistence, rotation/replay, logout,
independent sessions, concurrent refresh, and rollback. During security testing,
the configured database was still at `0001_meetings_transcripts` and lacked the
Phase 4 user/session schema. The opt-in tests were therefore skipped; no
migration was run. Unit tests exercise service-level token behavior, but
concurrency and rotation rollback do not yet have executed PostgreSQL evidence.

### Engineering lesson / interview talking point

“A row-lock statement is a concurrency design, not integration proof. Keep
database tests opt-in for normal development, and state clearly when the live
schema is too old to run them.”

## PS-017 — Wrapped PostgreSQL Summary uniqueness error

### Context and resolution

The Phase 5 PostgreSQL integration check confirmed that PostgreSQL rejects a
duplicate `(meeting_id, version)` Summary. However, the asyncpg/SQLAlchemy
wrapped integrity exception did not expose the constraint name at the location
that `SummaryService` originally inspected. As a result, the service did not
translate the duplicate into its expected `ConflictError`.

`SummaryService` now inspects the wrapped exception causes and diagnostics for
`uq_summaries_meeting_version` before mapping the failure. Other integrity
errors continue to propagate to normal safe error handling. The PostgreSQL
integration test now verifies both the actual unique constraint and the
service-level conflict mapping.

### Engineering lesson / interview talking point

“Database adapters may wrap constraint errors differently. Inspect the
driver's wrapped exception chain and translate only the known domain
constraint; PostgreSQL integration tests verify behavior that mocked errors
cannot.”

## PS-018 — Duplicate operations in directly constructed AI results

### Context and problem

The Phase 6 AI orchestration request contract deduplicates requested
operations while preserving order. During the final adversarial review, the
aggregate `ProcessingResult` contract was found to accept a directly
constructed result whose requested operations and matching operation outcomes
contained duplicates. That allowed an aggregate state the request contract
could never produce through normal orchestration.

### Solution and validation

`ProcessingResult` now rejects duplicate requested operations as part of its
model validation. A regression test constructs a duplicated aggregate and
asserts validation fails. The AI suite passed **91 tests**; the full backend
suite passed with **350 run and 8 skipped**. PostgreSQL integration tests were
skipped because `RUN_POSTGRES_INTEGRATION` was not enabled; no database-backed
claim is made for this fix.

### Engineering lesson / interview talking point

“An aggregate contract should enforce its invariants itself, even if normal
request construction already guarantees them. Validate uniqueness at both the
request and result boundaries.”

## PS-019 — Redis unavailable during live Celery validation

### Context and observed limitation

Phase 9 implemented a Redis-backed Celery broker boundary and a live worker
integration test. Redis was not available in the local development
environment, so the opt-in real-broker test could not be run. Configuration,
message validation, mocked publisher behavior, and worker boundary tests do
not prove live distributed execution.

### Resolution and validation status

The live integration test remains opt-in under
`RUN_REDIS_CELERY_INTEGRATION=1` and requires an already reachable
Redis-compatible broker. Phase 9 documentation records broker execution as
implemented but not live-validated. Docker/Compose remains deferred and was
not changed to supply Redis.

### Engineering lesson / interview talking point

“A configured broker and a passing mocked task test are not evidence that a
real worker can exchange messages through Redis. Keep the real-broker test
available and distinguish implementation from live validation.”

## PS-020 — Queue envelope and trusted worker identity boundary

### Context and decision

Celery messages cross a broker boundary and must remain data-only. The worker
needs an authenticated owner identity to reconstruct the existing Phase 8
execution context, but a queue field such as `user_id` would be producer input
and cannot be treated as authority.

### Solution

The queue accepts a strict primitive envelope containing only job, meeting,
transcript, and operation identifiers. Trusted context, credentials, ORM
state, and AI results are excluded. The producer places a separate signed
authorization alongside that envelope; the worker verifies it and exact
bindings before creating a trusted context. Unsupported free-form context is
rejected rather than silently transported.

### Engineering lesson / interview talking point

“Queue serialization is a trust boundary. Transport the minimum explicit
schema, then reconstruct authority only from a verified credential bound to
that schema.”

## PS-021 — Dedicated RS256 background-job authorization

### Context and decision

Neither the external access JWT nor the Gateway-to-Meeting internal principal
has the intended purpose and binding for a distributed background job. The
worker needs a short-lived assertion that binds the authenticated producer to
one exact job envelope.

### Solution and limitation

Phase 9 uses a dedicated RS256 key pair and authorization purpose, issuer,
audience, lifetime, subject, `jti`, and exact job/meeting/transcript/operation
claims. The worker checks signature and claims before context creation. These
keys are separate from external access-token and internal-principal keys.
`jti` is metadata, not a durable one-time-consumption ledger; persistent job
state limits duplicate execution, but no separate durable replay ledger or
exactly-once guarantee is claimed.

### Engineering lesson / interview talking point

“Use credentials whose audience and purpose match the trust boundary. A
valid user access token is not automatically a valid worker authorization.”

## PS-022 — Durable job lifecycle and PostgreSQL lease fencing

### Context and solution

Celery delivery state alone cannot serve as durable application job state.
Phase 9.4 added the `processing_jobs` PostgreSQL record and migration
`0006_processing_jobs`. The producer registers before publishing; the worker
uses row-locked claims, persisted attempts/retry timing, leases, sanitized
failure state, and terminal results. Fresh lease tokens fence a worker whose
lease expired and was reclaimed. This remains at-least-once execution, not
exactly-once processing.

### Validation

Migration `0006_processing_jobs` is applied at Alembic head. The opt-in
PostgreSQL integration passed **2/2 with no skips**, including concurrent
claims, expired-lease reclamation, persisted attempts and lease replacement,
stale completion/failure rejection, and final persisted state. The lifecycle
suite passed **11/11**. Live Redis execution was not validated because Redis
was unavailable.

### Engineering lesson / interview talking point

“Persist business lifecycle in the application database, use row locks and
lease tokens to coordinate workers, and describe retry delivery as
at-least-once unless every downstream effect is idempotent.”

## PS-023 — PostgreSQL integration fixture omitted required echo setting

### Symptom and root cause

The Phase 9.4 PostgreSQL integration fixture called `init_database()` without
its required keyword-only `echo` argument. The production API and its other
callers already required this setting; the test setup was mismatched.

### Solution and validation

The fixture now passes `settings.database_echo`, consistent with shared
settings and the lifecycle connection setup. No production database behavior
changed. The PostgreSQL integration passed with `RUN_POSTGRES_INTEGRATION=1`
and no skip, and its expanded lease-reclamation/fencing scenario also passed.

### Engineering lesson / interview talking point

“When a fixture violates an existing API contract, align the fixture with the
project setting source instead of weakening production validation to satisfy
the test.”

## PS-024 — Finite AI response contracts do not prove token fit

### Context and decision

The Ollama generation boundary needs finite response limits, but character
counts and item counts are not tokenizer measurements. Ollama 0.40.12 exposes a
non-generation chat-template render path, while the installed model's effective
context and tokenizer parity against its `b11901` runtime remain unverified.

### Solution and limitation

Summary, task, decision, follow-up, insight, and cross-meeting answer schemas now
bound response items and variable-length fields. These caps make validation and
response shape finite; they are not a token reserve. The provider continues to
block before HTTP until complete request tokenization, runtime context, and
per-agent generation limits are verified. No model generation or paid fallback
was added.

### Validation

Mock-only contract-boundary tests reject oversized text and collections. A local
`_debug_render_only` render remains an operator-run check; exact tokenizer parity
and live generation remain unverified.

## PS-025 — Durable jobs must resolve immutable transcript revisions

### Context and decision

The existing `transcripts` table allowed one mutable row per meeting, while a
processing job already records a stable `transcript_id`. Replacing transcript
segments in place could therefore change the input observed by a delayed or
retried job.

### Solution and limitation

Migration `0008_transcript_revisions` retains existing transcript UUIDs as
revision 1, adds a per-meeting revision number and uniqueness constraint, and
allows later edits to append a row under a meeting lock. Worker transcript
resolution now reads the exact revision ID in the signed job. Downgrade refuses
to discard data when any meeting has multiple revisions. This is the persistence
foundation only: idempotent meeting submission, job/outbox creation in one
transaction, and the signed outbox relay remain unimplemented.

### Validation

Mock-only schema, repository, service, AI integration, and trusted-worker tests
pass. A dedicated disposable PostgreSQL migration test covers backfill,
uniqueness, downgrade protection, downgrade, and re-upgrade, but was skipped
because its explicit opt-in was not enabled; live migration behavior remains
unverified.

## PS-026 — Atomic submissions require durable idempotency and an outbox

### Context and decision

Meeting, transcript, and processing-job writes previously used separate service
operations, while publishing before commit could expose a job whose input later
rolled back. The worker already accepts a strict signed envelope and the job
lifecycle is already persisted in `processing_jobs`.

### Solution and limitation

`POST /api/v1/meetings/submit` now derives owner identity from Gateway's
verified principal, checks organization membership, and commits the meeting,
immutable transcript revision, lifecycle row, idempotency record, and pending
outbox event in one transaction. Transaction-scoped advisory locks serialize
same-owner/operation/key attempts; the composite unique index protects the
invariant. The outbox payload is the existing strict envelope, while owner
identity is kept separately for the AI-side signing publisher. No queue call
occurs in the transaction. One-event publication and token-conditional
acknowledgment are described in PS-027. One-shot composition is recorded in
PS-028; polling, scheduling, and retry policy remain pending.

The request rejects transcript text above the existing 100,000-character
sanitization policy instead of silently truncating it. The receipt returns
stable meeting/transcript IDs and initial queued status without exposing signed
authorization or internal job records.

### Validation

Mock-only route/client and request-contract tests cover authentication
forwarding, owner-field rejection, key forwarding, payload hashing, and schema
constraints. An opt-in test against an empty database whose name ends in
`_disposable_test` exercises atomicity, owner isolation, replay/conflict,
rollback, revision immutability, and concurrent duplicates. Its live execution
was not verified in this environment.

## PS-027 — Outbox publication is at-least-once

### Context and decision

The durable outbox needs a broker publication boundary that cannot mark an
event published before Celery accepts its message. The worker already verifies
an AI-signed strict job envelope and uses the job ID for lifecycle idempotency.

### Solution and limitation

The one-event relay publishes outside database transactions, then marks the row
published in a separate transaction only when the same pending event still has
the caller's live lease token. A stale acknowledgment changes no row. The AI
Celery publisher preserves the existing envelope signature, task name, and job
task ID, and propagates the stable outbox UUID in a Celery header. Broker
publication followed by acknowledgment failure can cause redelivery; this is
at-least-once behavior, not exactly-once delivery. Broker failure leaves the
pending lease to expire for later reclaim. No poller, scheduler, or retry
policy is included in this slice.

### Validation

Mock-only tests cover publication/signature identity, failure ordering, stale
lease acknowledgment, database acknowledgment failure, and caller-owned
transactions. The opt-in disposable PostgreSQL test now covers persisted
acknowledgment and stale-token rejection; live execution remains unverified in
this environment.

## PS-028 — Compose one claim per explicit outbox invocation

### Context and decision

The relay accepts a committed event claim, but callers need a safe composition
that creates that claim without holding a transaction open during broker I/O.

### Solution and limitation

`OneShotOutboxRuntime.run_once()` opens the existing Meeting Service session,
claims at most one eligible event in a caller-owned transaction, commits, and
closes the claim session before calling the existing relay. The publisher is
injected through the existing relay boundary, so Meeting Service does not
receive AI signing credentials or new broker configuration. No work returns a
typed `no_work` result. Relay/publish errors propagate after the claim commit;
the durable lease remains pending and can be reclaimed after expiry. Delivery
remains at-least-once. This is an explicit one-shot callable, not a poller,
scheduler, retry policy, or deployed worker entry point.

### Validation

Mock-only tests cover no-work behavior, commit/session-close ordering, lease
forwarding, single-event bounds, and failure propagation. An opt-in disposable
PostgreSQL test verifies the committed lease is visible to the relay and that
one invocation claims only one event; that new case has not been run live in
the current environment.

## PS-029 — Keep outbox authorization separate from user and job identity

### Context and decision

Meeting Service must ask AI Service to sign and publish an outbox event without
receiving the AI job-signing private key or borrowing a Gateway user principal.

### Solution and threat assumptions

The AI-owned `/internal/jobs/outbox-events` endpoint verifies a dedicated,
short-lived RS256 service principal with issuer/subject `meeting-service` and
audience `ai-service:outbox-publication`. Meeting Service holds only its
dedicated assertion private key; AI Service holds its matching verification
public key and separately retains `BACKGROUND_JOB_SIGNING_PRIVATE_KEY`. The
endpoint accepts a strict existing job envelope, validates event type and
event/job identity, then delegates signing and Celery publication to the
existing `CeleryJobSubmissionPort`. Publication errors are sanitized and
propagate through the Meeting Service adapter so the outbox relay does not
acknowledge them. Duplicate requests preserve event UUID and job/task UUID;
the assertion itself is not a one-use replay token.

This trusts Meeting Service to request publication for persisted outbox data
and assumes internal service traffic uses the deployment's protected network
and TLS. Provision a dedicated RSA-2048+ pair through the deployment secret
manager, private in Meeting Service and public in AI Service. Never reuse the
Gateway principal or worker job-authorization keys. Since only one verifier
key is configured, rotate during a dispatch pause by coordinated deployment;
overlapping rotation needs a later `kid`/key-ring design. Compose maps secret
environment variables but does not generate or provision key material.

### Validation

Mocked boundary tests cover authentication, schema and identity rejection,
AI-owned signing, Celery task/header identity, broker failure, duplicate
publication, and request-ID forwarding. Live service-to-service and broker
connectivity are not implied by these tests.

## PS-031 — Persist mapped AI outputs with terminal job state

### Context and decision

The worker already stored the typed aggregate result JSON and terminal lifecycle
state in `processing_jobs`, but successful mapped operation outputs were not
inserted into the existing Summary, Task, Decision, Follow-up, or Meeting Insight
tables. Their owner-scoped Meeting Service APIs therefore could not return the
worker-generated records.

### Solution and failure behavior

The Worker Service runtime now injects the Meeting Service-owned
`persist_processing_result` function into `PostgresJobLifecycle`. On completed
or partial jobs, `ProcessingJobService.complete()` calls it after verifying the
current running lease while still inside the transaction that writes terminal
status and result JSON. It validates meeting/transcript/operation identities
against the registered job and validates each successful output against the
existing shared domain schemas. Successful operations write to the existing
domain tables; failed operations write no domain rows. Summary version numbers
are allocated after locking the meeting row, preserving the existing unique
meeting/version contract. Task assignees and due dates remain only what the
existing mapped contract supplies; no names, IDs, or dates are fabricated.

If persistence or the lifecycle update fails, the database transaction rolls
back both domain rows and terminal result/status. The running job's lease can
then expire for existing lifecycle recovery. Once committed, duplicate delivery
sees terminal state and does not repeat persistence. No migration or public API
contract change was needed; existing authenticated domain endpoints expose the
persisted records.

### Validation and limitations

Mock-backed tests cover all five mapped operation types, identity mismatch,
partial-operation omission, same-transaction lifecycle callback, callback
failure, terminal duplicate no-op, and worker runtime wiring. They do not prove
PostgreSQL transaction behavior or deployed Worker/Meeting connectivity. Exact
Ollama token-budget accounting remains fail-closed, so this work does not claim
that live model generation can currently produce these outputs.

## PS-030 — Invoke outbox dispatch from a Meeting Service command

### Context and decision

The one-shot runtime was callable in tests but had no operational invocation
boundary. Dispatching at API startup would couple request-serving availability
to AI publication, while putting Meeting Service credentials in Worker Service
would cross the established service ownership boundary.

### Solution and operational contract

`app.outbox_dispatch_once` is a Meeting Service-owned command. Invoke it in the
running Meeting Service container with
`docker compose exec meeting-service python -m app.outbox_dispatch_once`. It
initializes Meeting Service database resources, invokes the existing runtime
once, then closes resources on success, no-work, startup/runtime failure, and
shutdown failure paths. Runtime/publish errors remain errors; the command only
prints their type and directs operators to service logs, avoiding exception
text that could contain credentials. API lifespan remains database-only, and
Worker Service task discovery is unchanged. The command uses the existing
`PROCESSING_JOB_LEASE_SECONDS` as `locked_until`; this avoids an ungrounded new
lease setting but means recovery after a publish failure waits for that lease
to expire. No poller, scheduler, or retry policy is included.

### Validation and deployment requirements

Mock-only tests cover one invocation, no-work, failure cleanup, invalid
configuration, sanitized CLI errors, API-startup isolation, and absence from
Worker Service registration. They do not establish live PostgreSQL, AI Service,
service-authentication, or broker connectivity. The Meeting Service container
must have its database URL, AI service URL, and dedicated
`OUTBOX_PUBLICATION_AUTH_PRIVATE_KEY`; the AI Service must have its matching
verification public key and its own background-job signing key. Execute the
command only after those deployment secrets/configuration and the AI/Celery
dependencies have been provisioned.
