"""
Purpose: Shared constants and enums used across services.
Future responsibilities: HTTP headers, table names, queue names, status codes.
Service ownership: Shared module.
"""

from __future__ import annotations

# PostgreSQL table names
TABLE_USERS = "users"
TABLE_ORGANIZATIONS = "organizations"
TABLE_MEETINGS = "meetings"
TABLE_TRANSCRIPTS = "transcripts"
TABLE_SUMMARIES = "summaries"
TABLE_TASKS = "tasks"
TABLE_DECISIONS = "decisions"
TABLE_FOLLOWUPS = "followups"

# Qdrant
QDRANT_COLLECTION_MEETING_CHUNKS = "meeting_chunks"

# Celery queues — TODO: align with worker-service queue definitions
QUEUE_AI_PROCESSING = "ai.processing"
QUEUE_EMBEDDINGS = "embeddings"
QUEUE_EMAIL = "email"

# Meeting processing statuses
MEETING_STATUS_PENDING = "pending"
MEETING_STATUS_PROCESSING = "processing"
MEETING_STATUS_READY = "ready"
MEETING_STATUS_FAILED = "failed"
