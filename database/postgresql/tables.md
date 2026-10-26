# PostgreSQL Tables

> `users`, `refresh_sessions`, `meetings`, `transcripts`, `summaries`, `tasks`,
> `decisions`, `followups`, `meeting_insights`, and `processing_jobs` are implemented by ORM models in
> `backend/shared/database/models/`; API DTOs remain in `backend/shared/schemas/`.

## Implemented schema

The migration chain through Phase 9 defines `users`, `refresh_sessions`, `meetings`,
`transcripts`, `summaries`, `tasks`, `decisions`, `followups`, and
`meeting_insights`, and `processing_jobs`, plus the `meeting_status`,
`task_status`, `followup_status`, and `meeting_insight_category` enums. The
configured PostgreSQL database is at Alembic head `0006_processing_jobs`;
revisions 0005 and 0006 are applied. The Phase 5 notes below describe the
historical 0004 checkpoint.

### meeting_status enum

Ordered values: `pending`, `processing`, `ready`, `failed`.

### task_status and followup_status enums

`task_status`: `open`, `in_progress`, `done`, `cancelled`.
`followup_status`: `draft`, `scheduled`, `sent`, `failed`.

### meeting_insight_category enum

Ordered values: `risk`, `blocker`, `concern`, `opportunity`, `dependency`,
`unresolved`, `disagreement`, `observation`. The shared `InsightCategory`
contract supplies the same values to AI validation and ORM persistence.

## Implemented tables

### users

- **Purpose:** Authentication and profile data.
- **Key columns:** `id` (UUID PK), `email` (unique), `password_hash`, `created_at`, `updated_at`.
- Passwords are persisted as hashes; roles, account status, and organization membership are not implemented.

### refresh_sessions

- **Purpose:** One independently revocable refresh session per login.
- **Key columns:** `id` (UUID PK), `user_id` (FK → users, `ON DELETE CASCADE`), `token_hash` (unique SHA-256 digest), `expires_at`, `revoked_at` (nullable).
- The raw opaque refresh token is returned only at login/rotation and is never stored.

### meetings

- **Purpose:** Meeting metadata, status, participants.
- **Key columns:** `id` (UUID PK), `organization_id`, `created_by`, `title`, `description`, `participants` (JSONB), `status` (`meeting_status` enum), `scheduled_at`, `created_at`, `updated_at`.
- **Current constraint:** The initial meeting revision stores `organization_id` and `created_by` as UUID ownership fields without foreign keys. A user table now exists, but there is no ownership foreign-key migration; organizations are not modeled.
- **Relationship:** one optional transcript, with ORM `delete-orphan` cascade; PostgreSQL deletes a transcript when its meeting is deleted (`ON DELETE CASCADE`).
- **TODO:** `recording_url`, `duration_seconds`, soft-delete via `deleted_at`.

### transcripts

- **Purpose:** Transcript metadata per meeting (segments stored as JSONB or normalized child table).
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, unique), `language`, `segments` (JSONB), `created_at`, `updated_at`.
- **TODO:** Consider `transcript_segments` child table for large meetings.

## Phase 5 result tables

Revision `0004_meeting_domain_results` is applied to the configured development
database and was validated by PostgreSQL integration tests.

### summaries

- **Purpose:** AI-generated meeting summaries with versioning.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, cascade delete), `content`, `key_topics` (JSONB), nullable `model_provider` and `model_name`, positive `version` (default 1), `created_at`.
- **Cardinality/constraints:** A meeting has zero or many summary versions; `(meeting_id, version)` is unique. A descending version index supports latest-version lookup.

### tasks

- **Purpose:** Meeting action items with assignment and workflow state.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, cascade delete), `title`, nullable `description`, nullable `assignee_id` (FK → users, set null on user deletion), nullable `due_at`, `status` (`task_status`, default `open`), `created_at`, `updated_at`.
- **Cardinality/indexes:** A meeting has zero or many tasks. Composite indexes support meeting/status and assignee/status queries.

### decisions

- **Purpose:** Decisions recorded from meeting discourse.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, cascade delete), `statement`, nullable `context`, `participants` (JSONB string list), `created_at`.
- **Cardinality:** A meeting has zero or many decisions.

### followups

- **Purpose:** Reviewable generated follow-up email drafts and delivery state.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, cascade delete), `subject`, `body_html`, `recipients` (JSONB email list), `status` (`followup_status`, default `draft`), nullable `scheduled_at` and `sent_at`, `created_at`.
- **Cardinality:** A meeting has zero or many follow-ups; no unique draft-per-meeting constraint is imposed.

## MeetingInsight table (Phase 7.4)

Revision `0005_meeting_insights` adds the following table. It is included in
the current PostgreSQL schema at head `0006_processing_jobs`.

### meeting_insights

- **Purpose:** Persist one qualitative Insight Agent candidate per row when a caller explicitly invokes the persistence boundary.
- **Columns:** `id UUID NOT NULL` (primary key, supplied by `UUIDPrimaryKeyMixin`); `meeting_id UUID NOT NULL`; `category meeting_insight_category NOT NULL`; `title TEXT NOT NULL`; `description TEXT NOT NULL`; `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
- **Foreign key:** `fk_meeting_insights_meeting_id_meetings` references `meetings.id` with `ON DELETE CASCADE`.
- **Relationship:** Meeting has zero or many insights; the ORM relationship uses `cascade="all, delete-orphan"`.
- **Lifecycle/constraints:** Immutable candidate snapshot; no `updated_at`, status, version, run ID, or provider metadata. No category/title uniqueness constraint or semantic deduplication; similar findings from different runs may coexist.
- **Migration state:** Applied in `0005_meeting_insights`; subsequently validated as part of the PostgreSQL schema at head 0006.

## Processing jobs (Phase 9.4)

- **Purpose:** Durable application lifecycle for asynchronous AI jobs; PostgreSQL, not Celery task state, is authoritative.
- **Key columns:** `job_id` (UUID PK), `meeting_id`, `transcript_id`, `owner_id`, requested operations, status, attempt counts, lease token/expiry, retry timing, sanitized failure fields, result, and lifecycle timestamps.
- **Constraints/indexes:** Status/attempt/lease/completion invariants; indexes support status/creation, owner/creation, and meeting lookup.
- **Migration state:** Applied and PostgreSQL-validated in `0006_processing_jobs`.

## Vector representation (Phase 10.1)

Transcript chunks are specified as a Qdrant projection in
[`../qdrant/collections.md`](../qdrant/collections.md), not as PostgreSQL
domain rows. No PostgreSQL vector table or migration is part of Phase 10.1.

## Planned tables (not implemented)

### organizations

- **Purpose:** Multi-tenant workspace boundary.
- **Key columns:** `id` (UUID PK), `name`, `slug` (unique), `created_at`.
