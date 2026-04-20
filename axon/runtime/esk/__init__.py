"""
AXON Runtime — Epistemic Security Kernel (ESK)
================================================
Public API for the Fase 6 security moat.

Modules
-------
  • `compliance` — κ regulatory class registry + coverage predicates
  • `provenance` — HMAC/Ed25519 signed envelopes + Merkle audit chain
  • `privacy`    — ε-budget differential privacy (Laplace / Gaussian)
  • `attestation` — SBOM + compliance dossier generation from IRProgram
  • `secret`     — Secret[T] with no-materialize invariant
  • `eid`        — Epistemic Intrusion Detector over immune HealthReports

See docs/plan_io_cognitivo.md Fase 6 for the strategic motivation.
"""

from __future__ import annotations

from .attestation import (
    ComplianceDossier,
    InTotoStatement,
    SbomEntry,
    SupplyChainSBOM,
    generate_dossier,
    generate_in_toto_statement,
    generate_sbom,
)
from .compliance import (
    REGISTRY as COMPLIANCE_REGISTRY,
    RegulatoryClass,
    classify_sector,
    covers,
    get as get_regulatory_class,
    is_known as is_known_regulatory_class,
)
from .eid import (
    EpistemicIntrusionDetector,
    IntrusionEvent,
    ShieldVerdictFn,
    always_approve,
    always_defer,
)
from .privacy import (
    BudgetExhaustedError,
    DifferentialPrivacyPolicy,
    PrivacyBudget,
    gaussian_noise,
    laplace_noise,
)
from .provenance import (
    DilithiumSigner,
    Ed25519Signer,
    GENESIS_HASH,
    HmacSigner,
    HybridSigner,
    ProvenanceChain,
    SignedEntry,
    SignedEnvelope,
    Signer,
    canonical_bytes,
    content_hash,
    sign_envelope,
    verify_envelope,
)
from .homomorphic import (
    CkksParameters,
    EncryptedValue,
    HomomorphicContext,
    encrypt_secret,
)
from .providers import (
    AwsKmsProvider,
    AzureKeyVaultProvider,
    SecretProvider,
    VaultProvider,
    secret_from_provider,
)
from .audit_engine import (
    Control,
    ControlImplementationStatement,
    EvidencePackage,
    FrameworkId,
    GapAnalysis,
    Risk,
    analyze_all,
    analyze_gaps,
    build_evidence_package,
    control_count,
    controls_for,
    generate_control_statements,
    generate_risk_register,
    risk_register_to_dict,
    statements_to_dict,
)
from .secret import Secret, SecretAccess


__all__ = [
    # compliance
    "COMPLIANCE_REGISTRY",
    "RegulatoryClass",
    "classify_sector",
    "covers",
    "get_regulatory_class",
    "is_known_regulatory_class",
    # provenance
    "DilithiumSigner",
    "Ed25519Signer",
    "GENESIS_HASH",
    "HmacSigner",
    "HybridSigner",
    "ProvenanceChain",
    "SignedEntry",
    "SignedEnvelope",
    "Signer",
    "canonical_bytes",
    "content_hash",
    "sign_envelope",
    "verify_envelope",
    # privacy
    "BudgetExhaustedError",
    "DifferentialPrivacyPolicy",
    "PrivacyBudget",
    "gaussian_noise",
    "laplace_noise",
    # attestation
    "ComplianceDossier",
    "InTotoStatement",
    "SbomEntry",
    "SupplyChainSBOM",
    "generate_dossier",
    "generate_in_toto_statement",
    "generate_sbom",
    # homomorphic (6.4)
    "CkksParameters",
    "EncryptedValue",
    "HomomorphicContext",
    "encrypt_secret",
    # providers (6.4.c)
    "AwsKmsProvider",
    "AzureKeyVaultProvider",
    "SecretProvider",
    "VaultProvider",
    "secret_from_provider",
    # secret
    "Secret",
    "SecretAccess",
    # eid
    "EpistemicIntrusionDetector",
    "IntrusionEvent",
    "ShieldVerdictFn",
    "always_approve",
    "always_defer",
    # audit engine (external audit preparation)
    "Control",
    "ControlImplementationStatement",
    "EvidencePackage",
    "FrameworkId",
    "GapAnalysis",
    "Risk",
    "analyze_all",
    "analyze_gaps",
    "build_evidence_package",
    "control_count",
    "controls_for",
    "generate_control_statements",
    "generate_risk_register",
    "risk_register_to_dict",
    "statements_to_dict",
]
