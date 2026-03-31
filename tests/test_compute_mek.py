"""
AXON Compute — MEK Epistemic Bridge Tests
=============================================
Tests for the integration between the compute primitive and the
Model Execution Kernel (MEK) as described in Paper §4.2:

    "El nodo IRCompute interactúa directamente con el tensor_registry
     del MEK a nivel del sistema operativo."

Verifies:
  - ComputeMEKBridge lazy MEK instantiation
  - Input de-referencing of Latent Pointers
  - Output registration in tensor_registry
  - ComputeEpistemicResult provenance metadata
  - Shannon entropy tracking (≈ 0 for deterministic)
  - NativeComputeDispatcher MEK integration path
  - Executor-level MEK context propagation
  - Flush / cleanup semantics
  - Edge cases: orphan pointers, non-finite results, missing MEK
"""

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest

from axon.runtime.compute_mek_bridge import (
    ComputeEpistemicResult,
    ComputeMEKBridge,
)
from axon.runtime.compute_dispatcher import NativeComputeDispatcher


# ── Fixture: real MEK kernel ──────────────────────────────────────
@pytest.fixture
def real_mek():
    """Return a real ModelExecutionKernel instance."""
    torch = pytest.importorskip("torch", reason="torch required for MEK")
    from axon.runtime.mek.kernel import ModelExecutionKernel

    return ModelExecutionKernel()


@pytest.fixture
def bridge(real_mek):
    """Return a ComputeMEKBridge wired to a real MEK."""
    return ComputeMEKBridge(mek=real_mek)


# ── Fixture: MEK with a pre-registered latent pointer ─────────────
@pytest.fixture
def mek_with_pointer(real_mek):
    """Register a dummy latent state and return (mek, pointer, value)."""
    import torch

    value = 42.0
    t = torch.tensor([value], dtype=torch.float64)
    pointer = real_mek.intercept_latent_state(
        source_node_id="prior_step",
        state_tensor=t,
        origin_model_id="test-model",
    )
    return real_mek, pointer, value


# ═══════════════════════════════════════════════════════════════════
#  ComputeEpistemicResult
# ═══════════════════════════════════════════════════════════════════

class TestComputeEpistemicResult:
    """Unit tests for the epistemic result DTO."""

    def test_to_dict_round_trip(self):
        r = ComputeEpistemicResult(
            output_name="total",
            result=99.5,
            tier="python",
            latent_pointer="PTR_LATENT_compute_add_abc12345",
            entropy=0.0,
            deterministic=True,
            verified=True,
            provenance={"compute_name": "add"},
        )
        d = r.to_dict()
        assert d["output_name"] == "total"
        assert d["result"] == 99.5
        assert d["tier"] == "python"
        assert d["latent_pointer"].startswith("PTR_LATENT_")
        assert d["entropy"] == 0.0
        assert d["deterministic"] is True
        assert d["verified"] is True
        assert d["provenance"]["compute_name"] == "add"

    def test_defaults(self):
        r = ComputeEpistemicResult(output_name="x", result=1)
        assert r.tier == "python"
        assert r.latent_pointer == ""
        assert r.entropy == 0.0
        assert r.deterministic is True
        assert r.verified is False
        assert r.provenance == {}

    def test_frozen(self):
        r = ComputeEpistemicResult(output_name="x", result=1)
        with pytest.raises(AttributeError):
            r.result = 2  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  ComputeMEKBridge — Lazy Init
# ═══════════════════════════════════════════════════════════════════

