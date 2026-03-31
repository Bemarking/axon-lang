"""
AXON Runtime — Compute–MEK Epistemic Bridge
=============================================
Bridges the deterministic Fast-Path (compute) with the cognitive
Model Execution Kernel so that:

1. **Input de-referencing** — When a compute argument is a Latent
   Pointer (``PTR_LATENT_*``), the bridge resolves it to the
   numeric payload stored in the MEK ``tensor_registry``.

2. **Output registration** — After deterministic execution the
   scalar result is wrapped as a ``LatentState`` (entropy ≈ 0,
   because the result is deterministic) and registered in the
   tensor_registry under a new pointer.

3. **Epistemic metadata** — Every compute result carries provenance:
   ``tier`` (rust / c / python), ``verified`` (shield status),
   ``deterministic=True``, Shannon entropy, and the originating
   compute name.

Paper §4.2:
    "El nodo IRCompute interactúa directamente con el tensor_registry
     del MEK a nivel del sistema operativo."
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Prefix that identifies a MEK Latent Pointer string.
_PTR_PREFIX = "PTR_LATENT_"


# ── Epistemic Result DTO ────────────────────────────────────────
@dataclass(frozen=True)
class ComputeEpistemicResult:
    """Result of a compute execution enriched with epistemic metadata.

    Attributes:
        output_name:    The AXON variable name for the result.
        result:         Raw numeric value (f64).
        tier:           Execution tier that produced the result.
        latent_pointer: MEK pointer (``PTR_LATENT_compute_*``) that
                        references the registered LatentState in the
                        tensor_registry.
        entropy:        Shannon entropy of the result tensor.  For a
                        scalar deterministic value this is 0.0.
        deterministic:  Always ``True`` for compute.
        verified:       ``True`` if a shield proved the logic theorem.
        provenance:     Dict with execution lineage metadata.
    """

    output_name: str
    result: Any
    tier: str = "python"
    latent_pointer: str = ""
    entropy: float = 0.0
    deterministic: bool = True
    verified: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary for context storage."""
        return {
            "output_name": self.output_name,
            "result": self.result,
            "tier": self.tier,
            "latent_pointer": self.latent_pointer,
            "entropy": self.entropy,
            "deterministic": self.deterministic,
            "verified": self.verified,
            "provenance": self.provenance,
        }


