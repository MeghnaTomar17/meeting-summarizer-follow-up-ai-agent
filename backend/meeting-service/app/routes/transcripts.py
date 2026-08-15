"""
Purpose: Transcript retrieval and ingestion routes.
Future responsibilities: Segment storage, STT callback webhooks.
Service ownership: meeting-service.

NOTE: Semantic/text chunking for embeddings and RAG is owned by search-service
(see search-service/chunking/). This service stores transcript segments and metadata only.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/meetings", tags=["transcripts"])

# TODO: GET /{meeting_id}/transcript
# TODO: PUT /{meeting_id}/transcript — replace segments after processing
