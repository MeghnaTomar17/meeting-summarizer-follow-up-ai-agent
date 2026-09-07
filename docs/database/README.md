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
| PostgreSQL | Users, meetings, transcripts, AI output |
| Redis      | Cache, sessions, Celery broker            |
| Qdrant     | Semantic search over transcript chunks    |

## PostgreSQL foundation and current domain schema (Phases 2.5–3.3)

- Async engine/session in `backend/shared/database/`
- Alembic at repository root (`alembic.ini`, `backend/migrations/`)
- meeting-service integrates database lifespan and readiness
- Initial applied domain revision: `0001_meetings_transcripts`
- Implemented tables: `meetings`, `transcripts`; implemented enum: `meeting_status`
- Repositories and the service/use-case layer use the shared `AsyncSession`
- See [`docs/architecture/database.md`](../architecture/database.md)

## TODO

- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
