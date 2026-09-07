# PostgreSQL Indexes

> The three `meetings`/`transcripts` entries are implemented by revision
> `0001_meetings_transcripts`: `ix_meetings_organization_id`,
> `ix_meetings_created_by`, and unique `ix_transcripts_meeting_id`.
> Remaining entries are planning notes and are not yet database indexes.

| Table       | Index fields                    | Type     | Notes                        |
|-------------|---------------------------------|----------|------------------------------|
| users       | email                           | UNIQUE   | Login lookup                 |
| users       | organization_id                 | BTREE    | Org member listing           |
| meetings    | organization_id (`ix_meetings_organization_id`) | BTREE | Implemented org lookup |
| meetings    | created_by (`ix_meetings_created_by`) | BTREE | Implemented creator lookup |
| transcripts | meeting_id (`ix_transcripts_meeting_id`) | UNIQUE BTREE | Implemented one transcript per meeting |
| tasks       | meeting_id, status              | BTREE    | Action item boards           |
| tasks       | assignee_id, status             | BTREE    | My tasks view                |
| decisions   | meeting_id                      | BTREE    | Decision timeline            |
| followups   | meeting_id                      | BTREE    | Follow-up drafts             |
| summaries   | meeting_id, version DESC        | BTREE    | Latest summary lookup        |

<!-- TODO: GIN index on transcripts.segments for JSONB search if needed -->
<!-- TODO: pg_trgm extension for fuzzy title search -->
