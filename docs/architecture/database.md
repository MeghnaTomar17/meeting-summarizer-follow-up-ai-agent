# Database Architecture

> MannerAI Meetings Platform — PostgreSQL persistence and initial domain schema.

## Stack

```
FastAPI
  ↓
SQLAlchemy 2.x async (AsyncSession)
  ↓
asyncpg
  ↓
PostgreSQL
```

## Ownership

| Component | Location |
|-----------|----------|
| Declarative Base | `backend/shared/database/base.py` |
| UUID/timestamp mixins | `backend/shared/database/mixins.py` |
| Async engine | `backend/shared/database/engine.py` |
| Session factory + dependency | `backend/shared/database/session.py` |
| Connectivity helper | `backend/shared/database/health.py` |
| ORM models | `backend/shared/database/models/` |
| Alembic migrations | `backend/migrations/` |
| Pydantic API schemas | `backend/shared/schemas/` (separate layer) |

**Phase 2.5:** only `meeting-service` initializes PostgreSQL. Other services do not connect yet.

## Engine vs session

| Object | Scope | Purpose |
|--------|-------|---------|
| `AsyncEngine` | Process-wide singleton | Connection pooling |
| `async_sessionmaker` | Process-wide singleton | Creates sessions |
| `AsyncSession` | Request/task scoped | Unit of work for queries |

The engine is created during application lifespan startup and disposed on shutdown.

## Transaction boundaries

```
Route → Service → Repository → AsyncSession → commit/rollback
```

- `get_db_session()` yields a session but does **not** auto-commit.
- Repositories execute queries; the service layer owns transaction boundaries.
- On exception, the session dependency rolls back before re-raising.

## Configuration

From `SharedSettings` (Phase 2.1):

| Setting | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async connection URL |
| `DATABASE_POOL_SIZE` | `10` | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | `10` | Extra connections beyond pool |
| `DATABASE_POOL_TIMEOUT` | `30` | Seconds to wait for a connection |
| `DATABASE_POOL_RECYCLE` | `1800` | Recycle connections after seconds |
| `DATABASE_ECHO` | `false` | SQLAlchemy echo (dev only) |

Credentials come from `.env` — never logged.

## Health vs readiness

| Endpoint | PostgreSQL check? |
|----------|-------------------|
| `/health` | No |
| `/health/live` | No — process liveness only |
| `/health/ready` | Yes — `SELECT 1` on meeting-service only |

When PostgreSQL is unavailable, meeting-service `/health/ready` returns HTTP 503 with the standardized error envelope.

## Alembic workflow

See [`database/postgresql/migrations.md`](../../database/postgresql/migrations.md).

Run from repository root:

```bash
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
```

## Local PostgreSQL setup

1. Install PostgreSQL 16+ locally.
2. Create the database:

```sql
CREATE DATABASE mannerai_meetings;
```

3. Copy `.env.example` → `.env` and set `DATABASE_URL` with your local credentials.
4. Start meeting-service and verify `/health/ready`.

## Security

- `DATABASE_URL` is in the logging sensitive-field denylist.
- Readiness failures return safe messages — no raw PostgreSQL errors to clients.
- ORM models must not be exposed as API `response_model` — use Pydantic `*Public` schemas.

## ORM model conventions

- UUID primary keys via `UUIDPrimaryKeyMixin`
- Timestamps via `TimestampMixin` (`TIMESTAMPTZ`)
- Business models imported in `shared/database/models/__init__.py` for Alembic discovery
