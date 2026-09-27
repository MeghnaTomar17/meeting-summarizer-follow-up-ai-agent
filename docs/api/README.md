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
| `/meetings` | gateway → meeting-service | Authenticated meeting/transcript facade plus Phase 5 summary, task, decision, and follow-up APIs |
| `/search` | gateway → search-service | Semantic search facade |
| `/analytics` | gateway-service | Reporting and insights |
| `/integrations` | gateway-service | Calendar, email, webhooks |

Gateway auth, user self-service, and meeting/result facade endpoints are active.
Meeting Service also exposes internal, unversioned meeting routes. Its
organization-wide list route currently lacks principal and organization
membership checks; it is internal-only and not a public authorization
boundary. Organization membership is not implemented. Phase 5 does not expose
that route through the Gateway: `organization_id` and `created_by` are UUID
columns without organization or user foreign keys, and there is no Organization
or membership model. A public organization list requires a persisted,
authenticated user's organization-membership relationship and an authorization
policy enforced downstream; accepting a caller-supplied organization ID alone
would not be safe. Until that prerequisite exists, the list remains internal.

The Phase 5 Meeting contract does not define supported search fields or sort
parameters. The existing internal organization list retains its deterministic
`created_at DESC, id DESC` ordering and pagination. Search and client-selected
sorting remain deferred until their fields and authorization scope are defined.

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
