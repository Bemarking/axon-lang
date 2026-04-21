"""Policy + in-memory backend unit tests (no Docker)."""

from __future__ import annotations

import pytest

from axon_enterprise.config import SecretsSettings
from axon_enterprise.secrets import (
    InMemoryBackend,
    SecretKeyInvalid,
    SecretNotFound,
    SecretsPolicy,
    SecretValue,
    SecretValueTooLarge,
)


# ── Policy ────────────────────────────────────────────────────────────


def _policy(**overrides) -> SecretsPolicy:
    base = dict(
        backend="memory",
        path_prefix="axon/tenants",
        key_min_length=3,
        key_max_length=64,
        key_pattern=r"^[a-z0-9][a-z0-9_-]*$",
        audit_on_read=True,
    )
    base.update(overrides)
    return SecretsPolicy.from_settings(SecretsSettings(**base))


def test_key_normalisation_lowercases_and_strips() -> None:
    p = _policy()
    assert p.normalise_and_validate_key("  OpenAI_Api_Key  ") == "openai_api_key"


def test_key_reject_too_short() -> None:
    with pytest.raises(SecretKeyInvalid, match="key length"):
        _policy().normalise_and_validate_key("ab")


def test_key_reject_too_long() -> None:
    p = _policy(key_max_length=16)
    with pytest.raises(SecretKeyInvalid):
        p.normalise_and_validate_key("a" * 32)


def test_key_reject_disallowed_chars() -> None:
    p = _policy()
    with pytest.raises(SecretKeyInvalid, match="does not match policy"):
        p.normalise_and_validate_key("has space")
    with pytest.raises(SecretKeyInvalid):
        p.normalise_and_validate_key("has/slash")


def test_key_reject_reserved_prefix() -> None:
    p = _policy()
    with pytest.raises(SecretKeyInvalid, match="reserved"):
        p.normalise_and_validate_key("axon_internal")
    with pytest.raises(SecretKeyInvalid):
        p.normalise_and_validate_key("system_key")


def test_tenant_id_rejects_slashes() -> None:
    p = _policy()
    with pytest.raises(SecretKeyInvalid):
        p.validate_tenant_id("alice/admin")


def test_tenant_id_rejects_path_traversal() -> None:
    p = _policy()
    with pytest.raises(SecretKeyInvalid):
        p.validate_tenant_id("..")


def test_build_path_matches_rust_convention() -> None:
    """Must produce the exact path ``TenantSecretsClient`` in Rust expects."""
    p = _policy()
    assert (
        p.build_path("alpha", "anthropic_api_key")
        == "axon/tenants/alpha/anthropic_api_key"
    )


# ── In-memory backend ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_get_roundtrip() -> None:
    be = InMemoryBackend()
    entry = await be.put("axon/tenants/alpha/k", SecretValue("secret"))
    assert entry.path == "axon/tenants/alpha/k"
    assert entry.size_bytes == len("secret")

    value, read_entry = await be.get("axon/tenants/alpha/k")
    assert value.reveal() == "secret"
    assert read_entry.version_id == entry.version_id


@pytest.mark.asyncio
async def test_get_missing_raises_not_found() -> None:
    be = InMemoryBackend()
    with pytest.raises(SecretNotFound):
        await be.get("axon/tenants/alpha/ghost")


@pytest.mark.asyncio
async def test_put_creates_new_version_per_call() -> None:
    be = InMemoryBackend()
    e1 = await be.put("p", SecretValue("one"))
    e2 = await be.put("p", SecretValue("two"))
    assert e1.version_id != e2.version_id
    value, _ = await be.get("p")
    assert value.reveal() == "two"


@pytest.mark.asyncio
async def test_delete_then_get_fails() -> None:
    be = InMemoryBackend()
    await be.put("p", SecretValue("x"))
    await be.delete("p", recovery_window_days=7)
    with pytest.raises(SecretNotFound):
        await be.get("p")


@pytest.mark.asyncio
async def test_delete_missing_raises_not_found() -> None:
    be = InMemoryBackend()
    with pytest.raises(SecretNotFound):
        await be.delete("never", recovery_window_days=7)


@pytest.mark.asyncio
async def test_rotate_replaces_current_version() -> None:
    be = InMemoryBackend()
    await be.put("p", SecretValue("v1"))
    e2 = await be.put("p", SecretValue("v2"))
    e3 = await be.rotate("p", SecretValue("v3"))
    assert e2.version_id != e3.version_id
    value, _ = await be.get("p")
    assert value.reveal() == "v3"


@pytest.mark.asyncio
async def test_rotate_missing_raises_not_found() -> None:
    be = InMemoryBackend()
    with pytest.raises(SecretNotFound):
        await be.rotate("never", SecretValue("x"))


@pytest.mark.asyncio
async def test_put_rejects_oversized_value() -> None:
    be = InMemoryBackend()
    huge = SecretValue("x" * 70_000)
    with pytest.raises(SecretValueTooLarge):
        await be.put("p", huge)


@pytest.mark.asyncio
async def test_exists_reflects_delete() -> None:
    be = InMemoryBackend()
    await be.put("p", SecretValue("x"))
    assert await be.exists("p") is True
    await be.delete("p", recovery_window_days=7)
    assert await be.exists("p") is False
