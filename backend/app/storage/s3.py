"""S3-compatible storage backend (AWS S3 / Cloudflare R2 / MinIO).

Built on ``boto3`` (already pinned in requirements). The boto3
client is sync — we wrap calls in :func:`asyncio.to_thread` so the
event loop stays responsive.

Cloudflare R2 specifics
-----------------------
- ``region_name`` must be ``"auto"``.
- ``endpoint_url`` is ``https://<account_id>.r2.cloudflarestorage.com``.
- ``signature_version`` is ``"s3v4"``.

We pass these through from settings so any S3-compatible API works
without backend-specific code paths.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.storage.base import StorageBackend, StorageError, StoredAsset

log = logging.getLogger(__name__)


class S3StorageBackend(StorageBackend):
    """S3 / S3-compatible bucket implementation.

    The boto3 import is lazy so the local-only test path doesn't
    pull in the AWS SDK on import.
    """

    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        region: str = "auto",
    ) -> None:
        if not bucket:
            raise StorageError("S3StorageBackend requires a bucket name")
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:  # pragma: no cover — boto3 always available
            raise StorageError(
                "boto3 is not installed — run `pip install boto3` "
                "or use ``storage_backend='local'``."
            ) from exc

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region or None,
            config=Config(signature_version="s3v4"),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        mime_type: str,
    ) -> StoredAsset:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=mime_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"S3 put_object failed: {exc}") from exc
        return StoredAsset(key=key, size_bytes=len(data), mime_type=mime_type)

    async def get_bytes(self, key: str) -> bytes:
        try:
            resp = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"S3 get_object failed: {exc}") from exc
        body = resp.get("Body")
        if body is None:
            raise StorageError(f"S3 get_object returned no body for {key}")
        try:
            return await asyncio.to_thread(body.read)
        finally:
            try:
                body.close()
            except Exception:  # noqa: BLE001
                pass

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception as exc:  # noqa: BLE001
            # S3 delete is idempotent server-side; we treat ANY error
            # as a hard failure so the caller can decide.
            raise StorageError(f"S3 delete_object failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception:  # noqa: BLE001
            return False
        return True

    async def presigned_url(
        self,
        key: str,
        *,
        expires_seconds: int = 3600,
    ) -> Optional[str]:
        try:
            return await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=int(expires_seconds),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("S3 presigned_url failed for %s: %s", key, exc)
            return None
