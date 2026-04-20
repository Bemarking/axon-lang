"""
Always-on smoke harness for EnterpriseApplication.

Unlike the other suites in this folder, this one has NO env-var gate —
it exercises the Dry-Run handler end-to-end against every reference
program in examples/ and verifies each compiles + provisions + emits
dossier + SBOM without any external dependency.

If this harness ever fails, something regressed in the shipped reference
programs or in the facade itself.  It runs on every `pytest` invocation
because it is hermetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axon.enterprise import EnterpriseApplication


REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"


@pytest.mark.parametrize("reference", [
    "banking_reference.axon",
    "government_reference.axon",
    "healthcare_reference.axon",
    "io_cognitivo_primitives.axon",
])
def test_reference_end_to_end_dry_run(reference):
    """Every reference program completes the full lifecycle under DryRun."""
    path = EXAMPLES / reference
    assert path.exists(), f"missing reference: {path}"
    app = EnterpriseApplication.from_file(path, strict=True)
    # Provision cycle.
    report = app.provision(handler="dry_run")
    assert report.handler == "dry_run"
    assert report.type_errors == 0
    # Audit artifacts emit cleanly.
    dossier = app.dossier()
    sbom = app.sbom()
    assert sbom.program_hash == dossier.program_hash
    # Every regulated endpoint is shielded — no silent leak.
    assert dossier.unshielded_regulated == []
