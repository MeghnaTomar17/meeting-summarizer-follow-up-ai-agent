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

## TODO

- Initialize Alembic and first migration revision
- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