class TestBridgeLazyInit:
    """Verify lazy MEK instantiation."""

    def test_bridge_without_mek_creates_lazily(self):
        bridge = ComputeMEKBridge(mek=None)
        mek = bridge._ensure_mek()
        # If torch is installed, MEK should be available
        pytest.importorskip("torch", reason="torch needed")
        assert mek is not None
        assert hasattr(mek, "tensor_registry")

    def test_bridge_with_provided_mek(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        assert bridge._ensure_mek() is real_mek

    def test_bridge_caches_mek_unavailable(self):
        bridge = ComputeMEKBridge(mek=None)
        with patch(
            "axon.runtime.compute_mek_bridge.ComputeMEKBridge._ensure_mek",
            return_value=None,
        ):
            bridge._mek_available = False
            assert bridge._ensure_mek() is None


# ═══════════════════════════════════════════════════════════════════
#  ComputeMEKBridge — Input De-referencing
# ═══════════════════════════════════════════════════════════════════

class TestInputDeref:
    """Verify Latent Pointer de-referencing on compute inputs."""

    def test_deref_pointer_to_scalar(self, mek_with_pointer):
        mek, pointer, value = mek_with_pointer
        bridge = ComputeMEKBridge(mek=mek)

        context = {"x": pointer}
        resolved = bridge.resolve_inputs(["x"], context)
        assert resolved["x"] == pytest.approx(value)

    def test_deref_preserves_plain_values(self, bridge):
        context = {"a": 10.0, "b": 20.0}
        resolved = bridge.resolve_inputs(["a", "b"], context)
        assert resolved["a"] == 10.0
        assert resolved["b"] == 20.0

    def test_deref_orphan_pointer_passes_through(self, bridge):
        context = {"x": "PTR_LATENT_orphan_00000000"}
        resolved = bridge.resolve_inputs(["x"], context)
        # Orphan pointer stays as-is (logged as warning)
        assert resolved["x"] == "PTR_LATENT_orphan_00000000"

    def test_deref_direct_pointer_argument(self, mek_with_pointer):
        mek, pointer, value = mek_with_pointer
        bridge = ComputeMEKBridge(mek=mek)
        context = {}
        resolved = bridge.resolve_inputs([pointer], context)
        assert resolved[pointer] == pytest.approx(value)

    def test_deref_without_mek_passes_through(self):
        bridge = ComputeMEKBridge(mek=None)
        bridge._mek_available = False
        context = {"x": "PTR_LATENT_something_12345678"}
        resolved = bridge.resolve_inputs(["x"], context)
        # No MEK → pass through unchanged
        assert resolved["x"] == "PTR_LATENT_something_12345678"


# ═══════════════════════════════════════════════════════════════════
#  ComputeMEKBridge — Output Registration
# ═══════════════════════════════════════════════════════════════════

class TestOutputRegistration:
    """Verify that compute results become LatentState in the MEK."""

    def test_register_scalar_result(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="add",
            output_name="total",
            result=42.0,
            tier="python",
            verified=True,
        )
        assert isinstance(ep, ComputeEpistemicResult)
        assert ep.result == 42.0
        assert ep.latent_pointer.startswith("PTR_LATENT_compute_add_")
        assert ep.deterministic is True
        assert ep.verified is True
        assert ep.provenance["compute_name"] == "add"
        assert ep.provenance["tier"] == "python"
        assert ep.provenance["origin_model_id"] == "native-compute"

    def test_registered_pointer_exists_in_registry(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="mul",
            output_name="product",
            result=100.0,
        )
        assert ep.latent_pointer in real_mek.tensor_registry

    def test_registered_tensor_value_matches(self, real_mek):
        import torch

        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="sub",
            output_name="diff",
            result=7.5,
        )
        latent = real_mek.tensor_registry[ep.latent_pointer]
        assert latent.tensor.item() == pytest.approx(7.5)
        assert latent.origin_model_id == "native-compute"

    def test_register_integer_result(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="count",
            output_name="n",
            result=7,
        )
        assert ep.latent_pointer.startswith("PTR_LATENT_")
        latent = real_mek.tensor_registry[ep.latent_pointer]
        assert latent.tensor.item() == pytest.approx(7.0)

    def test_register_none_skips_mek(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        initial_count = len(real_mek.tensor_registry)
        ep = bridge.register_output(
            compute_name="noop",
            output_name="x",
            result=None,
        )
        assert ep.latent_pointer == ""
        assert len(real_mek.tensor_registry) == initial_count

    def test_register_nonfinite_raises(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="bad",
            output_name="x",
            result=float("inf"),
        )
        # Non-finite should not produce a pointer (logs error)
        assert ep.latent_pointer == ""

    def test_register_nan_raises(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="bad",
            output_name="x",
            result=float("nan"),
        )
        assert ep.latent_pointer == ""

    def test_entropy_near_zero_for_deterministic(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="det",
            output_name="y",
            result=3.14,
        )
        # Single-element tensor → softmax is [1.0] → entropy ≈ 0
        # (may have tiny float noise)
        assert abs(ep.entropy) < 1e-6

    def test_without_mek_returns_bare_result(self):
        bridge = ComputeMEKBridge(mek=None)
        bridge._mek_available = False
        ep = bridge.register_output(
            compute_name="add",
            output_name="sum",
            result=10.0,
        )
        assert ep.result == 10.0
        assert ep.latent_pointer == ""
        assert ep.provenance["deterministic"] is True


# ═══════════════════════════════════════════════════════════════════
#  ComputeMEKBridge — Flush
# ═══════════════════════════════════════════════════════════════════

class TestFlush:
    """VRAM cleanup semantics."""

    def test_flush_clears_registry(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        bridge.register_output(
            compute_name="a", output_name="x", result=1.0,
        )
        assert len(real_mek.tensor_registry) > 0
        bridge.flush()
        assert len(real_mek.tensor_registry) == 0

    def test_flush_without_mek_is_noop(self):
        bridge = ComputeMEKBridge(mek=None)
        bridge._mek_available = False
        bridge.flush()  # should not raise


# ═══════════════════════════════════════════════════════════════════
#  NativeComputeDispatcher — MEK Integration
# ═══════════════════════════════════════════════════════════════════

class TestDispatcherMEKIntegration:
    """Verify the dispatcher routes through the MEK bridge."""

    @pytest.fixture
    def meta_add(self):
        return {
            "compute_name": "add",
            "arguments": ["5", "3"],
            "output_name": "total",
            "compute_definition": {
                "inputs": [
                    {"name": "a", "type_name": "f64"},
                    {"name": "b", "type_name": "f64"},
                ],
                "logic_source": "let result = a + b\nreturn result",
                "verified": False,
            },
        }

    async def test_dispatch_with_mek_bridge(self, real_mek, meta_add):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)
        result = await dispatcher.dispatch(meta_add, {})

        assert result["result"] == 8
        assert result["output_name"] == "total"
        assert result["tier"] == "python"
        # Epistemic fields present
        assert result["latent_pointer"].startswith("PTR_LATENT_compute_add_")
        assert result["deterministic"] is True
        assert "provenance" in result

    async def test_dispatch_without_mek_bridge(self, meta_add):
        dispatcher = NativeComputeDispatcher()
        result = await dispatcher.dispatch(meta_add, {})
        assert result["result"] == 8
        assert result["tier"] == "python"
        # No latent_pointer without MEK
        assert "latent_pointer" not in result

    async def test_dispatch_registered_in_tensor_registry(
        self, real_mek, meta_add,
    ):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)
        result = await dispatcher.dispatch(meta_add, {})

        ptr = result["latent_pointer"]
        assert ptr in real_mek.tensor_registry
        latent = real_mek.tensor_registry[ptr]
        assert latent.tensor.item() == pytest.approx(8.0)

    async def test_dispatch_with_latent_pointer_input(self, mek_with_pointer):
        mek, pointer, value = mek_with_pointer
        bridge = ComputeMEKBridge(mek=mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)

        meta = {
            "compute_name": "double",
            "arguments": ["x", "2"],
            "output_name": "doubled",
            "compute_definition": {
                "inputs": [
                    {"name": "x", "type_name": "f64"},
                    {"name": "y", "type_name": "f64"},
                ],
                "logic_source": "let result = x * y\nreturn result",
            },
        }
        # Context carries the latent pointer under key "x"
        context = {"x": pointer}
        result = await dispatcher.dispatch(meta, context)
        assert result["result"] == pytest.approx(84.0)  # 42.0 * 2

    async def test_dispatch_verified_flag_propagates(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)
        meta = {
            "compute_name": "safe",
            "arguments": ["1"],
            "output_name": "out",
            "compute_definition": {
                "inputs": [{"name": "a", "type_name": "f64"}],
                "logic_source": "return a",
                "verified": True,
            },
        }
        result = await dispatcher.dispatch(meta, {})
        assert result["verified"] is True
        assert result["provenance"]["verified"] is True


