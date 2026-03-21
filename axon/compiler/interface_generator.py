"""
AXON Compiler — Epistemic Module System: Interface Generator
==============================================================
Phase 1 of the EMS compilation pipeline.

Generates `.axi` (AXON Interface) files — the cognitive equivalent
of OCaml's `.cmi` or GHC's `.hi` files. An interface contains only
the **exported signatures** of a module, not the implementation.

Design lineage:
  - OCaml .cmi:  Typed interface files for separate compilation
  - GHC .hi:     Content-hashed ABI for incremental builds
  - 1ML:         Unified signature representation
  - Backpack:    Signature-based mixin linking

Key innovation (axon-lang original):
  Each interface carries an **epistemic floor** — the minimum
  epistemic guarantee level the module provides, derived from
  its composition of know/believe/speculate/doubt blocks.

Pipeline position:
  ModuleResolver → **InterfaceGenerator** → IRGenerator → CompilationCache
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  EPISTEMIC LEVELS (partial order lattice)
# ═══════════════════════════════════════════════════════════════════

class EpistemicLevel:
    """
    The epistemic type lattice as a partial order.

    T (CorroboratedFact)
        ├── CitedFact
        │   └── FactualClaim
        │       ├── ContestedClaim
        │       └── Uncertainty (⊥)
        ├── Opinion
        └── Speculation

    For module-level floor computation, we use a simplified
    four-level lattice that maps to the epistemic block types:
        know > believe > doubt > speculate
    """
    KNOW = 4        # Maximum factual rigor
    BELIEVE = 3     # Moderate confidence
    DOUBT = 2       # Adversarial validation
    SPECULATE = 1   # Creative freedom
    UNSPECIFIED = 0  # No epistemic block used

    _NAMES = {4: "know", 3: "believe", 2: "doubt", 1: "speculate", 0: "unspecified"}
    _FROM_NAME = {v: k for k, v in _NAMES.items()}

    @classmethod
    def name(cls, level: int) -> str:
        return cls._NAMES.get(level, "unknown")

    @classmethod
    def from_name(cls, name: str) -> int:
        return cls._FROM_NAME.get(name, cls.UNSPECIFIED)

    @classmethod
    def is_compatible(cls, provider: int, consumer: int) -> bool:
        """
        Check if a provider module's epistemic floor satisfies
        the consumer's requirements.

        Rule: provider_floor >= consumer_requirement
        A 'know' module can be imported by anyone.
        A 'speculate' module can only be imported by speculate blocks.
        """
        if consumer == cls.UNSPECIFIED:
            return True  # No requirement
        return provider >= consumer


# ═══════════════════════════════════════════════════════════════════
#  SIGNATURE TYPES — exported cognitive primitive descriptors
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PersonaSignature:
    """Exported signature of a persona — identity without implementation."""
    name: str
    domain: tuple[str, ...] = ()
    tone: str = ""
    confidence_threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "domain": list(self.domain),
                "tone": self.tone, "confidence_threshold": self.confidence_threshold}


@dataclass(frozen=True)
class AnchorSignature:
    """Exported signature of an anchor — constraint hash without full text."""
    name: str
    constraint_hash: str = ""     # SHA-256 of require + reject + enforce
    on_violation: str = "raise"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "constraint_hash": self.constraint_hash,
                "on_violation": self.on_violation}


@dataclass(frozen=True)
class FlowSignature:
    """Exported signature of a flow — step count + output type."""
    name: str
    step_count: int = 0
    output_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "step_count": self.step_count,
                "output_type": self.output_type}


@dataclass(frozen=True)
class ShieldSignature:
    """Exported signature of a shield — capabilities without scan rules."""
    name: str
    scan_categories: tuple[str, ...] = ()
    on_breach: str = "halt"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "scan_categories": list(self.scan_categories),
                "on_breach": self.on_breach}


@dataclass(frozen=True)
class MandateSignature:
    """Exported signature of a mandate — convergence bounds."""
    name: str
    tolerance: float = 0.01
    max_steps: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "tolerance": self.tolerance,
                "max_steps": self.max_steps}


@dataclass(frozen=True)
class PsycheSignature:
    """Exported signature of a psyche — trait dimensions."""
    name: str
    trait_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "trait_count": self.trait_count}


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE INTERFACE — the .axi file representation
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CognitiveInterface:
    """
    The .axi file — what a module PROMISES to the world.

    This is the OCaml .cmi equivalent for axon-lang. It contains
    only the exported cognitive signatures, never the implementation
    details. Other modules compile against this interface, not the
    full source.

    The epistemic_floor is axon-lang's unique contribution:
    it propagates epistemic guarantees across module boundaries.
    """
    module_path: tuple[str, ...] = ()
    content_hash: str = ""              # SHA-256 of source file

    # Exported cognitive primitive signatures
    personas: dict[str, PersonaSignature] = field(default_factory=dict)
    anchors: dict[str, AnchorSignature] = field(default_factory=dict)
    flows: dict[str, FlowSignature] = field(default_factory=dict)
    shields: dict[str, ShieldSignature] = field(default_factory=dict)
    mandates: dict[str, MandateSignature] = field(default_factory=dict)
    psyches: dict[str, PsycheSignature] = field(default_factory=dict)

    # Epistemic contract (axon-lang original)
    epistemic_floor: int = EpistemicLevel.UNSPECIFIED

    # ── Interface hash (GHC ABI hash inspired) ────────────────

    @property
    def interface_hash(self) -> str:
        """
        Content-addressable hash of the interface itself.

        GHC/Bazel insight: if the source changes but the interface
        hash stays the same, downstream dependents DON'T need
        recompilation (early cutoff).
        """
        sig_data = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(sig_data.encode("utf-8")).hexdigest()[:16]

    # ── Lookup ────────────────────────────────────────────────

    def lookup(self, name: str) -> Any:
        """
        Look up an exported symbol by name across all primitive categories.

        Returns the signature object or None if not found.
        """
        for registry in (self.personas, self.anchors, self.flows,
                         self.shields, self.mandates, self.psyches):
            if name in registry:
                return registry[name]
        return None

    def has_export(self, name: str) -> bool:
        """Check if a name is exported by this module."""
        return self.lookup(name) is not None

    def all_exports(self) -> list[str]:
        """Return all exported symbol names."""
        names: list[str] = []
        for registry in (self.personas, self.anchors, self.flows,
                         self.shields, self.mandates, self.psyches):
            names.extend(registry.keys())
        return names

    # ── Serialization ─────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict for .axi file storage."""
        return {
            "module_path": list(self.module_path),
            "content_hash": self.content_hash,
            "epistemic_floor": EpistemicLevel.name(self.epistemic_floor),
            "personas": {k: v.to_dict() for k, v in self.personas.items()},
            "anchors": {k: v.to_dict() for k, v in self.anchors.items()},
            "flows": {k: v.to_dict() for k, v in self.flows.items()},
            "shields": {k: v.to_dict() for k, v in self.shields.items()},
            "mandates": {k: v.to_dict() for k, v in self.mandates.items()},
            "psyches": {k: v.to_dict() for k, v in self.psyches.items()},
        }

    def save(self, path: Path) -> None:
        """Write this interface to a .axi JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> CognitiveInterface:
        """Load a .axi interface file from disk."""
        data = json.loads(path.read_text(encoding="utf-8"))
        iface = cls(
            module_path=tuple(data.get("module_path", [])),
            content_hash=data.get("content_hash", ""),
            epistemic_floor=EpistemicLevel.from_name(
                data.get("epistemic_floor", "unspecified")
            ),
        )

        for name, sig in data.get("personas", {}).items():
            iface.personas[name] = PersonaSignature(
                name=sig["name"], domain=tuple(sig.get("domain", [])),
                tone=sig.get("tone", ""),
                confidence_threshold=sig.get("confidence_threshold"),
            )
        for name, sig in data.get("anchors", {}).items():
            iface.anchors[name] = AnchorSignature(
                name=sig["name"],
                constraint_hash=sig.get("constraint_hash", ""),
                on_violation=sig.get("on_violation", "raise"),
            )
        for name, sig in data.get("flows", {}).items():
            iface.flows[name] = FlowSignature(
                name=sig["name"], step_count=sig.get("step_count", 0),
                output_type=sig.get("output_type", ""),
            )
        for name, sig in data.get("shields", {}).items():
            iface.shields[name] = ShieldSignature(
                name=sig["name"],
                scan_categories=tuple(sig.get("scan_categories", [])),
                on_breach=sig.get("on_breach", "halt"),
            )
        for name, sig in data.get("mandates", {}).items():
            iface.mandates[name] = MandateSignature(
                name=sig["name"], tolerance=sig.get("tolerance", 0.01),
                max_steps=sig.get("max_steps", 50),
            )
        for name, sig in data.get("psyches", {}).items():
            iface.psyches[name] = PsycheSignature(
                name=sig["name"], trait_count=sig.get("trait_count", 0),
            )

        return iface


# ═══════════════════════════════════════════════════════════════════
#  INTERFACE GENERATOR — extract public surface from IRProgram
# ═══════════════════════════════════════════════════════════════════

class InterfaceGenerator:
    """
    Generates a CognitiveInterface (.axi) from a compiled IRProgram.

    This extracts only the public-facing signatures: names, types,
    and contract bounds — never implementation details like prompt
    text, step bodies, or flow logic.
    """

    @staticmethod
    def generate(
        ir_program: Any,
        module_path: tuple[str, ...],
        content_hash: str,
    ) -> CognitiveInterface:
        """
        Extract the cognitive interface from a compiled IRProgram.

        Args:
            ir_program:   The compiled IRProgram node.
            module_path:  The dotted module path for this file.
            content_hash: SHA-256 of the source file.

        Returns:
            A CognitiveInterface ready for .axi serialization.
        """
        iface = CognitiveInterface(
            module_path=module_path,
            content_hash=content_hash,
        )

        # Extract persona signatures
        for persona in getattr(ir_program, "personas", ()):
            iface.personas[persona.name] = PersonaSignature(
                name=persona.name,
                domain=getattr(persona, "domain", ()),
                tone=getattr(persona, "tone", ""),
                confidence_threshold=getattr(persona, "confidence_threshold", None),
            )

        # Extract anchor signatures (hash the constraint, don't export it)
        for anchor in getattr(ir_program, "anchors", ()):
            constraint_text = (
                getattr(anchor, "require", "") +
                "|".join(getattr(anchor, "reject", ())) +
                getattr(anchor, "enforce", "")
            )
            iface.anchors[anchor.name] = AnchorSignature(
                name=anchor.name,
                constraint_hash=hashlib.sha256(
                    constraint_text.encode("utf-8")
                ).hexdigest()[:16],
                on_violation=getattr(anchor, "on_violation", "raise"),
            )

        # Extract flow signatures
        for flow in getattr(ir_program, "flows", ()):
            iface.flows[flow.name] = FlowSignature(
                name=flow.name,
                step_count=len(getattr(flow, "steps", ())),
                output_type=getattr(flow, "output_type", ""),
            )

        # Extract shield signatures
        for shield in getattr(ir_program, "shields", ()):
            iface.shields[shield.name] = ShieldSignature(
                name=shield.name,
                scan_categories=getattr(shield, "scan", ()),
                on_breach=getattr(shield, "on_breach", "halt"),
            )

        # Extract mandate signatures
        for mandate in getattr(ir_program, "mandate_specs", ()):
            iface.mandates[mandate.name] = MandateSignature(
                name=mandate.name,
                tolerance=getattr(mandate, "tolerance", 0.01),
                max_steps=getattr(mandate, "max_steps", 50),
            )

        # Extract psyche signatures
        for psyche in getattr(ir_program, "psyche_specs", ()):
            iface.psyches[psyche.name] = PsycheSignature(
                name=psyche.name,
                trait_count=len(getattr(psyche, "traits", ())),
            )

        # Compute epistemic floor from epistemic blocks
        iface.epistemic_floor = InterfaceGenerator._compute_epistemic_floor(
            ir_program
        )

        return iface

    @staticmethod
    def _compute_epistemic_floor(ir_program: Any) -> int:
        """
        Derive the module's epistemic floor from its content.

        Rules:
          - If any 'know' block exists → floor = KNOW
          - If any anchor with confidence_floor > 0.8 → floor = KNOW
          - If any 'believe' block exists → floor = BELIEVE
          - If any 'doubt' block exists → floor = DOUBT
          - If any 'speculate' block exists → floor = SPECULATE
          - Else → UNSPECIFIED

        The floor is the HIGHEST epistemic level present, because
        the module CAN provide that level of guarantee.
        """
        max_level = EpistemicLevel.UNSPECIFIED

        # Check anchors (anchors imply know-level guarantees)
        anchors = getattr(ir_program, "anchors", ())
        if anchors:
            max_level = max(max_level, EpistemicLevel.KNOW)

        # Check runs for epistemic flow references
        for run in getattr(ir_program, "runs", ()):
            flow = getattr(run, "flow", None)
            if flow:
                for step in getattr(flow, "body", ()):
                    node_type = getattr(step, "node_type", "")
                    if node_type == "epistemic_block":
                        scope = getattr(step, "scope", "")
                        level = EpistemicLevel.from_name(scope)
                        max_level = max(max_level, level)

        # Check shields (shields imply security-aware = believe+)
        if getattr(ir_program, "shields", ()):
            max_level = max(max_level, EpistemicLevel.BELIEVE)

        return max_level


# ═══════════════════════════════════════════════════════════════════
#  MODULE REGISTRY — namespace for cross-file symbol resolution
# ═══════════════════════════════════════════════════════════════════

class ModuleRegistry:
    """
    Holds compiled CognitiveInterfaces for cross-file resolution.

    The IRGenerator uses this registry to look up imported symbols
    during Phase 2 (cross-reference resolution). Each interface
    is keyed by its dotted module path.

    Usage:
        registry = ModuleRegistry()
        registry.register(("axon", "security"), security_interface)
        iface = registry.resolve(("axon", "security"))
    """

    def __init__(
        self,
        interfaces: dict[tuple[str, ...], CognitiveInterface] | None = None,
    ):
        self._interfaces: dict[str, CognitiveInterface] = {}
        if interfaces:
            for path, iface in interfaces.items():
                self.register(path, iface)

    def register(
        self, module_path: tuple[str, ...], interface: CognitiveInterface
    ) -> None:
        """Register a compiled interface for cross-file resolution."""
        key = ".".join(module_path)
        self._interfaces[key] = interface

    def resolve(self, module_path: tuple[str, ...]) -> CognitiveInterface | None:
        """Look up an interface by dotted module path."""
        key = ".".join(module_path)
        return self._interfaces.get(key)

    def has_module(self, module_path: tuple[str, ...]) -> bool:
        """Check if a module is registered."""
        return ".".join(module_path) in self._interfaces

    def all_modules(self) -> list[str]:
        """Return all registered module keys."""
        return list(self._interfaces.keys())

    def all_interfaces(self) -> list[CognitiveInterface]:
        """Return all registered interfaces."""
        return list(self._interfaces.values())

    def __len__(self) -> int:
        return len(self._interfaces)

    def __contains__(self, module_path: tuple[str, ...]) -> bool:
        return self.has_module(module_path)
