# Architecture Overview

> MannerAI Meetings Platform — scaffolding documentation.

## System context

The platform ingests meeting recordings and transcripts, runs AI pipelines for summaries and extractions, indexes content for semantic search, and exposes a React dashboard via an API gateway.

## Microservices

| Service | Responsibility |
|---------|----------------|
| gateway-service | Auth, routing, validation, public API |
| meeting-service | Meetings, uploads, transcripts, audio processing |
| ai-service | Agents, LLM pipelines, prompts |
| search-service | Embeddings, Qdrant retrieval |
| worker-service | Async jobs (Celery/RQ) |

## Data stores

- **PostgreSQL** — relational transactional data (users, meetings, AI artifacts)
- **Redis** — cache, sessions, Celery broker
- **Qdrant** — vector index for transcript chunks

## Persistence layer

- **SQLAlchemy 2.0 async** + **asyncpg** for PostgreSQL access
- **Alembic** for schema migrations (see `database/postgresql/migrations.md`)
- **Pydantic models** in `backend/shared/models/` for API/domain DTOs
- **SQLAlchemy ORM models** in `backend/shared/database/models/` (TODO)

## TODO

- Sequence diagrams for upload → process → index flow
- Security boundary (internal vs public APIs)
- Multi-tenancy model