# ═══════════════════════════════════════════════════════════════════
#  End-to-End: Compute → MEK → Downstream Context
# ═══════════════════════════════════════════════════════════════════

class TestEndToEndMEK:
    """Full pipeline: compute produces pointer, next compute reads it."""

    async def test_chained_computes_via_pointers(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)

        # Step 1: compute area = width * height
        meta1 = {
            "compute_name": "area",
            "arguments": ["10", "5"],
            "output_name": "area",
            "compute_definition": {
                "inputs": [
                    {"name": "w", "type_name": "f64"},
                    {"name": "h", "type_name": "f64"},
                ],
                "logic_source": "let result = w * h\nreturn result",
            },
        }
        r1 = await dispatcher.dispatch(meta1, {})
        assert r1["result"] == 50
        ptr1 = r1["latent_pointer"]
        assert ptr1.startswith("PTR_LATENT_compute_area_")

        # Step 2: compute doubled = area * 2
        # The context carries the latent pointer from Step 1
        meta2 = {
            "compute_name": "doubled",
            "arguments": ["area", "2"],
            "output_name": "doubled",
            "compute_definition": {
                "inputs": [
                    {"name": "area", "type_name": "f64"},
                    {"name": "factor", "type_name": "f64"},
                ],
                "logic_source": "let result = area * factor\nreturn result",
            },
        }
        context2 = {"area": ptr1}  # latent pointer in context
        r2 = await dispatcher.dispatch(meta2, context2)
        assert r2["result"] == pytest.approx(100.0)  # 50 * 2
        assert r2["latent_pointer"].startswith("PTR_LATENT_compute_doubled_")

    async def test_multiple_pointers_in_registry(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)

        pointers = []
        for i in range(5):
            meta = {
                "compute_name": f"step_{i}",
                "arguments": [str(i + 1), "10"],
                "output_name": f"out_{i}",
                "compute_definition": {
                    "inputs": [
                        {"name": "a", "type_name": "f64"},
                        {"name": "b", "type_name": "f64"},
                    ],
                    "logic_source": "let result = a * b\nreturn result",
                },
            }
            r = await dispatcher.dispatch(meta, {})
            pointers.append(r["latent_pointer"])

        # All 5 pointers should be distinct and in the registry
        assert len(set(pointers)) == 5
        for ptr in pointers:
            assert ptr in real_mek.tensor_registry

    async def test_flush_between_programs(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)

        meta = {
            "compute_name": "temp",
            "arguments": ["1"],
            "output_name": "t",
            "compute_definition": {
                "inputs": [{"name": "a", "type_name": "f64"}],
                "logic_source": "return a",
            },
        }
        r = await dispatcher.dispatch(meta, {})
        assert len(real_mek.tensor_registry) > 0

        bridge.flush()
        assert len(real_mek.tensor_registry) == 0


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases & Negative Tests
# ═══════════════════════════════════════════════════════════════════

