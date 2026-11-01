# API Documentation

> Public API contract for the MannerAI Meetings Platform.

## Base URL

| Environment | Base URL |
|-------------|----------|
| Development (direct gateway) | `http://localhost:8000/api/v1` |
| Development (via nginx) | `http://localhost/api/v1` |
| Production | TBD (behind nginx) |

Health probes are **not** versioned:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`

## Versioning

- **Public API version:** `v1` (URL prefix `/api/v1`)
- **Application version:** `0.1.0` (service build metadata — separate from API version)

The gateway owns the canonical public OpenAPI specification at `/openapi.json`.

## Authentication

Gateway authentication endpoints are implemented:

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/auth/signup` | Register a user; does not automatically create a refresh session |
| POST | `/auth/login` | Validate credentials and return access and refresh tokens |
| POST | `/auth/refresh` | Rotate a refresh token and issue a new token pair; access JWT not required |
| POST | `/auth/logout` | Revoke the supplied refresh session; existing access JWT remains valid until expiry |
| GET | `/auth/me` | Return the authenticated user's public profile |
| GET | `/users/me` | Return the authenticated user's public profile |
| PATCH | `/users/me` | Update the authenticated user's email only |

Login and refresh return `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }`.
Access tokens are short-lived signed JWTs. Refresh tokens are opaque random
values; only their SHA-256 hashes are stored. Invalid credentials and invalid
refresh tokens use generic authentication failures.

## Request correlation

Clients may send `X-Request-ID` on any request. The gateway echoes the resolved ID in the response header and includes it in error responses.

## Error responses

