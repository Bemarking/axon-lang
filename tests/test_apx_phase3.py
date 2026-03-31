"""APX Phase 3 tests: runtime resolution, FFI degradation, and blame semantics."""

from __future__ import annotations

import pytest

from axon.engine.apx import (
    EdgeKind,
    EpistemicContract,
    EpistemicEdge,
    EpistemicGraph,
    EpistemicLevel,
    EpistemicNode,
)
from axon.runtime.apx_resolver import (
    APXContract,
    APXDecision,
    APXPolicy,
    APXResolutionError,
    APXResolver,
)


def _contract(seed: str) -> EpistemicContract:
    return EpistemicContract(ecid=f"ecid-{seed}", certificate_hash=f"hash-{seed}", witness_count=2)


def _graph() -> EpistemicGraph:
    g = EpistemicGraph("runtime-apx")
    g.add_node(EpistemicNode("base.core", EpistemicLevel.CITED_FACT, _contract("base")))
    g.add_node(EpistemicNode("pkg.safe", EpistemicLevel.FACTUAL_CLAIM, _contract("safe")))
    g.add_node(EpistemicNode("pkg.low", EpistemicLevel.OPINION, _contract("low"), server_blame_count=5))

    g.add_edge(EpistemicEdge("pkg.safe", "base.core", EdgeKind.DEPENDS_ON, 1.0))
    g.add_edge(EpistemicEdge("pkg.low", "base.core", EdgeKind.DEPENDS_ON, 0.8))
    return g


def test_runtime_resolution_ok_with_ffi_degradation() -> None:
    resolver = APXResolver()
    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.safe",
        policy=APXPolicy(min_epr=0.0, on_low_rank="warn", ffi_mode="taint"),
        provided_pcc_hash="hash-safe",
        ffi_payload={"user": "alice", "token": "secret"},
    )

    assert result.decision == APXDecision.RESOLVED
    assert result.degraded_payload is not None
    assert result.degraded_payload.epistemic_mode == "believe"
    assert result.degraded_payload.tainted is True


def test_runtime_resolution_quarantine_on_low_rank() -> None:
    resolver = APXResolver()
    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.low",
        policy=APXPolicy(min_epr=0.9, on_low_rank="quarantine"),
        provided_pcc_hash="hash-low",
    )

    assert result.decision == APXDecision.QUARANTINED
    assert result.warnings


def test_runtime_resolution_block_on_low_rank() -> None:
    resolver = APXResolver()
    with pytest.raises(APXResolutionError, match="blocked by policy"):
        resolver.resolve(
            graph=_graph(),
            package_id="pkg.low",
            policy=APXPolicy(min_epr=0.99, on_low_rank="block"),
            provided_pcc_hash="hash-low",
        )


def test_runtime_resolution_pcc_required() -> None:
    resolver = APXResolver()
    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.safe",
        policy=APXPolicy(require_pcc=True, on_low_rank="warn"),
        provided_pcc_hash="wrong-hash",
    )
    assert result.decision == APXDecision.WARNED
    assert "PCC verification failed" in result.warnings[0]


def test_runtime_resolution_trust_floor_violation_warns() -> None:
    resolver = APXResolver()
    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.low",
        policy=APXPolicy(trust_floor="factual_claim", on_low_rank="warn"),
        provided_pcc_hash="hash-low",
    )

    assert result.decision == APXDecision.WARNED
    assert "trust floor violation" in result.warnings[0]


def test_ffi_mode_sanitize_scrubs_sensitive_keys() -> None:
    resolver = APXResolver()
    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.safe",
        policy=APXPolicy(ffi_mode="sanitize"),
        provided_pcc_hash="hash-safe",
        ffi_payload={"ok": 1, "api_token": "xxx", "password": "yyy"},
    )

    payload = result.degraded_payload.value
    assert "ok" in payload
    assert "api_token" not in payload
    assert "password" not in payload


def test_contract_semantics_raise_strategy() -> None:
    resolver = APXResolver()

    def _call(args):
        return {"x": args.get("x", 0)}

    contract = APXContract(
        name="C",
        precondition=lambda a: a.get("x", 0) > 0,
        postcondition=lambda r: r.get("x", 0) > 0,
        on_violation="raise",
    )

    with pytest.raises(APXResolutionError, match="contract violation"):
        resolver.execute_with_contract("pkg.safe", {"x": 0}, _call, contract)

    assert resolver.faults
    assert resolver.faults[0].label.value == "caller"


def test_contract_semantics_retry_strategy() -> None:
    resolver = APXResolver()
    state = {"n": 0}

    def _call(args):
        state["n"] += 1
        return {"ok": state["n"] >= 2}

    contract = APXContract(
        name="C",
        postcondition=lambda r: r.get("ok", False) is True,
        on_violation="retry",
    )

    result = resolver.execute_with_contract("pkg.safe", {}, _call, contract, retries=2)
    assert result["ok"] is True


def test_contract_semantics_fallback_and_warn() -> None:
    resolver = APXResolver()

    def _call(args):
        return {"ok": False}

    fallback_contract = APXContract(
        name="F",
        postcondition=lambda r: r.get("ok", False),
        on_violation="fallback",
        fallback_value={"ok": True, "source": "fallback"},
    )
    warn_contract = APXContract(
        name="W",
        postcondition=lambda r: r.get("ok", False),
        on_violation="warn",
        fallback_value={"ok": None},
    )

    fb = resolver.execute_with_contract("pkg.safe", {}, _call, fallback_contract)
    wrn = resolver.execute_with_contract("pkg.safe", {}, _call, warn_contract)

    assert fb["source"] == "fallback"
    assert "warning" in wrn


def test_contract_blame_server_on_postcondition_failure() -> None:
    resolver = APXResolver()

    def _call(args):
        return {"ok": False}

    contract = APXContract(
        name="S",
        postcondition=lambda r: r.get("ok", False),
        on_violation="warn",
    )

    _ = resolver.execute_with_contract("pkg.safe", {}, _call, contract)
    assert resolver.faults
    assert any(f.label.value == "server" for f in resolver.faults)
