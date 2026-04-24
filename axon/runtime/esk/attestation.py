"""
AXON Runtime — Supply-Chain Attestation (ESK Fase 6.6)
=========================================================
SBOM (Software Bill of Materials) generator + content-address hashes for
reproducible, auditable program supply chains.

Design anchors
--------------
• Each compiled IRProgram gets a deterministic content hash — changing
  any symbol, type, flow, shield, etc. changes the root hash.
• An SBOM lists every declaration with its kind, name, and per-node
  hash.  Operators can diff two SBOMs to audit a release.
• Regulatory dossiers (HIPAA, SOC 2) can be generated straight from the
  SBOM + compliance annotations without human summary.
• Format: JSON-serializable, stable key order, UTF-8.

References
----------
• SPDX 2.3 license/component listing concepts.
• SLSA Level 4 build provenance (future: sign the SBOM with Ed25519).
• in-toto attestation bundles (roadmapped post-Fase 6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import IRProgram

from .compliance import REGISTRY as COMPLIANCE_REGISTRY, classify_sector
from .provenance import canonical_bytes, content_hash


def _axon_version() -> str:
    """Resolve the live axon package version at call time.

    Imported lazily so `attestation.py` does not fail if `axon/__init__.py`
    imports this module during package initialisation. Falls back to a
    static fallback only if the package is unimportable (never expected
    in production).
    """
    try:
        from axon import __version__ as _v
        return _v
    except Exception:  # noqa: BLE001
        return "1.4.1"


@dataclass(frozen=True)
class SbomEntry:
    """One declaration in the SBOM."""
    name: str
    kind: str                      # persona | flow | shield | axonendpoint | ...
    content_hash: str
    compliance: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "content_hash": self.content_hash,
            "compliance": list(self.compliance),
        }


@dataclass
class SupplyChainSBOM:
    """Software Bill of Materials for a compiled IRProgram."""

    program_hash: str
    axon_version: str
    entries: list[SbomEntry] = field(default_factory=list)
    dependencies: list[dict[str, str]] = field(default_factory=list)

    def add(self, entry: SbomEntry) -> None:
        self.entries.append(entry)

    def add_dependency(self, name: str, version: str, *, kind: str = "pypi") -> None:
        self.dependencies.append({"name": name, "version": version, "kind": kind})

    def with_compliance(self, *labels: str) -> list[SbomEntry]:
        required = set(labels)
        return [e for e in self.entries if required.issubset(set(e.compliance))]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema":        "axon.esk.sbom.v1",
            "axon_version":  self.axon_version,
            "program_hash":  self.program_hash,
            "entries":       [e.to_dict() for e in self.entries],
            "dependencies":  list(self.dependencies),
            "entry_count":   len(self.entries),
        }


# ═══════════════════════════════════════════════════════════════════
#  Generation
# ═══════════════════════════════════════════════════════════════════

_KIND_TO_ATTR: list[tuple[str, str]] = [
    ("persona",        "personas"),
    ("context",        "contexts"),
    ("anchor",         "anchors"),
    ("tool",           "tools"),
    ("memory",         "memories"),
    ("type",           "types"),
    ("flow",           "flows"),
    ("agent",          "agents"),
    ("shield",         "shields"),
    ("daemon",         "daemons"),
    ("axonstore",      "axonstore_specs"),
    ("axonendpoint",   "endpoints"),
    ("resource",       "resources"),
    ("fabric",         "fabrics"),
    ("manifest",       "manifests"),
    ("observe",        "observations"),
    ("reconcile",      "reconciles"),
    ("lease",          "leases"),
    ("ensemble",       "ensembles"),
    ("session",        "sessions"),
    ("topology",       "topologies"),
    ("immune",         "immunes"),
    ("reflex",         "reflexes"),
    ("heal",           "heals"),
    ("component",      "components"),
    ("view",           "views"),
]


def _ir_node_hash(node: Any) -> str:
    """Hash an IR node via its canonical `to_dict()` representation."""
    try:
        payload = node.to_dict()
    except Exception:  # noqa: BLE001
        payload = {"name": getattr(node, "name", ""), "node_type": getattr(node, "node_type", "")}
    return content_hash(payload)


def generate_sbom(program: IRProgram, *, axon_version: str | None = None) -> SupplyChainSBOM:
    if axon_version is None:
        axon_version = _axon_version()
    """Build an SBOM from an IRProgram — pure function, deterministic."""
    entries: list[SbomEntry] = []
    for kind, attr in _KIND_TO_ATTR:
        bucket = getattr(program, attr, ())
        for node in bucket:
            compliance = tuple(getattr(node, "compliance", ()) or ())
            entries.append(SbomEntry(
                name=getattr(node, "name", ""),
                kind=kind,
                content_hash=_ir_node_hash(node),
                compliance=compliance,
            ))

    payload = {
        "entries": [e.to_dict() for e in entries],
    }
    program_h = content_hash(payload)
    return SupplyChainSBOM(
        program_hash=program_h,
        axon_version=axon_version,
        entries=entries,
    )


# ═══════════════════════════════════════════════════════════════════
#  Compliance dossier — paper-ready regulatory summary
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ComplianceDossier:
    """Human-auditable summary of the program's regulatory posture."""
    program_hash: str
    classes_covered: list[str]
    sectors: list[str]
    entries_per_class: dict[str, int]
    shielded_endpoints: list[str]
    unshielded_regulated: list[str]     # endpoints with κ ≠ ∅ but no shield
    axon_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema":               "axon.esk.compliance.v1",
            "axon_version":         self.axon_version,
            "program_hash":         self.program_hash,
            "classes_covered":      sorted(self.classes_covered),
            "sectors":              sorted(self.sectors),
            "entries_per_class":    dict(self.entries_per_class),
            "shielded_endpoints":   list(self.shielded_endpoints),
            "unshielded_regulated": list(self.unshielded_regulated),
        }


