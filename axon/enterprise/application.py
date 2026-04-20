"""
AXON Enterprise — EnterpriseApplication Facade
=================================================
Single entry point that wires the full production stack for an .axon program.

This is the integration layer referenced by Fase 7.1 of the plan.  It
does NOT reinvent primitives — it composes them:

    .axon source
         │
         ▼  (Lexer + Parser + TypeChecker + IRGenerator — Fases 1/4/6)
    IRProgram
         │
         ▼  (ImmuneRuntime — Fase 5)
    anomaly detection + reflex + heal
         │
         ▼  (Handler — Fase 2)
    provision / observe against real infra
         │
         ▼  (EpistemicIntrusionDetector + ProvenanceChain — Fase 6)
    audit-grade output + dossier + SBOM

An adopter that wants fine-grained control can still drop to the raw
modules; this facade is a convenience, not a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRProgram
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.runtime.esk import (
    ComplianceDossier,
    EpistemicIntrusionDetector,
    HmacSigner,
    ProvenanceChain,
    SupplyChainSBOM,
    generate_dossier,
    generate_sbom,
)
from axon.runtime.handlers import DryRunHandler, Handler, HandlerOutcome
from axon.runtime.immune import ImmuneRuntime


HandlerName = Literal["dry_run", "terraform", "kubernetes", "aws", "docker"]
"""Names of bundled handler factories (concrete SDKs lazy-loaded on demand)."""


# ═══════════════════════════════════════════════════════════════════
#  Startup report — what the facade produced
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EnterpriseStartupReport:
    """Summary emitted by `EnterpriseApplication.provision()`."""
    handler: str
    manifests_provisioned: int
    observations_executed: int
    outcomes: tuple[HandlerOutcome, ...]
    type_errors: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "handler":                self.handler,
            "manifests_provisioned":  self.manifests_provisioned,
            "observations_executed":  self.observations_executed,
            "outcomes":               [o.to_dict() for o in self.outcomes],
            "type_errors":            self.type_errors,
        }


# ═══════════════════════════════════════════════════════════════════
#  The facade itself
# ═══════════════════════════════════════════════════════════════════

_HANDLER_FACTORIES: dict[str, str] = {
    "dry_run":    "axon.runtime.handlers.dry_run:DryRunHandler",
    "terraform":  "axon.runtime.handlers.terraform:TerraformHandler",
    "kubernetes": "axon.runtime.handlers.kubernetes:KubernetesHandler",
    "aws":        "axon.runtime.handlers.aws:AwsHandler",
    "docker":     "axon.runtime.handlers.docker:DockerHandler",
}


def _load_handler(name: str) -> type[Handler]:
    """Lazy-resolve a handler class by name; keeps SDKs optional."""
    if name not in _HANDLER_FACTORIES:
        raise ValueError(
            f"unknown handler '{name}'. Available: "
            f"{', '.join(sorted(_HANDLER_FACTORIES))}"
        )
    module_path, class_name = _HANDLER_FACTORIES[name].split(":")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class EnterpriseApplication:
    """
    Unified SDK facade that turns an .axon program into a deployable
    production service with ESK-grade security, compliance dossier, and
    SBOM in a handful of method calls.

    Construction paths
    ------------------
        EnterpriseApplication.from_source(source_text)   # in-memory program
        EnterpriseApplication.from_file(path)            # read from disk
        EnterpriseApplication.from_ir(ir_program)        # already compiled

    Key methods
    -----------
        check()       → list[TypeError]     — compile-time validation
        provision(…)  → EnterpriseStartupReport
        observe()     → HealthReport stream (via ImmuneRuntime)
        dossier()     → ComplianceDossier   — compliance audit artifact
        sbom()        → SupplyChainSBOM     — supply-chain artifact
    """

    def __init__(
        self,
        program: IRProgram,
        *,
        source_path: str = "",
        axon_version: str = "1.0.0",
        signer_key: bytes | None = None,
    ) -> None:
        self.program = program
        self.source_path = source_path
        self.axon_version = axon_version
        self._signer = HmacSigner(key=signer_key) if signer_key else HmacSigner.random()
        self._chain: ProvenanceChain = ProvenanceChain(self._signer)
        self._immune = ImmuneRuntime(program)
        self._eid = EpistemicIntrusionDetector(
            trigger_level="speculate", chain=self._chain,
        )

    # ── Construction helpers ──────────────────────────────────────

    @classmethod
    def from_source(
        cls,
        source: str,
        *,
        source_path: str = "<inline>",
        axon_version: str = "1.0.0",
        strict: bool = True,
    ) -> "EnterpriseApplication":
        """Compile an in-memory .axon source string.  If `strict=True`
        (default), type errors raise immediately; otherwise they land in
        `EnterpriseStartupReport.type_errors`."""
        tree = Parser(Lexer(source).tokenize()).parse()
        errors = TypeChecker(tree).check()
        if strict and errors:
            messages = "\n".join(f"  • {e.message}" for e in errors)
            raise ValueError(
                f"axon program {source_path!r} has {len(errors)} compile "
                f"error(s):\n{messages}"
            )
        ir = IRGenerator().generate(tree)
        app = cls(ir, source_path=source_path, axon_version=axon_version)
        app._type_errors_count = len(errors)  # type: ignore[attr-defined]
        return app

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        axon_version: str = "1.0.0",
        strict: bool = True,
    ) -> "EnterpriseApplication":
        path_obj = Path(path)
        source = path_obj.read_text(encoding="utf-8")
        return cls.from_source(
            source,
            source_path=str(path_obj),
            axon_version=axon_version,
            strict=strict,
        )

    @classmethod
    def from_ir(
        cls,
        program: IRProgram,
        *,
        axon_version: str = "1.0.0",
    ) -> "EnterpriseApplication":
        return cls(program, source_path="<ir>", axon_version=axon_version)

    # ── Runtime-facing API ────────────────────────────────────────

    def provision(
        self,
        *,
        handler: HandlerName | Handler = "dry_run",
        handler_kwargs: dict[str, Any] | None = None,
    ) -> EnterpriseStartupReport:
        """β-reduce the IRIntentionTree against the chosen Handler."""
        concrete = self._resolve_handler(handler, handler_kwargs)
        outcomes = concrete.interpret_program(self.program)
        manifests = sum(1 for o in outcomes if o.operation == "provision")
        observations = sum(1 for o in outcomes if o.operation == "observe")
        handler_name = getattr(concrete, "name", concrete.__class__.__name__)
        return EnterpriseStartupReport(
            handler=handler_name,
            manifests_provisioned=manifests,
            observations_executed=observations,
            outcomes=tuple(outcomes),
            type_errors=getattr(self, "_type_errors_count", 0),
        )

    def observe(self, immune_name: str, sample: Any) -> tuple[Any, list[Any], list[Any]]:
        """Forward to `ImmuneRuntime.observe()`; see Fase 5 for semantics."""
        return self._immune.observe(immune_name, sample)

    def train_immune(self, immune_name: str, samples: list) -> None:
        self._immune.train(immune_name, samples)

    def check_intrusion(self, report) -> Any:
        """Route a HealthReport through the EpistemicIntrusionDetector."""
        return self._eid.observe(report)

    # ── ESK artifacts ────────────────────────────────────────────

    def dossier(self) -> ComplianceDossier:
        return generate_dossier(self.program, axon_version=self.axon_version)

    def sbom(self) -> SupplyChainSBOM:
        return generate_sbom(self.program, axon_version=self.axon_version)

    def provenance_chain(self) -> ProvenanceChain:
        return self._chain

    @property
    def immune_runtime(self) -> ImmuneRuntime:
        return self._immune

    # ── Internals ────────────────────────────────────────────────

    def _resolve_handler(
        self,
        handler: HandlerName | Handler,
        kwargs: dict[str, Any] | None,
    ) -> Handler:
        if isinstance(handler, Handler):
            return handler
        cls = _load_handler(handler)
        return cls(**(kwargs or {}))


__all__ = [
    "EnterpriseApplication",
    "EnterpriseStartupReport",
    "HandlerName",
]
