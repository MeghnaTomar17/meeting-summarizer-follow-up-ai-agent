# PostgreSQL Tables

> Documentation only — ORM models in `backend/shared/database/models/` (TODO), API DTOs in `backend/shared/models/`.

## users

- **Purpose:** Authentication and profile data.
- **Key columns:** `id` (UUID PK), `email` (unique), `hashed_password`, `organization_id`, `created_at`, `updated_at`.
- **TODO:** `roles`, `is_active`, partial index on active users.

## organizations

- **Purpose:** Multi-tenant workspace boundary.
- **Key columns:** `id` (UUID PK), `name`, `slug` (unique), `created_at`.

## meetings

- **Purpose:** Meeting metadata, status, participants.
- **Key columns:** `id` (UUID PK), `organization_id` (FK), `created_by` (FK → users), `title`, `status`, `scheduled_at`, `created_at`, `updated_at`.
- **TODO:** `recording_url`, `duration_seconds`, soft-delete via `deleted_at`.

## transcripts

- **Purpose:** Transcript metadata per meeting (segments stored as JSONB or normalized child table).
- **Key columns:** `id` (UUID PK), `meeting_id` (FK, unique), `language`, `segments` (JSONB), `created_at`, `updated_at`.
- **TODO:** Consider `transcript_segments` child table for large meetings.

## summaries

- **Purpose:** AI-generated meeting summaries with versioning.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `content`, `key_topics` (JSONB), `version`, `model_provider`, `created_at`.

## tasks

- **Purpose:** Extracted action items.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `title`, `description`, `assignee_id` (FK → users, nullable), `status`, `due_at`, `created_at`, `updated_at`.

## decisions

- **Purpose:** Extracted decisions with context.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `statement`, `context`, `participants` (JSONB), `created_at`.

## followups

- **Purpose:** Follow-up email drafts and delivery state.
- **Key columns:** `id` (UUID PK), `meeting_id` (FK), `subject`, `body_html`, `recipients` (JSONB), `status`, `scheduled_at`, `sent_at`, `created_at`.
