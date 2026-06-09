# PostgreSQL Indexes

> Placeholder index plan — apply via Alembic migrations.

| Table       | Index fields                    | Type     | Notes                        |
|-------------|---------------------------------|----------|------------------------------|
| users       | email                           | UNIQUE   | Login lookup                 |
| users       | organization_id                 | BTREE    | Org member listing           |
| meetings    | organization_id, created_at DESC | BTREE   | Dashboard listing            |
| meetings    | created_by, status              | BTREE    | User-scoped queries          |
| transcripts | meeting_id                      | UNIQUE   | One transcript per meeting   |
| tasks       | meeting_id, status              | BTREE    | Action item boards           |
| tasks       | assignee_id, status             | BTREE    | My tasks view                |
| decisions   | meeting_id                      | BTREE    | Decision timeline            |
| followups   | meeting_id                      | BTREE    | Follow-up drafts             |
| summaries   | meeting_id, version DESC        | BTREE    | Latest summary lookup        |

<!-- TODO: GIN index on transcripts.segments for JSONB search if needed -->
<!-- TODO: pg_trgm extension for fuzzy title search -->
