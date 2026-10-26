# Database Migrations

> PostgreSQL schema changes managed with **Alembic** at the repository root.

## Structure

```
alembic.ini
backend/migrations/
  env.py
  script.py.mako
  versions/
```

Alembic uses the canonical SQLAlchemy metadata from `shared.database.base.Base`.

## Local setup

1. Ensure PostgreSQL is running and the `mannerai_meetings` database exists.
2. Configure `DATABASE_URL` in the repository-root `.env` (see `.env.example`).
3. Run commands from the **repository root**.

## Common commands

```bash
# Inspect current revision
alembic -c alembic.ini current

# Show migration history
alembic -c alembic.ini history

# Apply all pending migrations
alembic -c alembic.ini upgrade head

# Create a new revision after an intentional ORM schema change
alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Conventions

- UUID primary keys for domain entities
- `created_at` / `updated_at` as `TIMESTAMPTZ`
- Forward-only migrations in CI; rollbacks documented in runbooks
- One canonical migration system for the entire platform

## Migration head and local database state

The current migration head is `0006_processing_jobs`:

```text
0001_meetings_transcripts
  → 0002_users
    → 0003_refresh_sessions
      → 0004_meeting_domain_results
        → 0005_meeting_insights
          → 0006_processing_jobs
```

`0001_meetings_transcripts` creates the `meeting_status` enum, meeting and
transcript tables, indexes, and cascading transcript-to-meeting foreign key.
`0002_users` adds user identities and password hashes. `0003_refresh_sessions`
adds per-login refresh sessions with hashed tokens, user foreign key, expiry,
revocation, and lookup/cleanup indexes. Each revision has a reversible
downgrade.

At the Phase 4 security-testing checkpoint the configured database reported
`0001_meetings_transcripts`; at the Phase 5 checkpoint it reported
`0004_meeting_domain_results (head)`. Those are historical observations.
Phase 9 validation subsequently applied migrations through
`0006_processing_jobs`; the configured PostgreSQL database was confirmed at
that head. The Phase 9 integration validated durable job persistence and
claim/lease transitions against PostgreSQL.

`0004_meeting_domain_results` creates versioned summaries, tasks, decisions,
and follow-ups with their indexes, foreign keys, and native status enums. Its
downgrade drops dependent tables/indexes before removing the enums.

`0005_meeting_insights` is an additive, reversible migration that creates one
immutable row per insight candidate, with a shared native category enum,
Meeting cascade foreign key, and a meeting-scope index. Its downgrade drops
the index and table before the enum. The migration is applied at the current
database head; its original unapplied status at the Phase 7 checkpoint was
superseded by the Phase 9 migration run.

`0006_processing_jobs` adds PostgreSQL-owned asynchronous job lifecycle,
attempt, retry, lease, failure, and result fields with constraints and indexes.
It is applied and was validated by opt-in PostgreSQL integration tests.

Meeting insight rows have no run/version/replacement semantics in this phase;
repeated or duplicate-looking findings are preserved. Processing status,
versioning, and semantic deduplication remain deferred.

Phase 5 opt-in PostgreSQL integration tests passed (7 total across refresh
session and Meeting-domain persistence coverage). They confirmed Summary
version uniqueness/latest ordering, Task and FollowUp status queries, assignee
`ON DELETE SET NULL`, and Meeting-child `ON DELETE CASCADE` against PostgreSQL.

### Initial migration history

The local development database was checked before migration: it had no
application tables and no `alembic_version` table. The original long revision
identifier, `0001_create_meetings_and_transcripts`, encountered PostgreSQL's
Alembic version-column length boundary during insertion. The revision was
shortened to `0001_meetings_transcripts` (which fits Alembic's default
`VARCHAR(32)` column), then the migration was applied and the resulting schema
was verified. The exact hidden cause of the boundary failure was not
conclusively established; the durable fix was the concise revision ID.

`upgrade()` creates the enum before the tables. `downgrade()` drops the
transcript index/table, meeting indexes/table, then the enum, reversing
dependencies safely.