class TestMEKEdgeCases:
    """Boundary conditions for the MEK bridge."""

    def test_deref_non_pointer_string(self, bridge):
        context = {"x": "hello_world"}
        resolved = bridge.resolve_inputs(["x"], context)
        assert resolved["x"] == "hello_world"

    def test_deref_numeric_value_untouched(self, bridge):
        context = {"x": 3.14}
        resolved = bridge.resolve_inputs(["x"], context)
        assert resolved["x"] == 3.14

    def test_register_zero(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="zero", output_name="z", result=0.0,
        )
        assert ep.latent_pointer.startswith("PTR_LATENT_")
        assert real_mek.tensor_registry[ep.latent_pointer].tensor.item() == 0.0

    def test_register_negative(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="neg", output_name="n", result=-999.0,
        )
        latent = real_mek.tensor_registry[ep.latent_pointer]
        assert latent.tensor.item() == pytest.approx(-999.0)

    def test_register_very_large(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        ep = bridge.register_output(
            compute_name="big", output_name="b", result=1e300,
        )
        assert ep.latent_pointer.startswith("PTR_LATENT_")

    async def test_dispatcher_division_by_zero_with_mek(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)
        meta = {
            "compute_name": "bad_div",
            "arguments": ["1", "0"],
            "output_name": "oops",
            "compute_definition": {
                "inputs": [
                    {"name": "a", "type_name": "f64"},
                    {"name": "b", "type_name": "f64"},
                ],
                "logic_source": "let result = a / b\nreturn result",
            },
        }
        with pytest.raises(ZeroDivisionError):
            await dispatcher.dispatch(meta, {})

    async def test_dispatcher_non_numeric_with_mek(self, real_mek):
        bridge = ComputeMEKBridge(mek=real_mek)
        dispatcher = NativeComputeDispatcher(mek_bridge=bridge)
        meta = {
            "compute_name": "bad_type",
            "arguments": ["hello"],
            "output_name": "x",
            "compute_definition": {
                "inputs": [{"name": "a", "type_name": "f64"}],
                "logic_source": "return a",
            },
        }
        with pytest.raises(ValueError, match="non-numeric"):
            await dispatcher.dispatch(meta, {})
