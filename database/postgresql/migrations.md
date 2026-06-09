# Database Migrations

> PostgreSQL schema changes managed with **Alembic** (TODO: initialize at repo root or under `backend/`).

## Conventions

- UUID primary keys (`gen_random_uuid()` via `pgcrypto` or application-generated).
- `created_at` / `updated_at` timestamps with timezone (`TIMESTAMPTZ`).
- Foreign keys with `ON DELETE CASCADE` where child rows are owned by parent meeting.
- Migrations are forward-only in CI; rollbacks documented in runbooks.

## TODO

- `alembic init backend/migrations`
- Initial revision: users, organizations, meetings, transcripts, summaries, tasks, decisions, followups
- Seed script for local development
