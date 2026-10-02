# API Design

> MannerAI Meetings Platform — Phase 2.4 public API contract and conventions.

## Public API boundary

| Layer | URL pattern | Audience |
|-------|-------------|----------|
| Gateway public API | `/api/v1/*` | Frontend, external consumers |
| Internal services | unversioned (`/meetings`, `/search`, …) | Gateway, workers (future) |
| Health probes | `/health`, `/health/live`, `/health/ready` | Infrastructure |

The **gateway** is the public API compatibility boundary. Internal service APIs evolve with coordinated deploys and are not directly exposed to clients.

Phase 7 did not introduce a public AI processing endpoint. `AIProcessingService`
is an application-layer contract that accepts a `ProcessingRequest` and a
caller-supplied transcript, then returns typed domain-ready inputs. Existing
Gateway and Meeting domain APIs remain separate; decisions about exposing AI
processing, jobs, and persistence invocation through public or internal APIs
are deferred to later integration phases.

## Versioning

### Public API (`v1`)

- URL versioning at `/api/v1`
- Constant: `shared.api.constants.API_V1_PREFIX`
- Future versions may coexist as `/api/v2` without breaking v1 clients

### Application version vs API version

- **Application version** (`0.1.0`): service build metadata in health responses and OpenAPI `info.version`
- **API version** (`v1`): public contract version in the URL and OpenAPI `info.x-api-version`

These must not be conflated.

### Internal APIs

Internal services use **unversioned** paths. Meeting-service exposes internal
meeting and transcript routes. The gateway authenticates public requests and
forwards supported meeting operations to Meeting Service with a signed
internal-principal bearer assertion.

### API evolution policy

1. Breaking changes require a new public API version (`/api/v2`)
2. Additive changes (new optional fields, new endpoints) are allowed within v1
3. Internal service contracts may change with gateway coordination
4. Deprecation windows should be documented in OpenAPI before removal

## Gateway responsibility

The gateway:

- Owns the canonical public OpenAPI specification
- Authenticates users with access JWTs and applies meeting ownership through the
  downstream service
- Validates and shapes public request/response models
- Proxies supported meeting and transcript operations to Meeting Service
- Forwards `X-Request-ID` to downstream services

Internal services retain minimal OpenAPI for local development and debugging.

## Worker-service HTTP policy

- **Business work:** Celery tasks only
- **HTTP:** health probes (and optional metrics in a future phase)
- No business REST endpoints on worker-service

## Health endpoints

Infrastructure probes, not part of the public business API:

```
GET /health
GET /health/live
GET /health/ready
```

Response shape (unchanged):

```json
{
  "status": "ok",
  "service": "gateway-service",
  "version": "0.1.0",
  "environment": "development"
}
```

Excluded from the public business OpenAPI schema on the gateway.

## Resource naming

| Convention | Example |
|------------|---------|
| Plural nouns for collections | `/meetings`, `/users` |
| snake_case path parameters | `{meeting_id}`, `{user_id}` |
| Nested sub-resources | `/meetings/{meeting_id}/transcript` |
| Action suffixes (non-CRUD) | `POST /meetings/{meeting_id}/process` |

## Nested resources

Prefer nesting genuine sub-resources under their parent:

```
/meetings/{meeting_id}/transcript
/meetings/{meeting_id}/upload
```

Avoid parallel top-level paths when a resource clearly belongs to a parent.

## Action endpoints

Use verb suffixes for operations that are not simple CRUD:

```
POST /meetings/{meeting_id}/process   → 202 Accepted (async job)
```

## Pagination

### List endpoints (offset)

Query parameters:

| Parameter | Default | Constraints |
|-----------|---------|-------------|
| `page` | `1` | `>= 1` |
| `page_size` | `20` | `1`–`100` |

Response envelope:

```json
{
  "items": [...],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 100,
    "total_pages": 5
  }
}
```

Schemas: `shared.schemas.pagination.PaginationParams`, `PaginatedResponse`.

### Search endpoints (limit-based)

Search uses `limit` initially (default 20, max 100). Cursor-based pagination is deferred.

## Filtering and sorting conventions

Not implemented in Phase 2.4. Approved conventions for future list endpoints:

