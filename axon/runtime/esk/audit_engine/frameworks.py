"""
AXON Audit Evidence Engine — Framework Catalog
=================================================
Structured catalog of the controls each external audit framework tests,
and which AXON primitive / module / generated artifact provides evidence
for each one.

This catalog is the single source of truth consumed by:
  • `GapAnalyzer`                    — identifies missing evidence
  • `ControlImplementationStatement`  — auto-populates the "how"
  • `EvidencePackager`                — decides what to bundle per framework
  • `RiskRegister`                    — maps threats to applicable controls
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FrameworkId(str, Enum):
    """Canonical identifiers for supported external audit frameworks."""
    SOC2_TYPE_II = "soc2_type_ii"
    ISO_27001 = "iso_27001"
    FIPS_140_3 = "fips_140_3"
    CC_EAL4_PLUS = "cc_eal4_plus"


class EvidenceKind(str, Enum):
    """How the evidence for a control is produced at audit time."""
    COMPILE_TIME = "compile_time"      # axon check enforces it
    RUNTIME_INVARIANT = "runtime_invariant"  # a Python invariant (e.g. Secret[T])
    AUTOMATED_ARTIFACT = "automated_artifact"  # axon dossier / sbom / in-toto
    TEST_SUITE = "test_suite"          # pytest proves the property
    MANUAL_POLICY = "manual_policy"    # business-authored policy doc
    EXTERNAL_OPERATIONAL = "external_operational"  # out of repo (ops/CI logs)


@dataclass(frozen=True)
class Control:
    """A single control within an audit framework."""
    framework: FrameworkId
    control_id: str          # e.g. "CC6.1" (SOC 2), "A.5.23" (ISO 27001)
    title: str
    axon_primitive: str      # which AXON feature addresses it (human-readable)
    evidence_kind: EvidenceKind
    evidence_locator: str    # file/path/test-id pointing to the artifact

    def key(self) -> str:
        return f"{self.framework.value}:{self.control_id}"


# ═══════════════════════════════════════════════════════════════════
#  SOC 2 Type II — Common Criteria + C + PI + P subset
# ═══════════════════════════════════════════════════════════════════

_SOC2: list[Control] = [
    Control(FrameworkId.SOC2_TYPE_II, "CC1.1", "Commitment to integrity", "Zero-shortcuts policy + signed commits", EvidenceKind.MANUAL_POLICY, "CODE_OF_CONDUCT.md (repo-external)"),
    Control(FrameworkId.SOC2_TYPE_II, "CC2.1", "Quality information", "axon check compile-time compliance", EvidenceKind.COMPILE_TIME, "axon.compiler.type_checker._check_regulatory_compliance"),
    Control(FrameworkId.SOC2_TYPE_II, "CC3.1", "Objectives specification", "manifest.compliance declares system's κ", EvidenceKind.COMPILE_TIME, "axon.compiler.ast_nodes.ManifestDefinition"),
    Control(FrameworkId.SOC2_TYPE_II, "CC3.2", "Risk identification", "immune + KL-divergence baseline", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.immune.AnomalyDetector"),
    Control(FrameworkId.SOC2_TYPE_II, "CC3.3", "Fraud potential", "reflex action quarantine/terminate", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.immune.ReflexEngine"),
    Control(FrameworkId.SOC2_TYPE_II, "CC4.1", "Control activities", "ESK 6 subsystems", EvidenceKind.TEST_SUITE, "tests/test_phase6_*.py"),
    Control(FrameworkId.SOC2_TYPE_II, "CC4.2", "Technology controls", "shield + type checker + Phase 4 pass", EvidenceKind.COMPILE_TIME, "axon.compiler.type_checker"),
    Control(FrameworkId.SOC2_TYPE_II, "CC5.1", "Policies deployment", "axonendpoint.shield binding", EvidenceKind.COMPILE_TIME, "axon.compiler.ast_nodes.AxonEndpointDefinition"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.1", "Logical access controls", "Secret[T] with audit trail", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.Secret"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.2", "Credential provisioning", "Handler-level credential + CT-3 classification", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.handlers.base"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.3", "Access modification/removal", "lease τ-decay", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.lease_kernel.LeaseKernel"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.6", "Boundary access controls", "axonendpoint.shield mandatory", EvidenceKind.COMPILE_TIME, "_check_regulatory_compliance"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.7", "Information transmission restriction", "Secret[T] no-materialize", EvidenceKind.RUNTIME_INVARIANT, "tests/test_phase6_runtime.py::TestSecret"),
    Control(FrameworkId.SOC2_TYPE_II, "CC6.8", "Unauthorized change prevention", "ProvenanceChain Merkle", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.ProvenanceChain"),
    Control(FrameworkId.SOC2_TYPE_II, "CC7.1", "Event detection", "immune + EID", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.EpistemicIntrusionDetector"),
    Control(FrameworkId.SOC2_TYPE_II, "CC7.2", "Anomaly monitoring", "KL-based AnomalyDetector", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.immune.AnomalyDetector"),
    Control(FrameworkId.SOC2_TYPE_II, "CC7.3", "Incident evaluation", "EID severity mapping", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.eid.IntrusionEvent"),
    Control(FrameworkId.SOC2_TYPE_II, "CC7.4", "Incident response", "reflex + heal linear", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.immune.HealKernel"),
    Control(FrameworkId.SOC2_TYPE_II, "CC7.5", "Recovery", "reconcile Active Inference", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.reconcile_loop.ReconcileLoop"),
    Control(FrameworkId.SOC2_TYPE_II, "CC8.1", "Change authorization", "SBOM deterministic content_hash", EvidenceKind.AUTOMATED_ARTIFACT, "axon sbom CLI"),
    Control(FrameworkId.SOC2_TYPE_II, "CC9.1", "Risk mitigation activities", "PrivacyBudget ε-tracker", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.PrivacyBudget"),
    Control(FrameworkId.SOC2_TYPE_II, "CC9.2", "Vendor risk management", "SBOM dependencies list", EvidenceKind.AUTOMATED_ARTIFACT, "axon sbom CLI"),
    Control(FrameworkId.SOC2_TYPE_II, "C1.1", "Confidential information identification", "type κ annotation", EvidenceKind.COMPILE_TIME, "TypeDefinition.compliance"),
    Control(FrameworkId.SOC2_TYPE_II, "C1.2", "Confidential information disposal", "lease τ-decay + Secret audit", EvidenceKind.RUNTIME_INVARIANT, "LeaseKernel + Secret.audit_trail"),
    Control(FrameworkId.SOC2_TYPE_II, "PI1.1", "Processing objectives", "axon check passes ⟺ objectives met", EvidenceKind.COMPILE_TIME, "axon check exit 0"),
    Control(FrameworkId.SOC2_TYPE_II, "PI1.4", "Output completeness", "Byzantine ensemble quorum", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.ensemble_aggregator"),
    Control(FrameworkId.SOC2_TYPE_II, "PI1.5", "Information retention", "ProvenanceChain append-only", EvidenceKind.RUNTIME_INVARIANT, "ProvenanceChain.append"),
    Control(FrameworkId.SOC2_TYPE_II, "P1.1", "Notice to data subjects", "dossier classes_covered", EvidenceKind.AUTOMATED_ARTIFACT, "axon dossier CLI"),
    Control(FrameworkId.SOC2_TYPE_II, "P4.1", "Collection limitation", "Differential Privacy mechanisms", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.privacy"),
    Control(FrameworkId.SOC2_TYPE_II, "P5.1", "Data subject access", "Secret audit + ProvenanceChain", EvidenceKind.RUNTIME_INVARIANT, "Secret.audit_trail"),
    Control(FrameworkId.SOC2_TYPE_II, "P6.1", "Disclosure restriction", "shield<GDPR> mandatory gate", EvidenceKind.COMPILE_TIME, "_check_regulatory_compliance"),
]


# ═══════════════════════════════════════════════════════════════════
#  ISO 27001:2022 — Annex A subset (organizational + technological)
# ═══════════════════════════════════════════════════════════════════

_ISO_27001: list[Control] = [
    Control(FrameworkId.ISO_27001, "A.5.1", "Information security policies", "manifest.compliance declarations", EvidenceKind.COMPILE_TIME, "ManifestDefinition"),
    Control(FrameworkId.ISO_27001, "A.5.2", "Security roles", "heal.mode human_in_loop", EvidenceKind.RUNTIME_INVARIANT, "HealDefinition.mode"),
    Control(FrameworkId.ISO_27001, "A.5.3", "Segregation of duties", "shield.allow_tools / deny_tools", EvidenceKind.COMPILE_TIME, "ShieldDefinition"),
    Control(FrameworkId.ISO_27001, "A.5.7", "Threat intelligence", "immune baseline-learned KL", EvidenceKind.RUNTIME_INVARIANT, "AnomalyDetector"),
    Control(FrameworkId.ISO_27001, "A.5.8", "InfoSec in project management", "CI axon check gate", EvidenceKind.EXTERNAL_OPERATIONAL, ".github/workflows/*.yml"),
    Control(FrameworkId.ISO_27001, "A.5.23", "Cloud services InfoSec", "Handler protocol abstraction", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.handlers"),
    Control(FrameworkId.ISO_27001, "A.5.24", "Incident management planning", "immune+reflex+heal+EID", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.immune + esk.eid"),
    Control(FrameworkId.ISO_27001, "A.5.25", "Event assessment", "EID classify_severity", EvidenceKind.RUNTIME_INVARIANT, "EpistemicIntrusionDetector.observe"),
    Control(FrameworkId.ISO_27001, "A.5.26", "Incident response", "reflex signed_trace", EvidenceKind.RUNTIME_INVARIANT, "ReflexEngine"),
    Control(FrameworkId.ISO_27001, "A.5.27", "Learning from incidents", "ProvenanceChain ledger", EvidenceKind.AUTOMATED_ARTIFACT, "ProvenanceChain.entries"),
    Control(FrameworkId.ISO_27001, "A.5.28", "Evidence collection", "Merkle chain + HMAC", EvidenceKind.AUTOMATED_ARTIFACT, "ProvenanceChain.append"),
    Control(FrameworkId.ISO_27001, "A.5.30", "Business continuity ICT", "reconcile self-healing", EvidenceKind.RUNTIME_INVARIANT, "ReconcileLoop"),
    Control(FrameworkId.ISO_27001, "A.5.33", "Records protection", "Immutable ProvenanceChain + SBOM", EvidenceKind.AUTOMATED_ARTIFACT, "axon sbom"),
    Control(FrameworkId.ISO_27001, "A.5.34", "Privacy / PII protection", "compliance [GDPR, CCPA] + PrivacyBudget + Secret[T]", EvidenceKind.COMPILE_TIME, "TypeDefinition.compliance + PrivacyBudget"),
    Control(FrameworkId.ISO_27001, "A.5.36", "Compliance with policies", "axon check enforces RTT", EvidenceKind.COMPILE_TIME, "_check_regulatory_compliance"),
    Control(FrameworkId.ISO_27001, "A.8.1", "User endpoint devices", "axonendpoint.shield gate", EvidenceKind.COMPILE_TIME, "AxonEndpointDefinition"),
    Control(FrameworkId.ISO_27001, "A.8.2", "Privileged access rights", "lease τ-decay", EvidenceKind.RUNTIME_INVARIANT, "LeaseKernel"),
    Control(FrameworkId.ISO_27001, "A.8.3", "Information access restriction", "shield.allow_tools + Secret[T]", EvidenceKind.RUNTIME_INVARIANT, "ShieldDefinition + Secret"),
    Control(FrameworkId.ISO_27001, "A.8.5", "Secure authentication", "Handler credential flow + CT-3", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.handlers"),
    Control(FrameworkId.ISO_27001, "A.8.6", "Capacity management", "resource.capacity + manifest.zones", EvidenceKind.COMPILE_TIME, "ResourceDefinition"),
    Control(FrameworkId.ISO_27001, "A.8.7", "Protection against malware", "immune behavioral detection", EvidenceKind.RUNTIME_INVARIANT, "AnomalyDetector + ReflexEngine"),
    Control(FrameworkId.ISO_27001, "A.8.8", "Technical vulnerability management", "heal + human_in_loop + signed", EvidenceKind.RUNTIME_INVARIANT, "HealKernel"),
    Control(FrameworkId.ISO_27001, "A.8.9", "Configuration management", "deterministic SBOM program_hash", EvidenceKind.AUTOMATED_ARTIFACT, "axon sbom"),
    Control(FrameworkId.ISO_27001, "A.8.10", "Information deletion", "lease on_expire anchor_breach", EvidenceKind.RUNTIME_INVARIANT, "LeaseKernel"),
    Control(FrameworkId.ISO_27001, "A.8.12", "Data leakage prevention", "Secret[T] no-materialize", EvidenceKind.RUNTIME_INVARIANT, "tests/test_phase6_runtime.py::TestSecret"),
    Control(FrameworkId.ISO_27001, "A.8.13", "Information backup", "resource.lifetime persistent + axonstore", EvidenceKind.COMPILE_TIME, "ResourceDefinition"),
    Control(FrameworkId.ISO_27001, "A.8.15", "Logging", "reflex HMAC signed_trace", EvidenceKind.RUNTIME_INVARIANT, "ReflexEngine"),
    Control(FrameworkId.ISO_27001, "A.8.16", "Monitoring", "immune continuous sensing", EvidenceKind.RUNTIME_INVARIANT, "AnomalyDetector"),
    Control(FrameworkId.ISO_27001, "A.8.17", "Clock synchronization", "ISO-8601 UTC timestamps", EvidenceKind.RUNTIME_INVARIANT, "LambdaEnvelope.tau"),
    Control(FrameworkId.ISO_27001, "A.8.20", "Network security", "Handler CT-3 partition classification", EvidenceKind.RUNTIME_INVARIANT, "NetworkPartitionError"),
    Control(FrameworkId.ISO_27001, "A.8.23", "Web filtering", "shield.scan threat categories", EvidenceKind.COMPILE_TIME, "ShieldDefinition.scan"),
    Control(FrameworkId.ISO_27001, "A.8.24", "Use of cryptography", "HmacSigner + Ed25519Signer + DilithiumSigner", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.provenance"),
    Control(FrameworkId.ISO_27001, "A.8.25", "SDL", "axon check CI gate", EvidenceKind.EXTERNAL_OPERATIONAL, ".github/workflows"),
    Control(FrameworkId.ISO_27001, "A.8.26", "Application security requirements", "compliance declarations", EvidenceKind.COMPILE_TIME, "TypeDefinition + ShieldDefinition"),
    Control(FrameworkId.ISO_27001, "A.8.27", "Secure architecture", "π-calculus + Linear + Separation Logic compile-time", EvidenceKind.COMPILE_TIME, "type_checker.*"),
    Control(FrameworkId.ISO_27001, "A.8.28", "Secure coding", "Compile-time type errors (Theorem 5.1)", EvidenceKind.COMPILE_TIME, "paper_lambda_lineal_epistemico.md"),
    Control(FrameworkId.ISO_27001, "A.8.29", "Security testing", "pytest 3680 tests", EvidenceKind.TEST_SUITE, "tests/"),
    Control(FrameworkId.ISO_27001, "A.8.30", "Outsourced development", "Dual-remote strategy + SBOM", EvidenceKind.AUTOMATED_ARTIFACT, "DEVELOPMENT.md + axon sbom"),
    Control(FrameworkId.ISO_27001, "A.8.31", "Dev/test/prod separation", "fabric.ephemeral", EvidenceKind.COMPILE_TIME, "FabricDefinition"),
    Control(FrameworkId.ISO_27001, "A.8.32", "Change management", "deterministic SBOM diff", EvidenceKind.AUTOMATED_ARTIFACT, "axon sbom"),
    Control(FrameworkId.ISO_27001, "A.8.33", "Test information", "DP-noise test data", EvidenceKind.RUNTIME_INVARIANT, "laplace_noise / gaussian_noise"),
]


# ═══════════════════════════════════════════════════════════════════
#  FIPS 140-3 — Cryptographic Module Validation
# ═══════════════════════════════════════════════════════════════════

_FIPS_140_3: list[Control] = [
    Control(FrameworkId.FIPS_140_3, "FIPS.ALG_APPROVED", "Only FIPS-approved algorithms used", "HMAC-SHA256 + SHA-256 + Ed25519 + ML-DSA-65", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.esk.provenance"),
    Control(FrameworkId.FIPS_140_3, "FIPS.BOUNDARY", "Cryptographic boundary defined", "ESK-CB: provenance.py + secret.py + attestation.py", EvidenceKind.MANUAL_POLICY, "docs/compliance/fips_140_3_submission_template.md"),
    Control(FrameworkId.FIPS_140_3, "FIPS.FSM", "Finite State Model", "POWER-OFF → INITIALIZED → OPERATIONAL", EvidenceKind.MANUAL_POLICY, "docs/compliance/fips_140_3_submission_template.md §6"),
    Control(FrameworkId.FIPS_140_3, "FIPS.KAT_HMAC", "HMAC-SHA256 Known Answer Test", "Test with fixed key/message → known tag", EvidenceKind.TEST_SUITE, "tests/test_phase6_runtime.py"),
    Control(FrameworkId.FIPS_140_3, "FIPS.KAT_SHA", "SHA-256 Known Answer Test", "SHA-256('abc') verification", EvidenceKind.TEST_SUITE, "tests/test_phase6_runtime.py"),
    Control(FrameworkId.FIPS_140_3, "FIPS.KAT_ED25519", "Ed25519 KAT (NIST CAVP vectors)", "Pending: Ed25519 KAT test", EvidenceKind.TEST_SUITE, "PENDING"),
    Control(FrameworkId.FIPS_140_3, "FIPS.PCT", "Pairwise consistency test Ed25519", "generate → sign → verify", EvidenceKind.TEST_SUITE, "tests/test_phase6_runtime.py"),
    Control(FrameworkId.FIPS_140_3, "FIPS.RNG", "Approved RNG source", "Python secrets.token_bytes (OS CSPRNG)", EvidenceKind.RUNTIME_INVARIANT, "HmacSigner.random"),
    Control(FrameworkId.FIPS_140_3, "FIPS.CT_COMPARE", "Constant-time comparisons", "hmac.compare_digest for MAC verify", EvidenceKind.RUNTIME_INVARIANT, "HmacSigner.verify"),
    Control(FrameworkId.FIPS_140_3, "FIPS.KEY_LIFECYCLE", "Key zeroization on dispose", "Garbage collection + no plaintext in repr", EvidenceKind.RUNTIME_INVARIANT, "Secret[T] invariant"),
    Control(FrameworkId.FIPS_140_3, "FIPS.DELIVERY", "Secure delivery procedures", "PyPI package + GitHub release signatures", EvidenceKind.EXTERNAL_OPERATIONAL, "pyproject.toml + release workflow"),
    Control(FrameworkId.FIPS_140_3, "FIPS.SELF_TEST", "Pre-operational self-test on load", "Pending: module-load KAT execution", EvidenceKind.TEST_SUITE, "PENDING"),
    Control(FrameworkId.FIPS_140_3, "FIPS.LAB_CAVP", "CAVP algorithm testing", "Business: engage NIST-accredited lab", EvidenceKind.EXTERNAL_OPERATIONAL, "PENDING (external)"),
    Control(FrameworkId.FIPS_140_3, "FIPS.CMVP", "CMVP module validation", "Business: submission to NIST", EvidenceKind.EXTERNAL_OPERATIONAL, "PENDING (external)"),
]


# ═══════════════════════════════════════════════════════════════════
#  Common Criteria EAL 4+ — subset of SFRs
# ═══════════════════════════════════════════════════════════════════

_CC_EAL4_PLUS: list[Control] = [
    # FAU — Security Audit
    Control(FrameworkId.CC_EAL4_PLUS, "FAU_GEN.1", "Audit data generation", "ReflexOutcome + ProvenanceChain", EvidenceKind.RUNTIME_INVARIANT, "ProvenanceChain.append"),
    Control(FrameworkId.CC_EAL4_PLUS, "FAU_GEN.2", "User identity association", "Secret.audit_trail accessor", EvidenceKind.RUNTIME_INVARIANT, "SecretAccess"),
    Control(FrameworkId.CC_EAL4_PLUS, "FAU_SAR.1", "Audit review", "axon dossier / sbom + chain.entries()", EvidenceKind.AUTOMATED_ARTIFACT, "CLI commands"),
    Control(FrameworkId.CC_EAL4_PLUS, "FAU_STG.1", "Protected audit storage", "Merkle append-only chain", EvidenceKind.RUNTIME_INVARIANT, "ProvenanceChain"),
    # FCO — Communication
    Control(FrameworkId.CC_EAL4_PLUS, "FCO_NRO.1", "Proof of origin", "Ed25519Signer / DilithiumSigner", EvidenceKind.RUNTIME_INVARIANT, "provenance.py"),
    # FCS — Cryptographic Support
    Control(FrameworkId.CC_EAL4_PLUS, "FCS_COP.1", "Cryptographic operation", "HMAC-SHA256 + Ed25519 + Dilithium3", EvidenceKind.RUNTIME_INVARIANT, "provenance.py"),
    Control(FrameworkId.CC_EAL4_PLUS, "FCS_CKM.1", "Key generation", "HmacSigner.random via secrets.token_bytes", EvidenceKind.RUNTIME_INVARIANT, "HmacSigner"),
    # FDP — User Data Protection
    Control(FrameworkId.CC_EAL4_PLUS, "FDP_ACC.1", "Access control (coverage rule)", "κ(shield) ⊇ κ(body)∪κ(output)", EvidenceKind.COMPILE_TIME, "_check_regulatory_compliance"),
    Control(FrameworkId.CC_EAL4_PLUS, "FDP_IFC.1", "Information flow control", "κ propagation through types", EvidenceKind.COMPILE_TIME, "TypeDefinition + type_checker"),
    Control(FrameworkId.CC_EAL4_PLUS, "FDP_IFF.1", "Security attributes", "compliance: [HIPAA,...] annotation", EvidenceKind.COMPILE_TIME, "TypeDefinition"),
    Control(FrameworkId.CC_EAL4_PLUS, "FDP_ITC.2", "Import with attributes", "manifest.compliance at ingest boundary", EvidenceKind.COMPILE_TIME, "ManifestDefinition"),
    # FIA — Identification & Authentication
    Control(FrameworkId.CC_EAL4_PLUS, "FIA_UAU.1", "Authentication timing", "Handler-level credential flow", EvidenceKind.RUNTIME_INVARIANT, "axon.runtime.handlers"),
    # FMT — Security Management
    Control(FrameworkId.CC_EAL4_PLUS, "FMT_MSA.1", "Security attribute management", "Only shield definitions set compliance", EvidenceKind.COMPILE_TIME, "ShieldDefinition.compliance"),
    Control(FrameworkId.CC_EAL4_PLUS, "FMT_SMR.1", "Security roles", "Crypto Officer + User + Reviewer (heal.mode)", EvidenceKind.RUNTIME_INVARIANT, "HealDefinition.mode"),
    # FPR — Privacy
    Control(FrameworkId.CC_EAL4_PLUS, "FPR_PSE.1", "Pseudonymity", "DP Laplace mechanism", EvidenceKind.RUNTIME_INVARIANT, "laplace_noise"),
    Control(FrameworkId.CC_EAL4_PLUS, "FPR_UNL.1", "Unlinkability", "DP Gaussian with composition", EvidenceKind.RUNTIME_INVARIANT, "gaussian_noise + PrivacyBudget"),
    # FPT — Protection of TSF
    Control(FrameworkId.CC_EAL4_PLUS, "FPT_TST.1", "TSF testing", "pytest 3680 tests", EvidenceKind.TEST_SUITE, "tests/"),
    Control(FrameworkId.CC_EAL4_PLUS, "FPT_ITC.1", "Inter-TSF confidentiality", "Secret[T] no-materialize", EvidenceKind.RUNTIME_INVARIANT, "Secret"),
    # FRU — Resource Utilisation
    Control(FrameworkId.CC_EAL4_PLUS, "FRU_RSA.1", "Maximum quotas", "resource.capacity + heal.max_patches", EvidenceKind.COMPILE_TIME, "ResourceDefinition + HealDefinition"),
    # FTP — Trusted Path/Channels
    Control(FrameworkId.CC_EAL4_PLUS, "FTP_ITC.1", "Inter-TSF trusted channel", "Operator's TLS stack (outside TOE)", EvidenceKind.EXTERNAL_OPERATIONAL, "PENDING (operator-provided)"),
    # SARs (augmentations for EAL 4+)
    Control(FrameworkId.CC_EAL4_PLUS, "ALC_FLR.2", "Flaw reporting procedures", "GitHub Issues SLA", EvidenceKind.EXTERNAL_OPERATIONAL, "SECURITY.md (organization-authored)"),
    Control(FrameworkId.CC_EAL4_PLUS, "AVA_VAN.5", "Advanced vulnerability analysis", "External pentest (accredited lab)", EvidenceKind.EXTERNAL_OPERATIONAL, "PENDING (external)"),
]


# ═══════════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════════

_ALL: dict[FrameworkId, list[Control]] = {
    FrameworkId.SOC2_TYPE_II:   _SOC2,
    FrameworkId.ISO_27001:      _ISO_27001,
    FrameworkId.FIPS_140_3:     _FIPS_140_3,
    FrameworkId.CC_EAL4_PLUS:   _CC_EAL4_PLUS,
}


def controls_for(framework: FrameworkId) -> list[Control]:
    """Return every control in the named framework."""
    return list(_ALL[framework])


def all_frameworks() -> list[FrameworkId]:
    return list(_ALL.keys())


def control_count(framework: FrameworkId) -> int:
    return len(_ALL[framework])


__all__ = [
    "Control",
    "EvidenceKind",
    "FrameworkId",
    "all_frameworks",
    "control_count",
    "controls_for",
]
