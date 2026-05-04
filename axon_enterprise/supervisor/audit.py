"""
Audit-trail integration for supervisor lifecycle events (Fase 16.l).

Every supervisor event lands as an immutable, canonical-hashed entry
in the enterprise audit log. The audit chain is per-tenant
Merkle-anchored so SOC2/GDPR/HIPAA auditors can reconstruct the
full lifecycle of any daemon and detect tampering.

Event types:

    daemon_started              — initial start
    daemon_crashed              — exception caught
    daemon_restarted            — about to invoke start_fn again
    daemon_intensity_exceeded   — gave up on this daemon
    daemon_state_snapshot       — pre-restart snapshot taken
    daemon_state_restored       — post-restart snapshot applied
    daemon_hibernated           — on_stuck=hibernate fired
    daemon_escalated            — on_stuck=escalate fired
    daemon_terminal_noop        — on_stuck=noop fired
    liveness_probe_failed       — probe declared the daemon stuck
    tenant_budget_exhausted     — multi-tenant budget gate tripped

Each entry carries:
    * event_type
    * daemon name
    * tenant id
    * timestamp (ISO-8601 UTC)
    * payload dict (event-specific fields)
    * canonical hash (HMAC-SHA256 of the canonical-serialized event
      under the tenant key)
    * Merkle parent hash (chain integrity)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol


class _AuditSink(Protocol):
    async def append(self, entry: dict[str, Any]) -> None: ...


@dataclass
class SupervisorAuditChain:
    """Append-only Merkle chain of supervisor events scoped per tenant.

    Each tenant has its own chain head (`prev_hash`) so per-tenant
    audit trails can be exported and verified independently.
    """

    sink: _AuditSink
    tenant_resolver: Callable[[str], str] | None = None
    sign_key_fn: Callable[[str], bytes] | None = None
    _per_tenant_head: dict[str, str] = field(default_factory=dict)

    def _tenant_for(self, daemon_name: str) -> str:
        if self.tenant_resolver is None:
            return "_global"
        try:
            return str(self.tenant_resolver(daemon_name) or "_global")
        except Exception:
            return "_global"

    def _key_for(self, tenant_id: str) -> bytes:
        if self.sign_key_fn is None:
            # Fallback: tenant id as the key. Real deployments wire a
            # KMS-backed key resolver; this default is for tests.
            return tenant_id.encode("utf-8")
        try:
            return self.sign_key_fn(tenant_id) or tenant_id.encode("utf-8")
        except Exception:
            return tenant_id.encode("utf-8")

    @staticmethod
    def _canonical_serialize(payload: dict[str, Any]) -> bytes:
        """Stable JSON for hashing — same shape on every replica."""
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")

    async def append(
        self,
        event_type: str,
        daemon_name: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append a supervisor event to the audit chain."""
        tenant_id = self._tenant_for(daemon_name)
        prev_hash = self._per_tenant_head.get(tenant_id, "")
        body = {
            "event_type": event_type,
            "daemon": daemon_name,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "payload": dict(payload or {}),
            "prev_hash": prev_hash,
        }
        canonical = self._canonical_serialize(body)
        signature = hmac.new(
            self._key_for(tenant_id), canonical, hashlib.sha256,
        ).hexdigest()
        merkle_hash = hashlib.sha256(
            (prev_hash + signature).encode("utf-8"),
        ).hexdigest()
        body["signature"] = signature
        body["merkle_hash"] = merkle_hash
        self._per_tenant_head[tenant_id] = merkle_hash
        try:
            await self.sink.append(body)
        except Exception:
            # Roll the head back so a failed sink write doesn't break
            # the chain for subsequent appends.
            self._per_tenant_head[tenant_id] = prev_hash

    def head_for_tenant(self, tenant_id: str) -> str:
        """Current Merkle head for a tenant — exportable for external
        verification."""
        return self._per_tenant_head.get(tenant_id, "")


class InMemoryAuditSink:
    """Trivial `_AuditSink` impl for tests + local dev.

    Production uses the enterprise audit/ adapter (Postgres + S3).
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(dict(entry))


def verify_chain(
    entries: list[dict[str, Any]],
    *,
    tenant_id: str,
    key: bytes,
) -> bool:
    """Re-derive the Merkle hashes from `entries` (in order) and
    verify each entry's signature + chain link. Returns True iff the
    chain is intact end-to-end for the given tenant.
    """
    prev_hash = ""
    for entry in entries:
        if entry.get("tenant_id") != tenant_id:
            continue
        body = {k: entry[k] for k in (
            "event_type", "daemon", "tenant_id", "timestamp",
            "payload", "prev_hash",
        ) if k in entry}
        if body.get("prev_hash") != prev_hash:
            return False
        canonical = SupervisorAuditChain._canonical_serialize(body)
        expected_sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, entry.get("signature", "")):
            return False
        expected_merkle = hashlib.sha256(
            (prev_hash + expected_sig).encode("utf-8"),
        ).hexdigest()
        if expected_merkle != entry.get("merkle_hash"):
            return False
        prev_hash = expected_merkle
    return True