def generate_dossier(
    program: IRProgram,
    *,
    axon_version: str | None = None,
) -> ComplianceDossier:
    """Distill an IRProgram into a regulatory dossier for audits."""
    if axon_version is None:
        axon_version = _axon_version()
    all_classes: set[str] = set()
    entries_per_class: dict[str, int] = {}

    for _kind, attr in _KIND_TO_ATTR:
        for node in getattr(program, attr, ()):
            labels = getattr(node, "compliance", ()) or ()
            for label in labels:
                if label in COMPLIANCE_REGISTRY:
                    all_classes.add(label)
                    entries_per_class[label] = entries_per_class.get(label, 0) + 1

    shielded_endpoints: list[str] = []
    unshielded_regulated: list[str] = []
    for ep in getattr(program, "endpoints", ()):
        if getattr(ep, "compliance", ()):
            if ep.shield_ref:
                shielded_endpoints.append(ep.name)
            else:
                unshielded_regulated.append(ep.name)

    sbom = generate_sbom(program, axon_version=axon_version)
    return ComplianceDossier(
        program_hash=sbom.program_hash,
        classes_covered=list(all_classes),
        sectors=list(classify_sector(all_classes)),
        entries_per_class=entries_per_class,
        shielded_endpoints=shielded_endpoints,
        unshielded_regulated=unshielded_regulated,
        axon_version=axon_version,
    )


__all__ = [
    "ComplianceDossier",
    "InTotoStatement",
    "SbomEntry",
    "SupplyChainSBOM",
    "generate_dossier",
    "generate_in_toto_statement",
    "generate_sbom",
]


# ═══════════════════════════════════════════════════════════════════
#  in-toto attestation bundle (SLSA Level 4) — ESK §6.6.d
# ═══════════════════════════════════════════════════════════════════

_IN_TOTO_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_SLSA_PROVENANCE_TYPE = "https://slsa.dev/provenance/v1"


@dataclass
class InTotoStatement:
    """An in-toto v1 Statement envelope for a compiled AXON program.

    Conforms to the in-toto Attestation Framework v1 (https://in-toto.io/
    attestation/) and the SLSA Provenance v1 predicate schema
    (https://slsa.dev/spec/v1.0/provenance).  Operators can wrap this
    in a DSSE envelope (Dead Simple Signing Envelope) signed by an
    offline CA for SLSA Build Level 3/4 attestation.

    The produced JSON is **content-addressed**: two identical IR
    programs yield byte-identical Statements (deterministic
    canonical encoding), which makes it suitable for reproducible-build
    audits and policy-driven deployment gates (rekor, sigstore).
    """

    subject_name: str
    subject_digest_sha256: str
    predicate: dict[str, Any]
    predicate_type: str = _SLSA_PROVENANCE_TYPE
    statement_type: str = _IN_TOTO_STATEMENT_TYPE

    def to_dict(self) -> dict[str, Any]:
        return {
            "_type": self.statement_type,
            "subject": [
                {
                    "name": self.subject_name,
                    "digest": {"sha256": self.subject_digest_sha256},
                }
            ],
            "predicateType": self.predicate_type,
            "predicate": dict(self.predicate),
        }


def generate_in_toto_statement(
    program: IRProgram,
    *,
    axon_version: str | None = None,
    builder_id: str = "https://axon-lang.io/builders/compiler@v1",
    subject_name: str = "axon-program",
) -> InTotoStatement:
    if axon_version is None:
        axon_version = _axon_version()
    """Emit an in-toto v1 Statement whose predicate is SLSA Provenance v1.

    The predicate captures:
      - buildDefinition.buildType:  Axon compilation
      - buildDefinition.externalParameters:  source hashes / SBOM
      - runDetails.builder.id:  stable URI identifying the build system
      - runDetails.metadata:  SBOM-derived dependency manifest

    Consumers (policy engines, SLSA verifiers) read the Statement to
    decide whether to accept the build artifact.
    """
    sbom = generate_sbom(program, axon_version=axon_version)
    # SLSA Provenance v1 predicate
    predicate = {
        "buildDefinition": {
            "buildType": "https://axon-lang.io/builds/compile@v1",
            "externalParameters": {
                "sbom_hash": sbom.program_hash,
                "axon_version": axon_version,
                "entry_count": len(sbom.entries),
            },
            "internalParameters": {},
            "resolvedDependencies": [
                {
                    "name": dep.get("name", ""),
                    "uri": f"pkg:{dep.get('kind', 'pypi')}/{dep.get('name', '')}@{dep.get('version', '')}",
                }
                for dep in sbom.dependencies
            ],
        },
        "runDetails": {
            "builder": {
                "id": builder_id,
                "version": {"axon": axon_version},
            },
            "metadata": {
                "invocationId": sbom.program_hash,
                "finishedOn": None,  # filled in at build time, not at emit
            },
            "byproducts": [
                {
                    "name": e.name,
                    "uri": f"axon:{e.kind}:{e.name}",
                    "digest": {"sha256": e.content_hash},
                }
                for e in sbom.entries
            ],
        },
    }
    return InTotoStatement(
        subject_name=subject_name,
        subject_digest_sha256=sbom.program_hash,
        predicate=predicate,
    )
