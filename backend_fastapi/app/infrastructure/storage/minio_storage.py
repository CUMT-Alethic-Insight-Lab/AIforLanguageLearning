"""MinIO 文件存储封装"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

_MINIO_IMPORT_ERROR: str | None = None


def is_minio_available() -> bool:
    """Check whether the MinIO SDK is installed."""
    global _MINIO_IMPORT_ERROR
    if _MINIO_IMPORT_ERROR:
        return False
    try:
        import minio  # noqa: F401
        return True
    except ImportError as e:
        _MINIO_IMPORT_ERROR = str(e)
        return False


@dataclass
class UploadResult:
    bucket: str
    object_key: str
    etag: str
    presigned_url: str | None = None


class MinIOStorage:
    """MinIO 异步存储封装（在线程池中执行同步 SDK）"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ):
        try:
            from minio import Minio
        except ImportError as e:
            raise RuntimeError(
                "MinIO SDK is not installed. Install with: pip install minio"
            ) from e
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def ensure_bucket(self, bucket: str) -> None:
        exists = await self._run(self.client.bucket_exists, bucket)
        if not exists:
            await self._run(self.client.make_bucket, bucket)
            logger.info(f"Created MinIO bucket: {bucket}")

    async def upload(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> UploadResult:
        await self.ensure_bucket(bucket)
        from io import BytesIO

        stream = BytesIO(data)
        result = await self._run(
            self.client.put_object,
            bucket,
            key,
            stream,
            len(data),
            content_type=content_type,
        )
        return UploadResult(bucket=bucket, object_key=key, etag=result.etag)

    async def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        expires: int = 3600,
    ) -> str:
        return await self._run(
            self.client.presigned_get_object,
            bucket,
            key,
            timedelta(seconds=expires),
        )

    async def initiate_multipart_upload(
        self,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        await self.ensure_bucket(bucket)
        result = await self._run(
            self.client.create_multipart_upload,
            bucket,
            key,
        )
        return result

    async def complete_multipart_upload(
        self,
        bucket: str,
        key: str,
        upload_id: str,
        parts: list[Any],
    ) -> UploadResult:
        result = await self._run(
            self.client.complete_multipart_upload,
            bucket,
            key,
            upload_id,
            parts,
        )
        return UploadResult(bucket=bucket, object_key=key, etag=result.etag)

    async def delete_object(self, bucket: str, key: str) -> None:
        await self._run(self.client.remove_object, bucket, key)


_storage: MinIOStorage | None = None


def get_minio_storage() -> MinIOStorage | None:
    global _storage
    if _storage is None:
        if not is_minio_available():
            logger.warning("MinIO SDK not available; storage features disabled.")
            return None
        from app.settings import settings

        endpoint = getattr(settings, "minio_endpoint", "localhost:9000")
        access_key = getattr(settings, "minio_access_key", "minioadmin")
        secret_key = getattr(settings, "minio_secret_key", "minioadmin")
        try:
            _storage = MinIOStorage(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=False,
            )
        except RuntimeError:
            logger.warning("MinIO SDK not available; storage features disabled.")
            return None
    return _storage
