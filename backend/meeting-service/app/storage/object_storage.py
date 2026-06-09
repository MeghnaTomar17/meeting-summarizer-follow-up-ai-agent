"""
Purpose: Object storage abstraction (S3-compatible).
Future responsibilities: Upload/download recordings, presigned URLs.
Service ownership: meeting-service.
"""

from __future__ import annotations

from pathlib import Path


class ObjectStorage:
    """S3 adapter placeholder — TODO: boto3 or aioboto3."""

    async def upload_file(self, key: str, local_path: Path, content_type: str) -> str:
        _ = (key, local_path, content_type)
        raise NotImplementedError

    async def get_presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        _ = (key, expires_seconds)
        raise NotImplementedError
