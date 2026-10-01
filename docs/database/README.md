# Database Documentation

## PostgreSQL (primary datastore)

- [`database/postgresql/tables.md`](../../database/postgresql/tables.md)
- [`database/postgresql/indexes.md`](../../database/postgresql/indexes.md)
- [`database/postgresql/migrations.md`](../../database/postgresql/migrations.md)

## Qdrant (vector search)

- [`database/qdrant/collections.md`](../../database/qdrant/collections.md)

## Stack

| Store      | Role                                      |
|------------|-------------------------------------------|
| PostgreSQL | Persisted users and Meeting domain data; AI-result persistence is deferred |
| Redis      | Planned cache/session/Celery broker; not wired to AI processing |
| Qdrant     | Planned semantic search over transcript chunks; not wired |

## PostgreSQL foundation and current domain schema (Phases 2.5–5)

- Async engine/session in `backend/shared/database/`
- Alembic at repository root (`alembic.ini`, `backend/migrations/`)
- gateway-service owns user and refresh-session persistence; meeting-service owns meetings, transcripts, summaries, tasks, decisions, and follow-ups
- Code migration head: `0004_meeting_domain_results` (`0001` → `0002` → `0003` → `0004`)
- Implemented tables: `users`, `refresh_sessions`, `meetings`, `transcripts`, `summaries`, `tasks`, `decisions`, `followups`
- Status enums: `meeting_status`, `task_status`, `followup_status`
- `MeetingInsight` persistence is deferred pending a defined output shape and cardinality
- Configured local development database is at `0004_meeting_domain_results (head)`; `alembic check` reports no pending schema changes
- PostgreSQL integration tests validated refresh sessions, Phase 5 persistence, summary versions, status filters, `ON DELETE SET NULL`, and Meeting-child cascades
- Repositories and service/use-case layers use the shared `AsyncSession`
- See [`docs/architecture/database.md`](../architecture/database.md)

## TODO

- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
