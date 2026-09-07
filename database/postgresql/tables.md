# PostgreSQL Tables

> `meetings` and `transcripts` are implemented by ORM models in
> `backend/shared/database/models/`; API DTOs remain in `backend/shared/schemas/`.

## Implemented schema

Only `meetings`, `transcripts`, and the `meeting_status` enum are implemented
by the current initial migration. The remaining entries are planning notes, not
existing PostgreSQL tables.

### meeting_status enum

Ordered values: `pending`, `processing`, `ready`, `failed`.

## Planned tables (not implemented)

### users

- **Purpose:** Authentication and profile data.
- **Key columns:** `id` (UUID PK), `email` (unique), `hashed_password`, `organization_id`, `created_at`, `updated_at`.
- **TODO:** `roles`, `is_active`, partial index on active users.

### organizations

- **Purpose:** Multi-tenant workspace boundary.
- **Key columns:** `id` (UUID PK), `name`, `slug` (unique), `created_at`.

## Implemented tables

### meetings

- **Purpose:** Meeting metadata, status, participants.
- **Key columns:** `id` (UUID PK), `organization_id`, `created_by`, `title`, `description`, `participants` (JSONB), `status` (`meeting_status` enum), `scheduled_at`, `created_at`, `updated_at`.
- **Current constraint:** `organization_id` and `created_by` are UUID ownership fields; user and organization tables are not modeled yet, so no foreign keys exist for them in the initial revision.
- **Relationship:** one optional transcript, with ORM `delete-orphan` cascade; PostgreSQL deletes a transcript when its meeting is deleted (`ON DELETE CASCADE`).
- **TODO:** `recording_url`, `duration_seconds`, soft-delete via `deleted_at`.

### transcripts

- **Purpose:** Transcript metadata per meeting (segments stored as JSONB or normalized child table).
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, unique), `language`, `segments` (JSONB), `created_at`, `updated_at`.
- **TODO:** Consider `transcript_segments` child table for large meetings.

## Planned tables (not implemented)

### summaries

- **Purpose:** AI-generated meeting summaries with versioning.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `content`, `key_topics` (JSONB), `version`, `model_provider`, `created_at`.

### tasks

- **Purpose:** Extracted action items.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `title`, `description`, `assignee_id` (FK → users, nullable), `status`, `due_at`, `created_at`, `updated_at`.

### decisions

- **Purpose:** Extracted decisions with context.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `statement`, `context`, `participants` (JSONB), `created_at`.

### followups

- **Purpose:** Follow-up email drafts and delivery state.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `subject`, `body_html`, `recipients` (JSONB), `status`, `scheduled_at`, `sent_at`, `created_at`.
