"""Unit tests for the canonical JSON + hash chain primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from axon_enterprise.audit.canonical import (
    GENESIS_MAGIC,
    canonical_bytes_for_hash,
    compute_event_hash,
    genesis_hash,
)


# ── canonical_bytes_for_hash ─────────────────────────────────────────


def test_canonical_is_sorted_keys() -> None:
    assert canonical_bytes_for_hash({"b": 1, "a": 2}) == canonical_bytes_for_hash(
        {"a": 2, "b": 1}
    )


def test_canonical_uses_compact_separators() -> None:
    assert (
        canonical_bytes_for_hash({"a": 1, "b": 2})
        == b'{"a":1,"b":2}'
    )


def test_canonical_ensures_ascii() -> None:
    # Non-ASCII characters are escaped as \uXXXX.
    raw = canonical_bytes_for_hash({"name": "Álvaro"})
    assert b"\\u00c1lvaro" in raw or b"\\u00C1lvaro" in raw


def test_canonical_serialises_uuid_as_string() -> None:
    uid = UUID("00000000-0000-0000-0000-000000000042")
    raw = canonical_bytes_for_hash({"id": uid})
    decoded = json.loads(raw)
    assert decoded["id"] == str(uid)


def test_canonical_serialises_datetime_as_iso_utc() -> None:
    dt = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    raw = canonical_bytes_for_hash({"t": dt})
    decoded = json.loads(raw)
    assert decoded["t"].endswith("+00:00")


def test_canonical_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2026, 4, 21, 12, 0, 0)
    raw = canonical_bytes_for_hash({"t": naive})
    decoded = json.loads(raw)
    assert decoded["t"].endswith("+00:00")


def test_canonical_rejects_unknown_type() -> None:
    class Mystery:
        pass

    with pytest.raises(TypeError, match="cannot serialise"):
        canonical_bytes_for_hash({"m": Mystery()})


def test_canonical_bytes_values_roundtrip_as_b64url() -> None:
    raw = canonical_bytes_for_hash({"b": b"\x00\x01\xff"})
    decoded = json.loads(raw)
    # b"\x00\x01\xff" → base64url no padding
    import base64

    assert decoded["b"] == base64.urlsafe_b64encode(b"\x00\x01\xff").rstrip(b"=").decode()


# ── genesis_hash ─────────────────────────────────────────────────────


def test_genesis_hash_is_deterministic() -> None:
    assert genesis_hash("alpha") == genesis_hash("alpha")


def test_genesis_hash_matches_spec() -> None:
    tenant = "alpha"
    expected = hashlib.sha256(GENESIS_MAGIC + tenant.encode("utf-8")).digest()
    assert genesis_hash(tenant) == expected


def test_genesis_hash_differs_per_tenant() -> None:
    assert genesis_hash("alpha") != genesis_hash("beta")


def test_genesis_hash_rejects_empty_tenant() -> None:
    with pytest.raises(ValueError):
        genesis_hash("")


# ── compute_event_hash ───────────────────────────────────────────────


def test_event_hash_differs_when_payload_changes() -> None:
    kwargs = dict(
        prev_hash=genesis_hash("alpha"),
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
    )
    a = compute_event_hash(**kwargs, payload={"action": "login"})
    b = compute_event_hash(**kwargs, payload={"action": "logout"})
    assert a != b


def test_event_hash_differs_when_sequence_changes() -> None:
    common = dict(
        prev_hash=genesis_hash("alpha"),
        tenant_id="alpha",
        event_type="auth:login_success",
        payload={"action": "login"},
    )
    a = compute_event_hash(sequence_number=1, **common)
    b = compute_event_hash(sequence_number=2, **common)
    assert a != b


def test_event_hash_depends_on_prev_hash() -> None:
    common = dict(
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
        payload={"action": "login"},
    )
    a = compute_event_hash(prev_hash=b"\x00" * 32, **common)
    b = compute_event_hash(prev_hash=b"\xff" * 32, **common)
    assert a != b


def test_event_hash_depends_on_tenant_id() -> None:
    common = dict(
        sequence_number=1,
        event_type="auth:login_success",
        payload={"action": "login"},
    )
    a = compute_event_hash(
        prev_hash=genesis_hash("alpha"), tenant_id="alpha", **common
    )
    b = compute_event_hash(
        prev_hash=genesis_hash("beta"), tenant_id="beta", **common
    )
    assert a != b


def test_event_hash_is_32_bytes() -> None:
    h = compute_event_hash(
        prev_hash=genesis_hash("alpha"),
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
        payload={"action": "login"},
    )
    assert len(h) == 32


def test_event_hash_is_deterministic_for_same_inputs() -> None:
    kwargs = dict(
        prev_hash=genesis_hash("alpha"),
        tenant_id="alpha",
        sequence_number=1,
        event_type="auth:login_success",
        payload={"action": "login", "details": {"b": 2, "a": 1}},
    )
    assert compute_event_hash(**kwargs) == compute_event_hash(**kwargs)
