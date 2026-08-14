# Logging

> MannerAI Meetings Platform — Phase 2.2 centralized logging.

## Architecture

All five backend services use a shared logging foundation in `backend/shared/utils/`:

- `logger.py` — `configure_logging()`, `get_logger()`, `log_event()`
- `logging_context.py` — `bind_context()` via `contextvars`
- `logging_formatters.py` — development and production formatters
- `service_bootstrap.py` — service startup helpers
- `shared/middleware/request_logging.py` — request ID + request completion logging

Each service initializes logging during startup and registers shared request logging middleware.

## Log levels

Configured through the existing `LOG_LEVEL` setting (`LOG_LEVEL` environment variable).

Supported values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Invalid values are rejected during settings validation and by `configure_logging()`.

## Development vs production formats

| Environment | Format |
|-------------|--------|
| `development` | Human-readable console output |
| `testing` | Human-readable console output |
| `production` | JSON structured logs to stdout |

Example development log:

```text
2026-08-14T17:10:23+00:00 INFO meeting-service request_completed request_id=abc123 method=GET path=/demo status_code=200 duration_ms=4.2
```

Example production log:

```json
{
  "timestamp": "2026-08-14T17:10:23.123456+00:00",
  "level": "INFO",
  "service": "meeting-service",
  "environment": "production",
  "logger": "shared.middleware.request_logging",
  "message": "request_completed",
  "event": "request_completed",
  "request_id": "abc123",
  "method": "GET",
  "path": "/demo",
  "status_code": 200,
  "duration_ms": 4.2
}
```

## Standard structured fields

Always present when configured:

- `timestamp`
- `level`
- `service`
- `environment`
- `logger`
- `message`

Request-scoped fields when available:

- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`

Future-compatible contextual fields:

- `meeting_id`
- `user_id`
- `job_id`
- `task_name`

Use `event` for structured event names such as `request_completed`.

## Service identity

Each service settings class defines `service_name`:

- `gateway-service`
- `meeting-service`
- `ai-service`
- `search-service`
- `worker-service`

`APP_NAME` remains the platform identifier (`mannerai-meetings`).

## X-Request-ID behavior

1. If the client sends `X-Request-ID` and it is valid, it is reused.
2. If the header is missing or invalid, a new UUID is generated.
3. The request ID is stored in request-local logging context.
4. The request ID is returned in the response header `X-Request-ID`.
5. Context is reset after the request completes.

Validation rules:

- Maximum length: 128 characters
- Allowed characters: letters, numbers, `.`, `_`, `-`
- Oversized or invalid values are replaced with a generated UUID

## Sensitive-data logging policy

Never log:

- passwords
- JWT secrets
- API keys
- `Authorization` headers
- cookies
- database connection strings
- Redis connection strings containing credentials
- Qdrant API keys
- raw settings objects
- full request headers
- transcript contents
- audio data

Request logging middleware logs only:

- request ID
- HTTP method
- path
- status code
- duration

Health endpoints (`/health`, `/health/live`, `/health/ready`) do not emit successful INFO request logs.

## Developer usage

Obtain a logger:

```python
from shared.utils.logger import get_logger

logger = get_logger(__name__)
```

Emit a structured event:

```python
from shared.utils.logger import get_logger, log_event
import logging

logger = get_logger(__name__)
log_event(logger, logging.INFO, "meeting_uploaded", "Meeting uploaded", meeting_id=meeting_id)
```

Bind contextual fields:

```python
from shared.utils.logging_context import bind_context

with bind_context(meeting_id=meeting_id, user_id=user_id):
    logger.info("processing meeting")
```

## Uvicorn integration

`configure_logging()` configures the root logger and routes `uvicorn`, `uvicorn.error`, and `uvicorn.access` through the same formatting pipeline.

`uvicorn.access` is elevated to `WARNING` because application middleware owns structured request access logs.
