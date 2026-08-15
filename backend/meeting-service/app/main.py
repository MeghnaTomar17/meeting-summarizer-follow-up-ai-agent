"""
Purpose: FastAPI entrypoint for meeting-service.
Future responsibilities: Upload routes, meeting CRUD, transcript APIs.
Service ownership: meeting-service.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.config.settings import get_settings
from app.database import shutdown_database, startup_database
from shared.database.health import check_postgres_connectivity
from shared.middleware.request_logging import REQUEST_ID_HEADER
from shared.schemas.errors import ErrorBody, ErrorResponse
from shared.utils.health import health_payload
from shared.utils.logging_context import get_log_context
from shared.utils.service_bootstrap import (
    init_service_logging,
    register_exception_handlers,
    register_logging_middleware,
)

init_service_logging(get_settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    await startup_database(settings)
    try:
        yield
    finally:
        await shutdown_database()


app = FastAPI(
    title="MannerAI Meeting Service",
    version="0.1.0",
    description="Meeting CRUD, transcript storage, upload and audio processing.",
    lifespan=lifespan,
)

register_logging_middleware(app)
register_exception_handlers(app)

# TODO: include_router upload, meetings, transcripts
# TODO: lifespan — object storage


def _resolve_request_id(request: Request) -> str:
    context_id = get_log_context().get("request_id")
    if isinstance(context_id, str) and context_id:
        return context_id
    state_id = getattr(request.state, "request_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    return "unknown"


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("meeting-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("meeting-service", version=app.version)


@app.get("/health/ready", response_model=None)
async def health_ready(request: Request):
    if await check_postgres_connectivity():
        return health_payload("meeting-service", version=app.version)

    request_id = _resolve_request_id(request)
    payload = ErrorResponse(
        error=ErrorBody(
            code="SERVICE_UNAVAILABLE",
            message="Required dependencies are unavailable.",
            request_id=request_id,
        )
    )
    response = JSONResponse(
        status_code=503,
        content=payload.model_dump(exclude_none=True),
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
