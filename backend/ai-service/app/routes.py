"""Authenticated internal cross-meeting answer endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from fastapi import APIRouter, Depends

from app.auth import get_authenticated_user_id
from app.config.settings import AISettings, get_settings
from app.cross_meeting_answers import CrossMeetingAnswerService
from llm.openai_client import OpenAIModelProvider
from shared.schemas.cross_meeting import (
    CrossMeetingAnswerGenerationRequest,
    CrossMeetingQuestionResponse,
)
from shared.exceptions.common import ServiceUnavailableError

router = APIRouter(prefix="/internal/intelligence", tags=["internal-intelligence"])


async def get_answer_service(
    settings: AISettings = Depends(get_settings),
) -> AsyncIterator[CrossMeetingAnswerService]:
    provider = OpenAIModelProvider.from_settings(settings)
    try:
        yield CrossMeetingAnswerService(provider)
    finally:
        await provider.aclose()


@router.post("/answers", response_model=CrossMeetingQuestionResponse)
async def answer_question(
    payload: CrossMeetingAnswerGenerationRequest,
    _user_id=Depends(get_authenticated_user_id),
    service: CrossMeetingAnswerService = Depends(get_answer_service),
) -> CrossMeetingQuestionResponse:
    try:
        return await service.answer(payload)
    except Exception:
        raise ServiceUnavailableError("The answer service is unavailable.") from None


__all__ = ["router", "get_answer_service"]