All client-facing errors use the Phase 2.3 envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found.",
    "request_id": "abc-123"
  }
}
```

See `docs/architecture/exceptions.md` for full error semantics.

## Public route map

All routes below are gateway-owned under `/api/v1`:

| Prefix | Owning service | Notes |
|--------|----------------|-------|
| `/auth` | gateway-service | Login, register, refresh |
| `/users` | gateway-service | Profiles and administration |
| `/meetings` | gateway → meeting-service | Authenticated meeting/transcript facade, atomic `POST /meetings/submit`, and meeting result APIs |
| `/search` | gateway → search-service | Semantic search facade |
| `/intelligence/structured-data` | gateway → meeting-service | Owner-scoped, bounded structured evidence across meetings |
| `/intelligence/evidence` | gateway → meeting-service + search-service | Structured and semantic evidence retrieval; no answer generation |
| `/intelligence/questions` | gateway → meeting-service + search-service + ai-service | Evidence-grounded cross-meeting answer with validated citations |
| `/analytics/overview` | gateway → meeting-service | Authenticated owner-scoped dashboard aggregates |
| `/analytics/trends` | gateway → meeting-service | Weekly decision, scheduled-meeting, and persisted-topic trends |
| `/analytics/recurring-blockers` | gateway → meeting-service | Owner-scoped exact-description blocker groups with insight provenance |
| `/analytics/task-completion-trends` | gateway → meeting-service | Explicit capability response for unavailable historical completion events |
| `/analytics/speaker-participation` | gateway → meeting-service | Bounded per-meeting counts of speaker-attributed transcript segments |
| `/integrations` | gateway-service | Calendar, email, webhooks |

Gateway auth, user self-service, and meeting/result facade endpoints are active.
Meeting Service also exposes internal, unversioned meeting routes. Its
organization-wide list route remains internal-only and is not exposed through
the Gateway. The repository now has organizations and memberships, and
`GET /api/v1/organizations/personal` returns the authenticated user's personal
organization. Signup provisions that organization with an owner membership.
`POST /api/v1/meetings` checks membership inside Meeting Service; owner, admin,
and member roles may create meetings. A caller-supplied organization ID alone
is not authorization. Existing meeting organization UUIDs were not mapped to
memberships, so existing meeting access remains creator-scoped. Organization
creation beyond signup, invitations, membership administration, deletion,
ownership transfer, and organization-wide listing are not implemented.

`POST /api/v1/meetings/submit` accepts an `Idempotency-Key` header and a JSON
body containing `meeting`, `transcript`, and `requested_operations`. The
Gateway derives the caller from its authenticated access token and forwards a
short-lived signed Meeting Service principal; owner identity is never accepted
in the body. Meeting Service checks membership and commits the meeting,
immutable transcript revision, queued `processing_jobs` record,
owner-scoped idempotency receipt, and pending `job_outbox_events` row in one
transaction. The response contains only meeting/transcript IDs and the initial
queued status. Repeating an owner/key with the same canonical payload returns
the same receipt; a changed payload returns 409. Keys are 1–255 characters.
Transcript text over 100,000 characters is rejected, never truncated. The
outbox row becomes visible only after commit; a separate one-event relay can
publish a claimed row, but no polling or scheduled relay is wired to this API,
so submission itself does not claim broker delivery.

Transcript `PUT /api/v1/meetings/{meeting_id}/transcript` appends an immutable
transcript revision while retaining the existing `TranscriptInDB` response
shape. Background jobs resolve the exact transcript UUID captured at submission,
even when a later revision is created.

The Phase 5 Meeting contract does not define supported search fields or sort
parameters. The existing internal organization list retains its deterministic
`created_at DESC, id DESC` ordering and pagination. Search and client-selected
sorting remain deferred until their fields and authorization scope are defined.

### Semantic search

`POST /search` is the authenticated Gateway-to-Search Service semantic search
route. Send a bearer access token issued by Gateway and a JSON body containing
`query`, optional `top_k`, and optionally bounded `meeting_ids` to narrow the
search to selected meetings:

```json
{
  "query": "What did we decide about the project budget?",
  "top_k": 10,
  "meeting_ids": ["00000000-0000-0000-0000-000000000001"]
}
```

`query` is trimmed and must contain non-whitespace text (maximum 2000
characters). `top_k` is an integer from 1 through 50 and defaults to 10.
Identity fields, organization scope, and raw vector-store filters are rejected.
`meeting_ids` must contain no more than 100 unique UUIDs; it only narrows the
result set and is always combined with the authenticated owner filter.
Gateway derives the user from its authenticated user record, signs a short-lived
internal principal for the `search-service` audience, and forwards the request
ID when available. Client-supplied identity headers do not set the owner scope.

The response contains `results`, each exposing meeting, transcript and chunk
IDs; chunk index and text; optional language and source timing metadata; and the
Qdrant similarity score. Scores are raw metric scores (higher is more similar),
not probabilities. Owner and organization IDs, embedding metadata, raw payloads
and vectors are omitted. Search filters Qdrant by the verified owner's ID.

This text-query top-k operation is also the current chunk-level similarity
search contract; it does not need a renamed duplicate endpoint. A caller that
needs retrieval-only RAG context can use the same validated `results` as
context, retaining the meeting/transcript/chunk identifiers, source-segment
metadata, timing, language, and score. There is no separate context-packing or
answer-generation API. Search does not send retrieved chunks to an LLM or
generate an answer. Similarity seeded by a selected chunk ID and meeting-level
similarity are not defined contracts; meeting-level aggregation would require
ranking and aggregation semantics that the current API does not specify.

Invalid external or internal credentials return 401; invalid request bodies
return 422. Provider, Qdrant, timeout, or invalid downstream response failures
are returned as sanitized service errors. The live Qdrant repository test is
opt-in; it does not verify a live embedding provider or full Gateway-to-Search
deployment.

### Transcript indexing

`POST /search/meetings/{meeting_id}/index` is the authenticated synchronous
indexing trigger. The public body is empty: the Gateway first fetches the
persisted transcript and authoritative organization ID through Meeting Service's
internal `GET /meetings/{meeting_id}/transcript/index-source`, which applies the
normal creator ownership check. It then forwards that source to Search with a
Gateway-signed Search-audience principal. Search derives `owner_id` exclusively
from the verified principal; caller-supplied owner fields are not accepted.

The result contains meeting/transcript IDs, `indexed` or `empty` status, and a
chunk count. Search prepares the complete embedding batch before initializing
or updating Qdrant. Deterministic point IDs make retries idempotent; the
repository upserts current chunks before deleting stale ones, which is not an
atomic replacement. Missing/inaccessible transcripts fail before Search is
called and are never treated as empty. A genuinely empty persisted transcript
replaces that transcript's indexed point set with an empty set. Provider and
Qdrant failures are sanitized. This path is synchronous; ordinary unit tests
use mocks and require no external API. The Celery `run_embedding_job` remains a
stub. Gateway indexing uses `SEARCH_SERVICE_INDEX_TIMEOUT_SECONDS` (45 seconds
by default), separate from the shorter semantic-search proxy timeout, to allow
the configured embedding operation to finish. Automated integration-style
tests compose the real Search indexing and semantic-search services with the
real Qdrant repository over an in-memory Qdrant client; they cover multi-meeting
owner scope and replacement visibility, but do not verify a live Qdrant server.
The opt-in live Qdrant test verifies only the repository against Qdrant and does
not exercise embeddings or the Gateway. Live embedding-provider and deployed
Gateway-to-Search verification remain separate checks.

### Analytics dashboard

`GET /analytics/overview` returns current owner-scoped dashboard totals and a
weekly meeting series. `weeks` is optional, defaults to 12, and is bounded to
1–52. Weekly buckets are UTC calendar weeks beginning Monday; the response
includes the requested number of chronological buckets through the current
week, including zero-count buckets. Meetings without `scheduled_at` are
excluded from weekly buckets but remain included in `total_meetings`.

Task totals use current persisted status: open tasks are `open` or
`in_progress`; completed tasks are `done`. Overdue tasks have a non-null due
time strictly before the Meeting Service UTC clock and are not `done` or
`cancelled`. Follow-ups include all persisted statuses, with a status breakdown.
Meeting and processing-job status counts are separate and include zero-valued
statuses. All totals are scoped by joining records to meetings owned by the
authenticated user; organization IDs do not grant access.

`GET /analytics/trends` uses the same `weeks` range and UTC Monday calendar
weeks. `decision_trends` groups persisted decisions by `created_at`;
`meeting_frequency` uses the same `scheduled_at` buckets and counts as
`meetings_per_week` in the overview. `topics_per_week` defaults to 10 and is
bounded to 1–25.

`topic_trends` returns one bucket per week, with up to `topics_per_week` exact
topic strings ranked by meeting count descending and then normalized topic
ascending. It reads only the highest-version persisted summary per owned
meeting and assigns topics to the meeting's `scheduled_at` week. Topic strings
are lowercased, trimmed, and internal whitespace is collapsed; repeated
normalized strings in a meeting count once. Non-array topic JSON, non-string
array values, empty strings, and normalized strings longer than 500 characters
are ignored. Similar but non-identical phrases are not semantically merged.
No summaries are regenerated and no LLM is called.

`GET /analytics/recurring-blockers` groups persisted insights whose category is
exactly `blocker`. It trims, lowercases, and collapses whitespace in the
description for exact matching; semantically similar descriptions remain
separate. A group is returned only when the normalized description occurs in
at least two distinct meetings owned by the authenticated user. Groups are
ordered by distinct meeting count descending and normalized description
ascending, and at most 50 groups are returned. Each group includes a stable
SHA-256 identifier derived from the normalized description, its distinct
meeting count, total persisted insight count, and original title/description
plus meeting and insight IDs and insight creation timestamps. Evidence is
ordered to include one reference per meeting before duplicate insights and is
capped at 100 references per group; `evidence_truncated` indicates whether
additional persisted insights were omitted. No transcript content is returned,
no insights are regenerated, and no LLM is called.

`GET /analytics/task-completion-trends` currently returns `available: false`
with a reason. The persisted Task model stores current status and `updated_at`
but no completion timestamp or status-transition history, so it cannot support
historical completion-event buckets. `updated_at` is not treated as completion
time. No date filters or historical counts are returned.

`GET /analytics/speaker-participation` reports per-meeting counts for the most
recent persisted transcripts by meeting creation time. `meetings_limit` defaults
to 50 and is bounded to 1–100. It includes transcripts with no valid segments
as zero-count entries and excludes meetings without a transcript. A segment
counts once per unique nonnegative integer `index` within its transcript; for
duplicate indexes the first JSON-array occurrence is used. Speaker labels are
trimmed and compared case-insensitively within a meeting. Missing, blank, and
`unknown` labels contribute to `unknown_speaker_segment_count`; other labels
are returned with segment counts. Results are per meeting because labels are
not a reliable cross-meeting person identity. Optional timestamps are ignored:
this endpoint does not estimate speaking duration. Transcript text is not
returned. Both meetings and per-meeting speaker lists are bounded, with
truncation flags.

### Cross-meeting structured data

`POST /intelligence/structured-data` returns separate bounded pages of owned
meetings, tasks, decisions, and persisted meeting insights. Its body accepts
`since`, `until`, `task_filter` (`all`, `unresolved`, or `overdue`), `page`,
and `page_size`:

```json
{
  "since": "2026-10-01T00:00:00Z",
  "until": "2026-11-01T00:00:00Z",
  "task_filter": "unresolved",
  "page": 1,
  "page_size": 20
}
```

Each record collection has its own pagination metadata and uses the same page
and page size. Page size is bounded by the shared API maximum. The time window
is inclusive at `since` and exclusive at `until`; it uses `Meeting.scheduled_at`
for meetings and each child record's `created_at` for tasks, decisions, and
insights. Meetings without a schedule are omitted when a time window is used.
`unresolved` includes task statuses `open` and `in_progress`. `overdue` uses
the Meeting Service clock and selects tasks whose `due_at` is earlier than the
current instant and whose status is neither `done` nor `cancelled`; tasks
without due dates are excluded.

Gateway derives the owner from the authenticated external user and signs a
short-lived `meeting-service` internal principal. Meeting Service verifies
that principal and applies owner scope in each database query. Caller-provided
owner identifiers are rejected. The response contains only selected fields
and stable meeting/child IDs for provenance. It omits transcript bodies,
follow-up content, and summary content; summary metadata/content is not needed
by this structured evidence contract.

This boundary supplies structured evidence only. It does not generate
intelligence answers or implement RAG orchestration. Project grouping is not a
first-class entity and can only use existing meeting text in later work.
Recurring-issue detection remains future work. Search Service continues to
own semantic and vector retrieval; this endpoint does not call Qdrant or an
LLM.

### Cross-meeting evidence retrieval

`POST /intelligence/evidence` composes the existing structured-data and
semantic-search contracts. The request nests the existing bounded contracts
so their validation rules remain authoritative:

```json
{
  "semantic": {"query": "What is blocking Project Atlas?", "top_k": 8},
  "structured": {
    "since": "2026-10-01T00:00:00Z",
    "task_filter": "unresolved",
    "page": 1,
    "page_size": 20
  }
}
```

Gateway obtains the owner from its authenticated user context, then calls
Meeting Service and Search Service once each with that same user identity and
the incoming request ID. Each service receives its own Gateway-signed,
audience-bound internal principal. Meeting Service performs the structured
PostgreSQL query; Search Service performs query embedding and owner-filtered
Qdrant retrieval. Gateway validates both responses against their existing
schemas and returns them together as `structured` and `semantic` evidence.

If either call fails or returns malformed data, the request fails with a
sanitized service-unavailable response; this API does not return partial
evidence. An empty response from either source remains empty in the bundle.
The result preserves the meeting/task/decision/insight IDs and meeting
provenance from structured data, plus meeting/transcript/chunk IDs, scores,
and source-segment provenance from semantic results.

This is retrieval-only. It does not parse project names, determine missed
deadlines, classify recurrence, aggregate chunks into meeting similarity, call
an LLM, or generate an answer. The evidence bundle is input for later
reasoning; Search Service continues to own embeddings and vector retrieval.

### Cross-meeting questions

`POST /intelligence/questions` accepts a nonblank `question`, bounded `top_k`,
and the existing structured time-window and task filters. Gateway retrieves
the Block 2 evidence bundle using the authenticated user and request ID, then
forwards that validated bundle to AI Service with an `ai-service` audience-bound
principal. AI Service uses the registered local Ollama adapter and the
structured-output validator. The fail-closed token-budget gate currently blocks
generation because exact rendered-request counting and effective Ollama context
are not verified. The response contains an answer, an
`insufficient_evidence` flag, and citations with source type, stable record ID,
meeting ID, and available timestamp or transcript offsets. Citation metadata
is reconstructed from trusted retrieval results; unknown evidence IDs are
rejected. Empty retrieval returns an explicit insufficient-evidence answer
without calling the provider. Transcript content is untrusted input and cannot
alter system instructions or authorization. Project matching uses only names
and meeting descriptions present in evidence; possible recurring themes must
cite distinct meetings. Citation validation cannot prove every generated
sentence is factually correct.

For questions containing “this month” or “current month”, Gateway derives a
UTC half-open calendar window (`since` inclusive, `until` exclusive) from its
trusted clock. Meeting evidence uses `scheduled_at`; tasks, decisions, and
insights use `created_at`, following Block 1. Semantic chunks are restricted
by Search Service to meeting IDs returned by the month-bounded meeting query.
Overdue and unresolved task questions select the existing `overdue` and
`unresolved` structured filters. Answers about repeated deadline problems
require cited overdue task records from at least two distinct meetings.

### Internal outbox publication (Meeting Service → AI Service)

`POST /internal/jobs/outbox-events` is an AI Service internal endpoint, not a
Gateway public route. It accepts `event_id`, `owner_id`, `job_id`, the existing
`ai.processing.requested.v1` event type, and the strict existing AI job envelope
as `payload`. The outer `job_id` must match `payload.job_id`. A successful
publication returns `202` with the stable `event_id` and `job_id`; AI Service
signs the worker authorization and publishes the existing Celery task. Duplicate
requests are allowed and retain those same identities for at-least-once delivery.

Authentication is a short-lived RS256 service principal issued by Meeting
Service (`iss` and `sub` `meeting-service`) for audience
`ai-service:outbox-publication`. It is separate from Gateway user principals
and AI-to-worker job authorization. Meeting Service holds only the dedicated
service-auth private key; AI Service verifies with its matching public key and
alone holds the background-job signing private key. Deployment key provisioning
and rotation requirements are recorded in the architecture overview.

### Meeting result routes

All routes below are available publicly under `/api/v1` and internally on
Meeting Service without that prefix. Create bodies omit `meeting_id`; the path
is authoritative. Responses use the existing `SummaryInDB`, `TaskInDB`,
`DecisionInDB`, and `FollowupInDB` Pydantic result schemas. Lists use the shared
paginated response envelope (`page`, `page_size`, `total`, `total_pages`).

| Method | Public path | Behavior |
|--------|-------------|----------|
| POST | `/meetings/{meeting_id}/summaries` | Create Summary version 1; duplicate version returns conflict |
| GET | `/meetings/{meeting_id}/summaries` | List Summary versions, paginated |
| GET | `/meetings/{meeting_id}/summaries/latest` | Get highest Summary version |
| GET | `/meetings/{meeting_id}/summaries/{summary_id}` | Get a Summary belonging to this Meeting |
| POST | `/meetings/{meeting_id}/tasks` | Create Task |
| GET | `/meetings/{meeting_id}/tasks` | List Tasks, paginated; optional `?status=` filter |
| GET | `/meetings/{meeting_id}/tasks/{task_id}` | Get a Task belonging to this Meeting |
| PATCH | `/meetings/{meeting_id}/tasks/{task_id}` | Partially update Task fields/status |
| POST | `/meetings/{meeting_id}/decisions` | Create Decision |
| GET | `/meetings/{meeting_id}/decisions` | List Decisions, paginated |
| GET | `/meetings/{meeting_id}/decisions/{decision_id}` | Get a Decision belonging to this Meeting |
| POST | `/meetings/{meeting_id}/followups` | Create FollowUp draft |
| GET | `/meetings/{meeting_id}/followups` | List FollowUps, paginated; optional `?status=` filter |
| GET | `/meetings/{meeting_id}/followups/{followup_id}` | Get a FollowUp belonging to this Meeting |
| PATCH | `/meetings/{meeting_id}/followups/{followup_id}` | Partially update FollowUp fields/status |

The Summary POST body does not currently accept a version field, so the route
uses the service default `1`; it cannot create later versions through HTTP.
The service can create an explicitly supplied version, and the database,
repository, and latest-version lookup support multiple versions. Automatic
version assignment is not implemented.

The Gateway authenticates the external access token, derives the user identity,
and sends a signed internal principal and resolved `X-Request-ID` to Meeting
Service. Meeting Service checks ownership through its domain services. No public
organization-wide Meeting list is exposed; see the authorization decision
above.

## Pagination

List endpoints will accept:

- `?page=1` (default `1`)
- `?page_size=20` (default `20`, maximum `100`)

List responses:

```json
{
  "items": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 0,
    "total_pages": 0
  }
}
```

## Further reading

- `docs/architecture/api-design.md` — full API design conventions
- `docs/architecture/exceptions.md` — error handling
- `docs/architecture/logging.md` — request correlation
