# PostgreSQL Indexes

> The user/session entries are created by revisions `0002_users` and
> `0003_refresh_sessions`; meeting/transcript entries are created by
> `0001_meetings_transcripts`; Phase 5 result-table indexes are created by
> `0004_meeting_domain_results`, applied to the configured development DB.

| Table       | Index fields                    | Type     | Notes                        |
|-------------|---------------------------------|----------|------------------------------|
| users       | email                           | UNIQUE   | Login lookup                 |
| refresh_sessions | token_hash                  | UNIQUE   | Opaque refresh-token lookup  |
| refresh_sessions | user_id                     | BTREE    | Session ownership / cleanup  |
| refresh_sessions | expires_at                  | BTREE    | Expiration cleanup           |
| meetings    | organization_id (`ix_meetings_organization_id`) | BTREE | Implemented org lookup |
| meetings    | created_by (`ix_meetings_created_by`) | BTREE | Implemented creator lookup |
| transcripts | meeting_id (`ix_transcripts_meeting_id`) | UNIQUE BTREE | Implemented one transcript per meeting |
| summaries   | meeting_id, version (`uq_summaries_meeting_version`) | UNIQUE BTREE | One row per version per meeting |
| summaries   | meeting_id, version DESC (`ix_summaries_meeting_version_desc`) | BTREE | Latest summary lookup |
| tasks       | meeting_id, status (`ix_tasks_meeting_status`) | BTREE | Action item boards |
| tasks       | assignee_id, status (`ix_tasks_assignee_status`) | BTREE | My tasks view |
| decisions   | meeting_id (`ix_decisions_meeting_id`) | BTREE | Decision timeline |
| followups   | meeting_id (`ix_followups_meeting_id`) | BTREE | Follow-up drafts |

<!-- TODO: GIN index on transcripts.segments for JSONB search if needed -->
<!-- TODO: pg_trgm extension for fuzzy title search -->
