"""
Purpose: Celery task — orchestrate semantic chunking (search-service) and index embeddings in Qdrant.
Future responsibilities: Call search-service indexing APIs.
Service ownership: worker-service.
"""

from __future__ import annotations


def run_embedding_job(meeting_id: str) -> None:
    _ = meeting_id
    raise NotImplementedError
