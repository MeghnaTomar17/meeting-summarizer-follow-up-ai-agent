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

Authentication is not implemented yet. Future endpoints under `/api/v1/auth` will issue JWT bearer tokens.

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

## Public route map (planned)

All routes below are gateway-owned under `/api/v1`:

| Prefix | Owning service | Notes |
|--------|----------------|-------|
| `/auth` | gateway-service | Login, register, refresh |
| `/users` | gateway-service | Profiles and administration |
| `/meetings` | gateway → meeting-service | BFF / proxy facade |
| `/search` | gateway → search-service | Semantic search facade |
| `/analytics` | gateway-service | Reporting and insights |
| `/integrations` | gateway-service | Calendar, email, webhooks |

Business endpoints are not active yet. This table documents the approved contract.

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
