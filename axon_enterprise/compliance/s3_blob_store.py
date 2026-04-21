"""AWS S3 BlobStore — production durable storage.

Streams a put via ``boto3.s3.upload_fileobj`` (wrapped in
``asyncio.to_thread``) so the SAR export never materialises in
memory. Presigned URLs are produced via
``s3.generate_presigned_url`` with the tenant-configured TTL.

Retention / object lock is provisioned at the bucket level in
Terraform (Fase 10.m); the application never issues
``DeleteObject`` unless the CLI explicitly runs a retention job.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from dataclasses import dataclass
from typing import AsyncIterable

import structlog

from axon_enterprise.compliance.blob_store import BlobPutResult, BlobStore
from axon_enterprise.compliance.errors import ComplianceBackendError
from axon_enterprise.config import ComplianceSettings, get_settings

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.s3"
)


@dataclass
class S3BlobStore(BlobStore):
    """boto3-backed implementation."""

    settings: ComplianceSettings

    @classmethod
    def from_settings(cls) -> S3BlobStore:
        return cls(settings=get_settings().compliance)

    def _object_key(self, key: str) -> str:
        prefix = self.settings.blob_s3_prefix.strip("/")
        return f"{prefix}/{key}" if prefix else key

    def _client(self):
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ComplianceBackendError(
                "boto3 required for S3 blob store; install via "
                "`pip install 'axon-enterprise[aws]'`"
            ) from exc
        return boto3.client("s3")

    async def put(
        self,
        *,
        key: str,
        body: AsyncIterable[bytes],
        content_type: str = "application/octet-stream",
    ) -> BlobPutResult:
        if not self.settings.blob_s3_bucket:
            raise ComplianceBackendError("compliance.blob_s3_bucket unset")

        bucket = self.settings.blob_s3_bucket
        object_key = self._object_key(key)

        # Buffer to a tempfile so upload_fileobj can seek. SAR
        # exports are already gzip-compressed; multi-GiB is rare but
        # supported. The tempfile is unlinked on close.
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            delete=False, prefix="axon-compliance-", suffix=".part"
        )
        sha = hashlib.sha256()
        size = 0
        try:
            try:
                async for chunk in body:
                    if not chunk:
                        continue
                    sha.update(chunk)
                    size += len(chunk)
                    await asyncio.to_thread(tmp.write, chunk)
            finally:
                await asyncio.to_thread(tmp.close)
            client = self._client()
            await asyncio.to_thread(
                client.upload_file,
                tmp.name,
                bucket,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as exc:
            raise ComplianceBackendError(
                f"S3 upload failed: {exc}"
            ) from exc
        finally:
            import os as _os
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

        _logger.info(
            "compliance_blob_uploaded",
            bucket=bucket,
            key=object_key,
            size_bytes=size,
        )
        return BlobPutResult(
            uri=f"s3://{bucket}/{object_key}",
            sha256_hex=sha.hexdigest(),
            size_bytes=size,
        )

    async def signed_url(self, *, key: str, ttl_seconds: int) -> str:
        if not self.settings.blob_s3_bucket:
            raise ComplianceBackendError("compliance.blob_s3_bucket unset")
        client = self._client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.settings.blob_s3_bucket,
                "Key": self._object_key(key),
            },
            ExpiresIn=ttl_seconds,
        )

    async def delete(self, *, key: str) -> None:
        if not self.settings.blob_s3_bucket:
            raise ComplianceBackendError("compliance.blob_s3_bucket unset")
        client = self._client()
        await asyncio.to_thread(
            client.delete_object,
            Bucket=self.settings.blob_s3_bucket,
            Key=self._object_key(key),
        )


def build_blob_store() -> BlobStore:
    """Factory — picks backend from settings."""
    s = get_settings().compliance
    if s.blob_backend == "s3":
        return S3BlobStore(settings=s)
    from axon_enterprise.compliance.local_blob_store import LocalBlobStore

    return LocalBlobStore(settings=s)