| Concern | Convention |
|---------|------------|
| Equality filters | `?status=ready` |
| Sort ascending | `?sort=scheduled_at` |
| Sort descending | `?sort=-scheduled_at` |
| Date ranges | `scheduled_after`, `scheduled_before` (ISO 8601) |

## Success response conventions

No universal `{"data": ...}` wrapper.

| Operation | Status | Body |
|-----------|--------|------|
| GET single resource | 200 | resource model directly |
| POST create | 201 | created resource directly |
| PATCH update | 200 | updated resource directly |
| DELETE | 204 | empty body |
| Async operation | 202 | `{"job_id": "...", "status": "accepted"}` |
| List | 200 | `{"items": [...], "pagination": {...}}` |
| Search | 200 | search-specific response (TBD) |

## HTTP status conventions

| Code | Usage |
|------|-------|
| 200 | Successful GET, PATCH, list, search |
| 201 | Resource created |
| 202 | Async operation accepted |
| 204 | Successful deletion |
| 400 | Malformed request |
| 401 | Unauthenticated |
| 403 | Forbidden |
| 404 | Resource not found (including unmatched routes) |
| 409 | State conflict |
| 422 | Request validation failure |
| 429 | Rate limited (future — gateway) |
| 500 | Unexpected server error |
| 502 | Gateway upstream failure (future) |
| 503 | Dependency unavailable |
| 504 | Gateway upstream timeout (future) |

## Error response conventions

All client-facing errors use the Phase 2.3 envelope (`shared.schemas.errors.ErrorResponse`):

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found.",
    "request_id": "abc-123"
  }
}
```

Unmatched routes also return this envelope (not Starlette's `{"detail": "Not Found"}`).

## X-Request-ID

- Clients may supply `X-Request-ID`
- Middleware generates a UUID when absent
- Echoed on every response header
- Included in every error response body
- Internal service calls should forward the header (future)

## OpenAPI ownership

| Service | OpenAPI role |
|---------|--------------|
| gateway-service | Canonical public API spec |
| meeting, ai, search, worker | Minimal dev/debug specs |

Gateway OpenAPI includes:

- Platform title and description
- Server URL `/api/v1`
- Tags: auth, users, meetings, search, analytics, integrations
- Shared `ErrorResponse` component
- `X-Request-ID` header documentation
- `info.x-api-version: v1`

Reusable error response definitions: `shared.api.openapi.COMMON_ERROR_RESPONSES`.

## Public schema safety

| Schema | Usage |
|--------|-------|
| `*InDB` | Internal persistence only — never `response_model` |
| `*Public` | Client-facing responses |
| `*Create` / `*Update` | Request bodies |

`UserInDB.password_hash` must never appear in public responses.

`MeetingPublic` excludes internal ownership fields (`organization_id`, `created_by`) present on `MeetingInDB`.

Phase 5 result endpoints currently use the existing Pydantic `SummaryInDB`,
`TaskInDB`, `DecisionInDB`, and `FollowupInDB` DTOs as response models. These
schemas contain result fields and the owning `meeting_id`, but no
authentication secrets or ownership-assigning fields. Phase 5 create request
schemas omit `meeting_id`; the nested route path supplies it. Do not expose ORM
entities directly.

## Router organization

### Gateway (`/api/v1`)

Aggregation point: `gateway-service/app/api/v1/router.py`

Mounted: auth, users, meetings, and meeting result routes. Search, analytics,
and integrations remain unmounted.

### meeting-service (internal)

Routers in `app/routes/`: meetings, upload (nested under `/meetings`), transcripts (nested).

### search-service (internal)

Router in `app/routes/search.py`.

Meeting Service mounts meeting, transcript, summary, task, decision, and
follow-up routes. Result routes are nested under `/meetings/{meeting_id}` and
perform ownership checks in services. The organization-wide Meeting list
remains internal-only: there is no Organization/membership model or
authorization policy, and a client-supplied organization ID is not sufficient
authorization. Phase 5 does not define Meeting search fields or client-selected
sort keys; the internal list retains deterministic `created_at DESC, id DESC`
ordering. Task and FollowUp lists support the existing `status` equality filter.
