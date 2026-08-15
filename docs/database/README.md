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

## PostgreSQL foundation (Phase 2.5)

- Async engine/session in `backend/shared/database/`
- Alembic at repository root (`alembic.ini`, `backend/migrations/`)
- meeting-service integrates database lifespan and readiness
- See [`docs/architecture/database.md`](../architecture/database.md)

## TODO

- First Alembic revision when ORM business models are implemented
- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
