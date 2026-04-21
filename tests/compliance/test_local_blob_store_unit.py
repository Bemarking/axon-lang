"""Unit tests for ``LocalBlobStore``.

The store is a pure I/O wrapper; these tests cover streaming put,
SHA-256 computation, path traversal rejection, and signed_url's
behaviour (returns the file URI).
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import AsyncIterator

import pytest

from axon_enterprise.compliance.errors import ComplianceBackendError
from axon_enterprise.compliance.local_blob_store import LocalBlobStore
from axon_enterprise.config import ComplianceSettings


def _store(tmp_path: Path) -> LocalBlobStore:
    settings = ComplianceSettings(blob_local_path=tmp_path)
    return LocalBlobStore(settings=settings)


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_put_streams_and_computes_sha256(tmp_path: Path) -> None:
    store = _store(tmp_path)
    chunks = [b"hello ", b"world"]
    result = await store.put(key="a/b/out.bin", body=_stream(chunks))

    assert result.size_bytes == len(b"hello world")
    assert result.sha256_hex == hashlib.sha256(b"hello world").hexdigest()
    assert result.uri.startswith("file://")

    dest = tmp_path / "a" / "b" / "out.bin"
    assert dest.read_bytes() == b"hello world"


@pytest.mark.asyncio
async def test_put_rejects_traversal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ComplianceBackendError):
        await store.put(key="../escape.bin", body=_stream([b"x"]))


@pytest.mark.asyncio
async def test_signed_url_returns_file_uri(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.put(key="hello.txt", body=_stream([b"hi"]))
    url = await store.signed_url(key="hello.txt", ttl_seconds=60)
    assert url.startswith("file://")
    assert url.endswith("/hello.txt")


@pytest.mark.asyncio
async def test_delete_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.delete(key="not-here.bin")  # no-op
    await store.put(key="p.bin", body=_stream([b"x"]))
    await store.delete(key="p.bin")
    assert not (tmp_path / "p.bin").exists()
    await store.delete(key="p.bin")  # second delete also OK
