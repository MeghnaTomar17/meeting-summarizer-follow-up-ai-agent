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
| PostgreSQL | Authoritative users, Meeting domain data, and durable `processing_jobs` |
| Redis      | Configured Celery broker; Redis cache/session clients remain deferred |
| Qdrant     | Phase 10.4 persistence and Phase 10.5–10.6 owner-filtered retrieval; live local repository retrieval verified |

## PostgreSQL foundation and current domain schema

- Async engine/session in `backend/shared/database/`
- Alembic at repository root (`alembic.ini`, `backend/migrations/`)
- gateway-service owns user and refresh-session persistence; meeting-service owns meetings, transcripts, summaries, tasks, decisions, follow-ups, and the MeetingInsight persistence boundary
- Repository migration chain extends through `0007_organizations_memberships`; the live database revision is environment-dependent and was not verified by this change
- Persisted tables include `users`, `refresh_sessions`, `organizations`, `organization_memberships`, `meetings`, `transcripts`, `summaries`, `tasks`, `decisions`, `followups`, `meeting_insights`, and `processing_jobs`
- Status/category enums include `organization_membership_role`, `meeting_status`, `task_status`, `followup_status`, and `meeting_insight_category`
- Signup provisions a `Personal workspace` organization and `owner` membership with the user in one transaction; supported membership roles are `owner`, `admin`, and `member`
- Meeting Service checks membership for meeting creation. Existing meeting organization UUIDs are preserved without inferred memberships or a foreign key; existing meeting access remains creator-scoped
- Migration downgrade removes organization and membership records only; it leaves user and meeting records intact
- PostgreSQL Phase 9 integration validated durable processing-job persistence, concurrent claims, lease reclaim/fencing, and terminal state at head 0006
- MeetingInsight rows are immutable candidate snapshots; replacement, semantic deduplication, run/version state, and automatic persistence after AI processing are deferred
- `AIProcessingService` returns domain-ready inputs without database/session/repository side effects; an application caller must explicitly decide whether to invoke persistence
- Historical Phase 5 verification was at `0004_meeting_domain_results`; Phase 9 validation subsequently applied and verified `0006_processing_jobs` at head
- PostgreSQL integration tests validated refresh sessions, Phase 5 persistence, summary versions, status filters, `ON DELETE SET NULL`, Meeting-child cascades, and Phase 9 job lifecycle
- Repositories and service/use-case layers use the shared `AsyncSession`
- See [`docs/architecture/database.md`](../architecture/database.md)

## Qdrant design, persistence, and retrieval boundary (through Phase 10.6)

`database/qdrant/collections.md` specifies `meeting_chunks`, its typed payload,
deterministic point identity, vector configuration, and ownership metadata.
The Search Service repository can explicitly initialize the collection,
persist prepared batches, remove stale transcript points, and delete by
transcript or meeting filter. Phase 10.5 adds authenticated retrieval with a
mandatory Qdrant payload filter on `owner_id`, derived from a verified
Gateway-signed Search principal. Search authorization continues to use
creator/owner scope; organization membership does not broaden retrieval access.
PostgreSQL remains authoritative. The opt-in live repository test has verified collection
initialization, deterministic similarity retrieval, owner isolation, and
empty-scope behavior against local Qdrant. It uses a unique temporary test
collection and does not verify embedding-provider connectivity or deployed
Gateway/Search integration.

## TODO

- Backup and restore runbooks (pg_dump / point-in-time recovery)
- Data retention and soft-delete policies
