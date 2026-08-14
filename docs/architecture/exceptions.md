# Exception & Error Handling

> MannerAI Meetings Platform — Phase 2.3 standardized error responses.

## Responsibilities

| Layer | Responsibility |
|-------|----------------|
| Application exceptions | Describe what went wrong |
| Exception handlers | Translate exceptions into HTTP responses |
| Logging (Phase 2.2) | Record tracebacks and request context |

Do not mix these concerns.

## Error envelope

All client-facing errors use:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Meeting not found.",
    "request_id": "abc-123"
  }
}
```

Optional `details` for validation and structured errors:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "request_id": "abc-123",
    "details": [
      {
        "field": "name",
        "message": "String should have at least 3 characters",
        "type": "string_too_short"
      }
    ]
  }
}
```

## Exception hierarchy

```
AppError (base)
├── BadRequestError (400)
├── UnauthorizedError (401)
├── ForbiddenError (403)
├── NotFoundError (404)
├── ConflictError (409)
├── ValidationError (422)
└── ServiceUnavailableError (503)
```

Domain-specific exceptions (e.g. `MeetingNotFoundError`) belong in their owning service and should extend `AppError` in later phases.

## HTTP status mapping

| Exception / source | Status | Code |
|--------------------|--------|------|
| `BadRequestError` | 400 | `BAD_REQUEST` |
| `UnauthorizedError` | 401 | `UNAUTHORIZED` |
| `ForbiddenError` | 403 | `FORBIDDEN` |
| `NotFoundError` | 404 | `NOT_FOUND` |
| `ConflictError` | 409 | `CONFLICT` |
| `ValidationError` / `RequestValidationError` | 422 | `VALIDATION_ERROR` |
| `ServiceUnavailableError` | 503 | `SERVICE_UNAVAILABLE` |
| Unhandled `Exception` | 500 | `INTERNAL_SERVER_ERROR` |
| `HTTPException` | varies | mapped by status (e.g. 401 → `UNAUTHORIZED`) |

## Request ID behavior

- `request_id` comes from Phase 2.2 logging context (`contextvars`)
- Every error response includes `request_id` in the JSON body
- Every error response includes `X-Request-ID` header
- Exception handlers own error response construction (not middleware)

## Safe error-message policy

Never expose to clients:

- Python tracebacks
- Internal exception messages for unexpected errors
- Database errors, file paths, credentials, API keys, JWT secrets

Unexpected errors always return:

```json
{
  "error": {
    "code": "INTERNAL_SERVER_ERROR",
    "message": "An unexpected error occurred.",
    "request_id": "..."
  }
}
```

Full tracebacks are logged server-side via `logger.exception()`.

## Logging integration

| Error type | Logging |
|------------|---------|
| `AppError` (4xx) | INFO, no traceback |
| `AppError` (5xx) | WARNING, no traceback |
| `RequestValidationError` | INFO, structured validation metadata |
| `HTTPException` | INFO, structured metadata |
| Unhandled `Exception` | ERROR with full traceback |

## Developer usage

Raise application errors:

```python
from shared.exceptions.common import NotFoundError

raise NotFoundError("Meeting not found.")
```

Register handlers (done in each service `main.py` via bootstrap):

```python
from shared.utils.service_bootstrap import register_exception_handlers

register_exception_handlers(app)
```

Future service-specific exceptions should extend `AppError` and set a specific `code` when needed.

## Health endpoints

Health endpoints are unchanged and do not use the error envelope on success.
