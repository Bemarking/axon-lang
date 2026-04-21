"""Filesystem-backed BlobStore — development + on-prem deployments.

Rejected by the production settings validator unless the env is
explicitly test/dev. Files land under
``compliance.blob_local_path/{key}``. SHA-256 is computed as the
body streams through so we never hold the full artefact in memory.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterable

from axon_enterprise.compliance.blob_store import BlobPutResult, BlobStore
from axon_enterprise.compliance.errors import ComplianceBackendError
from axon_enterprise.config import ComplianceSettings, get_settings


@dataclass
class LocalBlobStore(BlobStore):
    """Writes blobs under ``settings.blob_local_path``."""

    settings: ComplianceSettings

    @classmethod
    def from_settings(cls) -> LocalBlobStore:
        return cls(settings=get_settings().compliance)

    def _resolve(self, key: str) -> Path:
        if ".." in key.split("/"):
            raise ComplianceBackendError(
                f"rejecting path-traversal attempt in blob key: {key!r}"
            )
        return (self.settings.blob_local_path / key).resolve()

    async def put(
        self,
        *,
        key: str,
        body: AsyncIterable[bytes],
        content_type: str = "application/octet-stream",
    ) -> BlobPutResult:
        dest = self._resolve(key)
        await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)

        sha = hashlib.sha256()
        size = 0

        def _write_chunk(handle, chunk: bytes) -> None:
            handle.write(chunk)

        # Streamed write — keeps memory bounded for multi-GiB SAR
        # exports. ``asyncio.to_thread`` guarantees we don't block
        # the event loop on disk I/O.
        handle = await asyncio.to_thread(open, dest, "wb")
        try:
            async for chunk in body:
                if not chunk:
                    continue
                sha.update(chunk)
                size += len(chunk)
                await asyncio.to_thread(_write_chunk, handle, chunk)
        finally:
            await asyncio.to_thread(handle.close)

        return BlobPutResult(
            uri=dest.as_uri(),
            sha256_hex=sha.hexdigest(),
            size_bytes=size,
        )

    async def signed_url(self, *, key: str, ttl_seconds: int) -> str:
        # Local store cannot sign URLs — the tenant admin is assumed
        # to have filesystem access (CLI / ops runbook). The URI is
        # still stable so operators can copy the file manually.
        return self._resolve(key).as_uri()

    async def delete(self, *, key: str) -> None:
        dest = self._resolve(key)
        if await asyncio.to_thread(dest.exists):
            await asyncio.to_thread(dest.unlink)
