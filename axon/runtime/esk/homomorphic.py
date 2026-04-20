"""
AXON Runtime — Homomorphic Encryption (ESK Fase 6.4)
========================================================
CKKS-backed homomorphic compute for `Secret[T]`, enabling
arithmetic over ciphertext **without** ever materializing plaintext
in the Axon process memory.

The design intentionally follows TenSEAL's API surface (which wraps
Microsoft SEAL's CKKS scheme).  The AXON `HomomorphicContext` holds
the cryptographic parameters + galois/relin keys; `EncryptedValue`
wraps a ciphertext and exposes `add` / `multiply` / `dot` without
decryption.  Only `decrypt(context)` materializes plaintext — and
only inside the caller's scope, preserving the no-materialize
invariant of the surrounding `Secret[T]` envelope.

Design anchors
--------------
• **No silent fallback.** Without `tenseal` installed, the context's
  constructor raises `RuntimeError` — identical policy to `DilithiumSigner`.
• **Parameters chosen for real security.** Default 128-bit security
  (poly_modulus_degree=8192, scale=2^40) per SEAL guidance.
• **Operations are side-effect free.** Every `add`/`multiply` returns
  a new `EncryptedValue`; the original ciphertext is immutable.
• **Depth accounting.** CKKS multiplications consume noise budget;
  `EncryptedValue.depth` tracks the current multiplicative depth so
  operators can bail before crossing the limit.

References
----------
• Cheon, J.H., Kim, A., Kim, M., Song, Y. (2017). *Homomorphic Encryption
  for Arithmetic of Approximate Numbers* — CKKS.
• Fan, J., Vercauteren, F. (2012). *Somewhat Practical Fully Homomorphic
  Encryption* — BFV.
• NIST SP 800-57 Part 1 Rev 5 — key-management guidance for HE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from axon.runtime.handlers.base import CalleeBlameError, CallerBlameError


# ═══════════════════════════════════════════════════════════════════
#  Parameters
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CkksParameters:
    """CKKS scheme parameters (subset of TenSEAL's ``ts.context`` config).

    Defaults are the SEAL-recommended preset for **128-bit security**:
    ``N = 8192``, ``q = (60, 40, 40, 60)``, ``scale = 2^40``.  This
    supports about 2 multiplicative levels before relinearization and
    rescaling saturate the noise budget.
    """
    poly_modulus_degree: int = 8192
    coeff_mod_bit_sizes: tuple[int, ...] = (60, 40, 40, 60)
    scale: float = 2.0 ** 40

    def security_level(self) -> int:
        """Rule-of-thumb 128-bit level for N ∈ {4096, 8192, 16384}
        combined with conservative coeff moduli; returns the bit-level
        the parameters are intended to provide."""
        if self.poly_modulus_degree < 8192:
            return 0  # sub-standard — toy parameters only
        if self.poly_modulus_degree < 16384:
            return 128
        return 192


# ═══════════════════════════════════════════════════════════════════
#  Homomorphic context
# ═══════════════════════════════════════════════════════════════════

class HomomorphicContext:
    """Wrapper around a TenSEAL CKKS context with key material.

    The context owns:
      • public key (encrypt)
      • secret key (decrypt — stays inside this object)
      • galois keys (rotate)
      • relinearization keys (multiply-rescale)

    ``encrypt(value)`` returns an `EncryptedValue` bound to this context.
    ``decrypt(ct)`` requires the same context that produced the ct and
    returns the recovered plaintext vector.
    """

    def __init__(self, *, _context: Any, parameters: CkksParameters) -> None:
        # Constructor is not a public entry point — use ``ckks()`` factory.
        self._ctx = _context
        self.parameters = parameters

    @classmethod
    def ckks(
        cls,
        parameters: CkksParameters | None = None,
    ) -> "HomomorphicContext":
        """Factory: create a CKKS context with the given parameters.

        Requires ``tenseal``.  Raises ``RuntimeError`` if not installed.
        """
        params = parameters or CkksParameters()
        try:
            import tenseal as ts  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "HomomorphicContext.ckks requires the 'tenseal' package. "
                "Install with `pip install tenseal`."
            ) from exc

        context = ts.context(
            scheme=ts.SCHEME_TYPE.CKKS,
            poly_modulus_degree=params.poly_modulus_degree,
            coeff_mod_bit_sizes=list(params.coeff_mod_bit_sizes),
        )
        context.generate_galois_keys()
        context.generate_relin_keys()
        context.global_scale = params.scale

        return cls(_context=context, parameters=params)

    # ── Encryption / decryption ───────────────────────────────────

    def encrypt(self, value: float | Sequence[float]) -> "EncryptedValue":
        """Encode + encrypt a scalar or vector under CKKS.

        Vectors are packed into a single ciphertext (SIMD slots).
        """
        try:
            import tenseal as ts  # type: ignore[import-not-found]
        except ImportError as exc:  # noqa: F401 — unreachable if ctor succeeded
            raise CalleeBlameError(
                "tenseal disappeared after context construction"
            ) from exc

        if isinstance(value, (int, float)):
            ct = ts.ckks_vector(self._ctx, [float(value)])
            return EncryptedValue(_ct=ct, depth=0, n_slots=1, _ctx=self)
        vec = [float(v) for v in value]
        if not vec:
            raise CallerBlameError("encrypt() requires at least one value")
        ct = ts.ckks_vector(self._ctx, vec)
        return EncryptedValue(_ct=ct, depth=0, n_slots=len(vec), _ctx=self)

    def decrypt(self, enc: "EncryptedValue") -> list[float]:
        """Decrypt a ciphertext produced by this context."""
        if enc._ctx is not self:
            raise CallerBlameError(
                "decrypt() called on a ciphertext produced by a DIFFERENT context"
            )
        return list(enc._ct.decrypt())


# ═══════════════════════════════════════════════════════════════════
#  Ciphertext wrapper
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EncryptedValue:
    """A CKKS ciphertext plus metadata: slot count, multiplicative depth,
    and a back-reference to the context that produced it.

    Arithmetic methods are **pure** — they return a new `EncryptedValue`
    rather than mutating the receiver.  This preserves the algebraic
    independence of intermediate results and makes a workflow composable.
    """

    _ct: Any = field(repr=False)
    depth: int = 0
    n_slots: int = 1
    _ctx: HomomorphicContext | None = field(default=None, repr=False)

    # ── Arithmetic over ciphertext ────────────────────────────────

    def add(self, other: "EncryptedValue | float | Sequence[float]") -> "EncryptedValue":
        """Homomorphic addition.  Depth unchanged."""
        if isinstance(other, EncryptedValue):
            self._check_ctx(other)
            new_ct = self._ct + other._ct
            new_depth = max(self.depth, other.depth)
        else:
            new_ct = self._ct + self._to_plain(other)
            new_depth = self.depth
        return EncryptedValue(
            _ct=new_ct, depth=new_depth, n_slots=self.n_slots, _ctx=self._ctx,
        )

    def subtract(self, other: "EncryptedValue | float | Sequence[float]") -> "EncryptedValue":
        if isinstance(other, EncryptedValue):
            self._check_ctx(other)
            new_ct = self._ct - other._ct
            new_depth = max(self.depth, other.depth)
        else:
            new_ct = self._ct - self._to_plain(other)
            new_depth = self.depth
        return EncryptedValue(
            _ct=new_ct, depth=new_depth, n_slots=self.n_slots, _ctx=self._ctx,
        )

    def multiply(self, other: "EncryptedValue | float | Sequence[float]") -> "EncryptedValue":
        """Homomorphic multiplication.  Depth += 1 when cipher × cipher."""
        if isinstance(other, EncryptedValue):
            self._check_ctx(other)
            new_ct = self._ct * other._ct
            new_depth = max(self.depth, other.depth) + 1
        else:
            new_ct = self._ct * self._to_plain(other)
            new_depth = self.depth  # plaintext multiplication: no depth cost
        return EncryptedValue(
            _ct=new_ct, depth=new_depth, n_slots=self.n_slots, _ctx=self._ctx,
        )

    def dot(self, plain: Sequence[float]) -> "EncryptedValue":
        """Plaintext-vector inner product — depth += 1."""
        new_ct = self._ct.dot([float(v) for v in plain])
        return EncryptedValue(
            _ct=new_ct, depth=self.depth + 1, n_slots=1, _ctx=self._ctx,
        )

    def sum(self) -> "EncryptedValue":
        """Reduce-sum over slots into a single-slot ciphertext."""
        new_ct = self._ct.sum()
        return EncryptedValue(
            _ct=new_ct, depth=self.depth, n_slots=1, _ctx=self._ctx,
        )

    # ── Operators for ergonomics ──────────────────────────────────

    def __add__(self, other): return self.add(other)
    def __sub__(self, other): return self.subtract(other)
    def __mul__(self, other): return self.multiply(other)

    def __radd__(self, other): return self.add(other)
    def __rmul__(self, other): return self.multiply(other)

    # ── Serialization ─────────────────────────────────────────────

    def serialize(self) -> bytes:
        """Serialize the ciphertext to bytes (e.g. to persist in AxonStore)."""
        return self._ct.serialize()

    # ── Decryption entry (caller-authorized) ──────────────────────

    def decrypt(self, context: HomomorphicContext | None = None) -> list[float]:
        """Decrypt using this value's bound context.  The `context`
        argument is a redundant integrity check — if supplied, it MUST
        match the binding context."""
        if self._ctx is None:
            raise CalleeBlameError(
                "EncryptedValue is missing its context binding — "
                "was it constructed outside the normal factory?"
            )
        if context is not None and context is not self._ctx:
            raise CallerBlameError(
                "decrypt() context mismatch — caller passed a different "
                "HomomorphicContext than the one that produced this ct"
            )
        return self._ctx.decrypt(self)

    # ── Internals ─────────────────────────────────────────────────

    def _check_ctx(self, other: "EncryptedValue") -> None:
        if other._ctx is not self._ctx:
            raise CallerBlameError(
                "homomorphic op between ciphertexts from DIFFERENT contexts — "
                "cross-context compose is not permitted (key mismatch)"
            )

    def _to_plain(
        self, value: float | Sequence[float]
    ) -> float | list[float]:
        if isinstance(value, (int, float)):
            return float(value)
        return [float(v) for v in value]


# ═══════════════════════════════════════════════════════════════════
#  Integration with Secret[T]
# ═══════════════════════════════════════════════════════════════════

def encrypt_secret(
    secret,
    context: HomomorphicContext,
    *,
    accessor: str,
    purpose: str = "encrypt_for_homomorphic_compute",
) -> EncryptedValue:
    """Extract the payload from a Secret, encrypt it under the given
    context, and RETURN the ciphertext.  The plaintext stays in the
    scope of this function and is not retained anywhere.

    Audit trail: the secret's `reveal` is recorded with the supplied
    accessor/purpose so the operation is forensic.

    Raises CallerBlameError if the payload is not a number or iterable
    of numbers — CKKS only encrypts real-valued data.
    """
    from .secret import Secret  # local import: break circular reference

    if not isinstance(secret, Secret):
        raise CallerBlameError(
            f"encrypt_secret expects a Secret[T]; got {type(secret).__name__}"
        )
    payload = secret.reveal(accessor=accessor, purpose=purpose)
    if isinstance(payload, (int, float)):
        return context.encrypt(float(payload))
    if isinstance(payload, (list, tuple)):
        return context.encrypt([float(v) for v in payload])
    raise CallerBlameError(
        f"CKKS can only encrypt real-valued payloads; "
        f"Secret payload has type {type(payload).__name__}"
    )


__all__ = [
    "CkksParameters",
    "EncryptedValue",
    "HomomorphicContext",
    "encrypt_secret",
]
