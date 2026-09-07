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

# Create a new revision (when ORM models exist)
alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Conventions

- UUID primary keys for domain entities
- `created_at` / `updated_at` as `TIMESTAMPTZ`
- Forward-only migrations in CI; rollbacks documented in runbooks
- One canonical migration system for the entire platform

## Current revision

`0001_meetings_transcripts` is the initial domain-schema revision. It
creates the `meeting_status` PostgreSQL enum, the `meetings` and `transcripts`
tables, their lookup indexes, and the cascading transcript-to-meeting foreign
key. It has not been applied automatically; use `upgrade head` against an
intended PostgreSQL database.
