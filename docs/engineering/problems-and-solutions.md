# Engineering Problems and Solutions

This is a factual record of meaningful issues encountered through Phase 5.
It complements the current architecture documents; it does not turn deferred
design choices into completed work.

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
