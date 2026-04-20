# Fase 8 — Rust parity gap inventory

**Generated:** 2026-04-20  
**Python baseline:** 193 modules (~71,276 LOC) with 3713 tests passing  
**Rust crate:** 94 modules (~62,233 LOC) predating Phase 1 primitives  

---

## Summary

| Metric | Count | Status |
|--------|-------|--------|
| Total Python modules in scope | 193 | Complete |
| Rust modules with equivalents | 35 | Partial (compiler mostly done) |
| Rust modules stale (pre-Phase-1) | 20 | Need extension |
| Missing Rust modules | 140+ | Not started |
| **Estimated gap** | **72%** | **Significant work ahead** |

---

## Key findings

### Compiler pipeline: 80% done (Tier 1–2)
- **Lexer:** OK for Tier 1–2 keywords. Missing Fase 3+ (resource, fabric, manifest, observe, reconcile, lease, ensemble, topology, session, immune, reflex, heal).
- **Parser & AST:** Fully typed for Persona, Context, Flow, Tool, Type, Intent, Run. Tier 2+ (Agent, Shield, Pix, etc.) use GenericDeclaration (structural only).  
  **Missing:** ResourceDef, FabricDef, ManifestDef, ObserveDef, ReconcileDef, LeaseDef, EnsembleDef, TopologyDef, SessionDef, ImmuneDef, ReflexDef, HealDef.
- **Type checker:** Epistemic lattice present. Missing Phase 3+ type rules (lease, topology, immune semantics).
- **IR:** Generates JSON for Tier 1–2. Missing IRResource, IRFabric, IRManifest, IRObserve, IRReconcile, IRLease, IREnsemble, IRTopology, IRSession, IRImmune, IRReflex, IRHeal.
- **Frontend:** Entry point only. Missing frontend_bootstrap, module_resolver, semantic_validator, compilation_cache.

**Action:** Extend lexer (4h), parser+AST (16h), IR (12h), add frontend_bootstrap (12h) and module_resolver (8h). Total: 52h.

### Runtime primitives: 0% done (CRITICAL GAP)
- **Executor:** Missing (380 LOC). Main execution loop driving resource/manifest/observe lifecycle. **Blocks everything.**
- **Handler base framework:** Missing (330 LOC). Free Monad + CPS. **CRITICAL BLOCKER for all 8 handlers.**
- **Lease kernel, reconcile_loop, ensemble_aggregator, file_resource:** All missing. ~700 LOC total.
- **Immune system (detector, heal, reflex, health_report):** All missing. ~620 LOC.
- **Session state:** session_store.rs basic; missing versioning, snapshots, durability.
- **Event bus:** Basic pub/sub; missing resource lifecycle hooks.

**Action:** Handler base (20h) → executor (16h) → lease/reconcile/ensemble/file (32h) → immune (30h). Total: 98h.

### ESK (Epistemic Security Kernel): 0% done (1,400 LOC)
- **Provenance:** Missing (400 LOC). Multi-sig verifier (HMAC-SHA256, Ed25519, Dilithium, Hybrid). Requires ring, ed25519-dalek, liboqs-sys. **Critical—blocks audit.**
- **Privacy:** Missing (220 LOC). Differential privacy (Laplace/Gaussian DP). Requires ndarray.
- **Attestation:** Missing (280 LOC). SBOM + in-toto SLSA v1.
- **Secret, compliance, eid, homomorphic, providers:** All missing (1,400 LOC total).
- **Audit engine (5 modules):** All missing (600 LOC). Frameworks, gap_analyzer, risk_register, control_statements, evidence_packager.

**Action:** Provenance (24h) → privacy (12h) → attestation (12h) → rest of ESK (32h) → audit_engine (20h). Total: 100h.

### Handlers: 0% done (8 implementations, 2,500 LOC)
All blocked on handler base framework.
- Dry-run (4h), terraform (16h), kubernetes (12h), aws (10h), docker (10h), mq (10h), grpc (8h), file (4h).

**Total: 84h (after handler base complete).**

### CLI: 50% done
- **OK:** check, compile, run, trace, version, repl, inspect, serve (partial).
- **Missing:** dossier, sbom, audit, evidence-package (all depend on ESK).

**Action:** CLI integration (20h) after ESK+audit_engine.

### Enterprise facade: Not in scope (optional for Phase 8).

---

## Porting plan (5 weeks, ~400 hours)

### Week 1: Compiler foundation (68h)
- Extend lexer (4h)
- Extend parser & AST (16h)  
- Extend IR & ir_generator (12h)
- Frontend bootstrap (12h)
- Module resolver (8h)
- Type checker Phase 3+ semantics (16h)

