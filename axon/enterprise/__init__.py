"""
AXON Enterprise — Unified SDK Facade
=======================================
Public API for building production-grade AI applications on Axon.

This package is the Axon-native integration layer that wires together:
  • Fase 2 — Handlers (DryRun, Terraform, Kubernetes, AWS, Docker)
  • Fase 3 — Reconcile + Lease + Ensemble control primitives
  • Fase 4 — Topology + Session types
  • Fase 5 — Cognitive Immune System (immune, reflex, heal)
  • Fase 6 — Epistemic Security Kernel (ESK)

The facade is intentionally thin: it does not hide Axon's primitives;
it just saves adopters from hand-wiring seven runtime modules to build
a compliant enterprise service.  Adopters can always drop to the
underlying primitives when they need fine-grained control.

Usage
-----
    from axon.enterprise import EnterpriseApplication

    app = EnterpriseApplication.from_file("program.axon")
    report = app.provision()            # uses DryRunHandler by default
    report = app.provision(handler="terraform")
    dossier = app.dossier()             # JSON-serializable compliance dossier
    sbom    = app.sbom()                # JSON-serializable SBOM
"""

from __future__ import annotations

from .application import (
    EnterpriseApplication,
    EnterpriseStartupReport,
    HandlerName,
)


__all__ = [
    "EnterpriseApplication",
    "EnterpriseStartupReport",
    "HandlerName",
]
