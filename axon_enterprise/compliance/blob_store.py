"""BlobStore Protocol — where SAR / evidence bundles land.

Two implementations ship:

    LocalBlobStore   — writes to the filesystem rooted at
                       ``compliance.blob_local_path``. ``signed_url``
                       returns a ``file://`` URI; SHA-256 is computed
                       on write.

    S3BlobStore      — writes to ``s3://{bucket}/{prefix}/{key}``;
                       ``signed_url`` delegates to
                       ``s3.generate_presigned_url('get_object', ...)``
                       with the configured TTL.

Both expose the same two operations: ``put(key, iterable_of_bytes)``
which consumes a streaming body (SAR exports can be multi-GiB per
tenant) and ``signed_url(key)``. Deletion is explicit (``delete``)
and called by retention jobs in 10.m; it is NOT used during normal
erasure flow — an erasure produces a **purge report** blob that
should be retained for the SOC 2 evidence bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterable, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class BlobPutResult:
    """Metadata returned after a successful upload."""

    uri: str
    sha256_hex: str
    size_bytes: int


@runtime_checkable
class BlobStore(Protocol):
    """Durable store for compliance artefacts."""

    async def put(
        self,
        *,
        key: str,
        body: AsyncIterable[bytes],
        content_type: str = "application/octet-stream",
    ) -> BlobPutResult:
        """Stream a body into the store; return its URI + checksum."""
        ...

    async def signed_url(self, *, key: str, ttl_seconds: int) -> str:
        """Return a time-limited URL the tenant admin can fetch."""
        ...

    async def delete(self, *, key: str) -> None:
        """Remove the blob. Idempotent — no-op if the key is absent."""
        ...
