"""
AXON Audit Evidence Engine — EvidencePackager
================================================
Bundles every artifact an external auditor typically requests into a
single ZIP file, ready for hand-off.  The package is deterministic
(byte-identical on equal inputs) and carries a manifest that enumerates
every file with its SHA-256 digest — so the auditor can verify nothing
was altered during transport.

Typical contents
----------------
    MANIFEST.json            — package index with per-file SHA-256
    README.md                — intake note for the auditor
    program_sbom.json        — SupplyChainSBOM
    program_dossier.json     — ComplianceDossier
    in_toto_statement.json   — SLSA Provenance v1 attestation
    provenance_chain.json    — Merkle-linked runtime events (if any)
    risk_register.json       — ISO 27005-shaped risk register
    gap_analysis/            — one file per framework
        soc2_type_ii.json
        iso_27001.json
        fips_140_3.json
        cc_eal4_plus.json
    control_statements/      — one file per framework
        soc2_type_ii.json
        iso_27001.json
        ...
    source/                  — snapshot of the `.axon` source files
        *.axon
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from axon.compiler.ir_nodes import IRProgram

from ..attestation import (
    generate_dossier,
    generate_in_toto_statement,
    generate_sbom,
)
from ..provenance import ProvenanceChain
from .control_statements import generate_control_statements, statements_to_dict
from .frameworks import FrameworkId
from .gap_analyzer import analyze_all
from .risk_register import generate_risk_register, risk_register_to_dict


@dataclass
class EvidencePackage:
    """In-memory representation of a packaged audit bundle."""
    program_hash: str
    files: dict[str, bytes] = field(default_factory=dict)

    def sha256_of(self, filename: str) -> str:
        return hashlib.sha256(self.files[filename]).hexdigest()

    def filenames(self) -> list[str]:
        return sorted(self.files.keys())

    def to_zip_bytes(self) -> bytes:
        """Serialize to a single ZIP byte blob with deterministic ordering."""
        buf = io.BytesIO()
        # ZIP_DEFLATED with fixed modification date for reproducibility.
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(self.files.keys()):
                info = zipfile.ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, self.files[name])
        return buf.getvalue()

    def write_zip(self, path: str | Path) -> Path:
        out = Path(path)
        out.write_bytes(self.to_zip_bytes())
        return out


def _j(payload: Any) -> bytes:
    """Canonical JSON encoding (sorted keys, 2-space indent)."""
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def build_evidence_package(
    program: IRProgram,
    *,
    axon_version: str | None = None,
    provenance_chain: ProvenanceChain | None = None,
    provenance_payloads: Iterable[dict[str, Any]] | None = None,
    source_files: dict[str, str] | None = None,
    auditor_note: str = "",
) -> EvidencePackage:
    """Assemble the audit-ready evidence package for `program`.

    Parameters
    ----------
    program : IRProgram
        The compiled Axon program under audit.
    axon_version : str
        Version string recorded in every artifact.
    provenance_chain : ProvenanceChain, optional
        If supplied, the chain's entries are emitted as
        `provenance_chain.json`.  `provenance_payloads` must accompany
        the chain so the bundle is self-verifiable.
    provenance_payloads : iterable of dict, optional
        The raw payloads corresponding to the chain entries.
    source_files : {filename: source_text}, optional
        Axon source snapshots to include under `source/`.
    auditor_note : str
        Free-form preface text embedded in the README.
    """
    if axon_version is None:
        from axon.runtime.esk.attestation import _axon_version
        axon_version = _axon_version()
    sbom = generate_sbom(program, axon_version=axon_version)
    dossier = generate_dossier(program, axon_version=axon_version)
    in_toto = generate_in_toto_statement(program, axon_version=axon_version)
    risks = generate_risk_register(program)
    gap = analyze_all(program)

    pkg = EvidencePackage(program_hash=sbom.program_hash)

    pkg.files["program_sbom.json"] = _j(sbom.to_dict())
    pkg.files["program_dossier.json"] = _j(dossier.to_dict())
    pkg.files["in_toto_statement.json"] = _j(in_toto.to_dict())
    pkg.files["risk_register.json"] = _j(risk_register_to_dict(risks))

    # Gap analysis per framework.
    for framework, analysis in gap.items():
        pkg.files[f"gap_analysis/{framework}.json"] = _j(analysis.to_dict())

    # Control statements per framework.
    for f in FrameworkId:
        statements = generate_control_statements(program, f)
        pkg.files[f"control_statements/{f.value}.json"] = _j(
            statements_to_dict(statements, f)
        )

    # Provenance chain + payloads.
    if provenance_chain is not None:
        entries = [e.to_dict() for e in provenance_chain.entries()]
        chain_blob: dict[str, Any] = {
            "schema":  "axon.esk.provenance_chain.v1",
            "genesis": "0" * 64,
            "count":   len(entries),
            "entries": entries,
        }
        if provenance_payloads is not None:
            chain_blob["payloads"] = list(provenance_payloads)
        pkg.files["provenance_chain.json"] = _j(chain_blob)

    # Source snapshot.
    if source_files:
        for fname, source_text in source_files.items():
            safe_name = fname.replace("\\", "/").lstrip("/")
            pkg.files[f"source/{safe_name}"] = source_text.encode("utf-8")

    # README — last, so it can reference the SHA-256s of the rest.
    pkg.files["README.md"] = _build_readme(pkg, sbom.program_hash, auditor_note).encode("utf-8")

    # MANIFEST — absolutely last, after every other file.
    manifest = {
        "schema":         "axon.esk.evidence_manifest.v1",
        "axon_version":   axon_version,
        "program_hash":   sbom.program_hash,
        "file_count":     len(pkg.files),
        "files": [
            {"name": name, "sha256": pkg.sha256_of(name), "size": len(pkg.files[name])}
            for name in sorted(pkg.files.keys())
        ],
    }
    pkg.files["MANIFEST.json"] = _j(manifest)

    return pkg


def _build_readme(pkg: EvidencePackage, program_hash: str, auditor_note: str) -> str:
    lines = [
        "# AXON Audit Evidence Package",
        "",
        f"**Program hash:** `{program_hash}`",
        "",
        "## What is in this package",
        "",
        "This ZIP bundles the deterministic audit artifacts produced by the",
        "Axon compiler + ESK runtime.  Every JSON file is canonical-encoded",
        "and carries its own SHA-256 in `MANIFEST.json`.",
        "",
        "| File | Purpose |",
        "|---|---|",
        "| `program_sbom.json`              | Software Bill of Materials (deterministic) |",
        "| `program_dossier.json`           | Regulatory compliance dossier |",
        "| `in_toto_statement.json`         | SLSA Provenance v1 attestation |",
        "| `risk_register.json`             | ISO 27005-shaped risk register |",
        "| `gap_analysis/*.json`            | Per-framework gap analysis |",
        "| `control_statements/*.json`      | Pre-populated implementation statements |",
        "| `provenance_chain.json`          | Runtime Merkle chain (if provided) |",
        "| `source/*.axon`                  | Source snapshot at package time |",
        "",
        "## Verifying the package",
        "",
        "Every entry in `MANIFEST.json` carries a SHA-256 hash of the file",
        "contents.  An auditor re-running `sha256sum` on each file MUST see",
        "the same digest — the package is deterministic.  The program_hash",
        "inside `MANIFEST.json` equals the `program_hash` inside",
        "`program_sbom.json` — any divergence signals tampering.",
        "",
        "## Frameworks covered",
        "",
        "- SOC 2 Type II (AICPA Trust Services Criteria)",
        "- ISO/IEC 27001:2022 (Annex A subset)",
        "- FIPS 140-3 (scaffold + readiness)",
        "- Common Criteria EAL 4+ (SFR / SAR readiness)",
        "",
    ]
    if auditor_note:
        lines.extend(["## Auditor note", "", auditor_note, ""])
    return "\n".join(lines)


__all__ = [
    "EvidencePackage",
    "build_evidence_package",
]