### Week 2: Runtime core (44h)
- Handler base framework **[CRITICAL]** (20h)
- Executor **[CRITICAL]** (16h)
- Context manager (8h)

### Week 3: Runtime primitives (36h)
- Lease kernel (8h)
- Reconcile loop (10h)
- Ensemble aggregator (8h)
- File resource (6h)
- Event bus upgrade (4h)

### Week 4: Handlers (84h)
- Dry-run (4h)
- Terraform (16h)
- Kubernetes (12h)
- AWS (10h)
- Docker (10h)
- MQ (Kafka + RabbitMQ) (10h)
- gRPC (8h)
- File (4h)

### Week 5: ESK, Immune, CLI integration (168h)
- Provenance (24h)
- Privacy (12h)
- Secret (4h)
- Attestation (12h)
- Compliance (8h)
- EID (8h)
- Providers (Vault, KMS, KeyVault) (16h)
- Immune system (detector, heal, reflex, health_report) (30h)
- Audit engine (5 modules) (20h)
- CLI integration (dossier, sbom, audit, evidence-package) (20h)
- State persistence + perf tuning (8h)
- Test suite (≥2000 tests) (16h)

---

## Cargo.toml additions needed

**Cryptography:** ed25519-dalek, ring, liboqs-sys, zeroize  
**Handlers:** kube, bollard, rdkafka (or rskafka), lapin, tonic  
**Secrets:** hashicorp-vault, azure_identity, azure_security_keyvault  
**DP:** ndarray  
**SBOM:** cyclonedx (or hand-roll JSON)  
**Optional:** dashmap, anyhow, eyre

---

## Top 5 biggest gaps

1. **Handler base framework** (330 LOC + 2400 LOC implementations) — blocks all handler ports.
2. **Runtime executor** (380 LOC) — main execution loop; week 2 critical path.
3. **ESK suite** (1,400 LOC: provenance, privacy, attestation, audit_engine) — crypto complexity, longest phase.
4. **Compiler Phase 3+ support** (400 LOC: new keywords, AST, parser, IR) — week 1 foundation.
5. **Immune system** (620 LOC: detector, heal, reflex, health_report) — week 5 integration.

---

## What's already usable

- ✓ Lexer/parser/AST for Tier 1–2 (extend 12 keywords)
- ✓ IR generation for Tier 1–2 (add node types)
- ✓ Epistemic lattice + type checker (add Phase 3+ rules)
- ✓ HTTP server (axum) + async (tokio)
- ✓ Database (sqlx + PostgreSQL)
- ✓ Trace infrastructure (integrate with executor)
- ✓ CLI scaffolding (route to handlers)
- ✓ AWS SDK crates (integrate into AWS handler)

---

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Homomorphic encryption (CKKS) unavailable in Rust | HIGH | Use fhe.rs, concrete, or tfhe-rs; stub for Phase 8 |
| Handler Free Monad + CPS complexity | MEDIUM | Simplify: use async/Result instead of full monadic; refine later |
| Cryptographic correctness (Ed25519, Dilithium) | MEDIUM | Use RustCrypto + ring; security audit before Phase 6 ESK |
| Terraform/K8s subprocess invocation | MEDIUM | Use subprocess first; refine to library APIs in Phase 9 |
| Test coverage lag | HIGH | Target 1,500+ tests (40% of Python) by end of Phase 8 |

---

## Success criteria (Phase 8 exit) — aligned with plan

The plan's cierre requires **byte-identical parity**, not coverage percentage:

1. ✓ `cargo test --all-features` verde en `axon-rs/tests/`
2. ✓ **Parity gate verde:** Python y Rust producen output byte-idéntico en:
   - IR JSON (para cada `.axon` en `examples/`)
   - ComplianceDossier JSON (canonical, sorted keys)
   - SupplyChainSBOM JSON (canonical, sorted keys)
   - in-toto Statement JSON (SLSA Provenance v1)
   - EvidencePackage ZIP (determinístico: MANIFEST.json SHA-256s coinciden)
3. ✓ CLI parity: `axon check | compile | run | trace | dossier | sbom | audit | evidence-package` producen exit code + stdout + stderr + artefactos idénticos al Python de referencia
4. ✓ Usuario puede ejecutar todos los comandos anteriores **sin Python instalado** (binario estático standalone)
5. ✓ Handlers funcionales contra el mismo harness de integración opt-in (`AXON_IT_*` env vars) que la versión Python
6. ✓ Documentación: `axon-rs/ARCHITECTURE.md` + guía de migración para adopters

**No es criterio de cierre:** porcentaje de tests. El parity gate cubre la semántica; tests adicionales en Rust son bonus, no requisito.

---

**End of Fase 8 gap inventory.**