# ── Bridge ──────────────────────────────────────────────────────
class ComputeMEKBridge:
    """Mediates between the NativeComputeDispatcher and the MEK.

    Lifecycle per compute invocation:
        1. ``resolve_inputs``  — de-reference any latent pointers
        2. (dispatcher runs native logic)
        3. ``register_output`` — wrap result in a LatentState and
           register it in the MEK tensor_registry
    """

    def __init__(self, mek: Any | None = None) -> None:
        """Accept an existing MEK instance, or lazily create one."""
        self._mek = mek
        self._mek_available: bool | None = None

    # ── lazy MEK bootstrap ─────────────────────────────────────
    def _ensure_mek(self) -> Any | None:
        """Return the MEK instance, instantiating lazily if needed."""
        if self._mek is not None:
            return self._mek
        if self._mek_available is False:
            return None

        try:
            from axon.runtime.mek.kernel import ModelExecutionKernel

            self._mek = ModelExecutionKernel()
            self._mek_available = True
            logger.info("ComputeMEKBridge: MEK kernel instantiated")
            return self._mek
        except Exception:
            self._mek_available = False
            logger.debug(
                "ComputeMEKBridge: MEK unavailable — bridge disabled",
                exc_info=True,
            )
            return None

    # ── 1. INPUT DE-REFERENCING ────────────────────────────────
    def resolve_inputs(
        self,
        arguments: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve latent pointers in the argument list.

        For every argument that looks like a ``PTR_LATENT_*`` string
        (either passed directly or stored under a context key), the
        bridge de-references the pointer through the MEK's
        ``tensor_registry`` and replaces it with the numeric payload.

        Returns a *shallow copy* of *context* with de-referenced
        values injected for the pointer keys.
        """
        mek = self._ensure_mek()
        if mek is None:
            return context  # pass-through

        resolved = dict(context)
        for arg in arguments:
            val = context.get(arg, arg)
            if isinstance(val, str) and val.startswith(_PTR_PREFIX):
                resolved[arg] = self._deref_pointer(mek, val)
            elif isinstance(arg, str) and arg.startswith(_PTR_PREFIX):
                # The argument IS a pointer literal
                resolved[arg] = self._deref_pointer(mek, arg)
        return resolved

    @staticmethod
    def _deref_pointer(mek: Any, pointer: str) -> Any:
        """De-reference a single latent pointer to its numeric payload.

        If the pointer holds a torch.Tensor, we extract the scalar
        value.  If extraction fails the raw tensor is returned so
        downstream consumers can handle it.
        """
        registry = getattr(mek, "tensor_registry", {})
        if pointer not in registry:
            logger.warning("Latent pointer not found: %s", pointer)
            return pointer  # pass through unchanged

        latent = registry[pointer]
        tensor = getattr(latent, "tensor", None)
        if tensor is None:
            return pointer

        try:
            # Scalar extraction: .item() works for single-element tensors
            return float(tensor.item())
        except Exception:
            # Multi-element tensor — return as-is for advanced compute
            return tensor

    # ── 2. OUTPUT REGISTRATION ─────────────────────────────────
    def register_output(
        self,
        *,
        compute_name: str,
        output_name: str,
        result: Any,
        tier: str = "python",
        verified: bool = False,
    ) -> ComputeEpistemicResult:
        """Wrap a deterministic compute result as an epistemic LatentState.

        Steps:
            a. Convert the scalar result to a 1-D tensor.
            b. Create a ``LatentState`` with ``origin_model_id =
               "native-compute"`` (deterministic — no LLM).
            c. Register in ``tensor_registry`` under a new pointer.
            d. Return a ``ComputeEpistemicResult`` with all metadata.
        """
        mek = self._ensure_mek()
        latent_pointer = ""
        entropy = 0.0

        if mek is not None and result is not None:
            try:
                import torch

                # Wrap scalar as 1-element tensor
                if isinstance(result, (int, float)):
                    if not math.isfinite(result):
                        raise ValueError(
                            f"Compute produced non-finite result: {result}"
                        )
                    t = torch.tensor([float(result)], dtype=torch.float64)
                else:
                    t = torch.tensor([0.0], dtype=torch.float64)

                latent_pointer = mek.intercept_latent_state(
                    source_node_id=f"compute_{compute_name}",
                    state_tensor=t,
                    origin_model_id="native-compute",
                )
                # Deterministic results have zero Shannon entropy
                latent = mek.tensor_registry.get(latent_pointer)
                if latent is not None:
                    entropy = getattr(latent, "entropy", 0.0)

                logger.info(
                    "Compute '%s' registered as %s (entropy=%.6f, tier=%s)",
                    compute_name,
                    latent_pointer,
                    entropy,
                    tier,
                )
            except ImportError:
                logger.debug("torch not available — skipping MEK registration")
            except Exception:
                logger.debug(
                    "MEK registration failed",
                    exc_info=True,
                )

        provenance = {
            "compute_name": compute_name,
            "tier": tier,
            "verified": verified,
            "deterministic": True,
            "origin_model_id": "native-compute",
        }

        return ComputeEpistemicResult(
            output_name=output_name,
            result=result,
            tier=tier,
            latent_pointer=latent_pointer,
            entropy=entropy,
            deterministic=True,
            verified=verified,
            provenance=provenance,
        )

    # ── 3. CLEANUP ─────────────────────────────────────────────
    def flush(self) -> None:
        """Flush the MEK tensor_registry (VRAM cleanup)."""
        if self._mek is not None:
            self._mek.flush_memory()
