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
| PostgreSQL | Persisted users and Meeting domain data, including MeetingInsight candidates |
| Redis      | Planned cache/session/Celery broker; not wired to AI processing |
| Qdrant     | Planned semantic search over transcript chunks; not wired |

## PostgreSQL foundation and current domain schema (Phases 2.5–7)

- Async engine/session in `backend/shared/database/`
- Alembic at repository root (`alembic.ini`, `backend/migrations/`)
- gateway-service owns user and refresh-session persistence; meeting-service owns meetings, transcripts, summaries, tasks, decisions, follow-ups, and the MeetingInsight persistence boundary
- Code migration head: `0005_meeting_insights` (`0001` → `0002` → `0003` → `0004` → `0005`)
- ORM/migration-defined tables: `users`, `refresh_sessions`, `meetings`, `transcripts`, `summaries`, `tasks`, `decisions`, `followups`, `meeting_insights` (`meeting_insights` awaits migration 0005)
- Status/category enums: `meeting_status`, `task_status`, `followup_status`, `meeting_insight_category`
- MeetingInsight ORM/schema/repository and additive migration `0005_meeting_insights` are defined; the migration is currently unapplied and has not been validated against PostgreSQL
- MeetingInsight rows are immutable candidate snapshots; replacement, semantic deduplication, run/version state, and automatic persistence after AI processing are deferred
- `AIProcessingService` returns domain-ready inputs without database/session/repository side effects; an application caller must explicitly decide whether to invoke persistence
- The configured local development database was last verified at `0004_meeting_domain_results`; migration `0005_meeting_insights` remains pending
- PostgreSQL integration tests validated refresh sessions, Phase 5 persistence, summary versions, status filters, `ON DELETE SET NULL`, and Meeting-child cascades
- Repositories and service/use-case layers use the shared `AsyncSession`
- See [`docs/architecture/database.md`](../architecture/database.md)

## TODO

- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
