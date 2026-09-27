"""Provider-independent foundation for future AI processing orchestration."""

from __future__ import annotations

from app.contracts import ProcessingRequest, ProcessingResult, ProcessingStatus


class AIProcessingOrchestrator:
    """Validate the contract and report that execution is not implemented yet.

    This boundary deliberately has no provider, agent, database, or network
    dependency. A later block can inject those collaborators behind this API.
    """

    async def process(self, request: ProcessingRequest) -> ProcessingResult:
        return ProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=ProcessingStatus.NOT_IMPLEMENTED,
            sections={},
        )


__all__ = ["AIProcessingOrchestrator"]
