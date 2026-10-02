# PostgreSQL Tables

> `users`, `refresh_sessions`, `meetings`, `transcripts`, `summaries`, `tasks`,
> `decisions`, `followups`, and `meeting_insights` are implemented by ORM models in
> `backend/shared/database/models/`; API DTOs remain in `backend/shared/schemas/`.

## Implemented schema

The migration chain implements `users`, `refresh_sessions`, `meetings`,
`transcripts`, `summaries`, `tasks`, `decisions`, `followups`, and
`meeting_insights`, plus the `meeting_status`, `task_status`, `followup_status`,
and `meeting_insight_category` enums. The configured local database was
verified at `0004_meeting_domain_results (head)` after the Phase 5
synchronization. Revision `0005_meeting_insights` is now the code head and has
not been applied; that database therefore has the new insight schema pending.

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

## Implemented result tables (Phase 5)

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

### meeting_insights

- **Purpose:** Persist one qualitative Insight Agent candidate per row.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, cascade delete), `category` (`meeting_insight_category`), `title`, `description`, and `created_at`.
- **Cardinality/lifecycle:** A meeting has zero or many insights. Rows are immutable snapshots with no update/status/version fields. Regeneration may add another row; replacement and semantic deduplication are deferred to a later processing policy.
- **Constraints:** No uniqueness constraint on category/title; similar findings from separate runs remain separate. Meeting ownership is inherited through `meeting_id`.

## Planned tables (not implemented)

### organizations

- **Purpose:** Multi-tenant workspace boundary.
- **Key columns:** `id` (UUID PK), `name`, `slug` (unique), `created_at`.

### meeting_insights

Implemented by revision `0005_meeting_insights`, one row per typed candidate.
There is no run record, processing status, version, or semantic replacement
policy in this phase; repeated candidates are preserved as separate rows.
