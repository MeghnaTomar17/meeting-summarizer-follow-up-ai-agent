# Engineering Problems and Solutions

This is a factual record of meaningful issues encountered through Phase 3.3.
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
