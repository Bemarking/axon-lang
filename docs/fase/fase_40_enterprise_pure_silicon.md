---
title: "Plan vivo: Fase 40 — Enterprise Pure Silicon (the real v2.0.0 catch-up: axon-enterprise → 100% Rust/C)"
status: 🛠️ IN PROGRESS — 40.a–40.k + 40.m SHIPPED; 40.l CORE SHIPPED (login engine + axum router verified offline; sqlx/KMS/samael pending live-Postgres CI). §14 SCOPE RECKONING RATIFIED (founder 2026-05-22): port ALL 12 SaaS domains — tail re-planned 40.n–40.w, finale 40.x–40.ab. **40.n + 40.o + 40.p + 40.q + 40.r SHIPPED** (complete spine schema + sqlx UserStore/SessionStore; metering billing core; tamper-evident SHA-256 audit log; GDPR/CCPA/SOC2 compliance ops engine; Fase 29 vertical diagnostic stack). Remaining: 40.s api_keys+invitations, 40.t cognitive_states+replay, 40.u config+observability, 40.v cli, 40.w http. 40.a (Rust workspace foundation). 40.b (OSS shield-scanner hook → axon-lang v2.1.0). 40.c (HIPAA/legal/AML vertical cognition — checksum-validated, leak-safe). 40.d (supervisor hardening — backoff/policies/budgets/health/Merkle-audit/hierarchy wrapping the OSS DaemonSupervisor). D1 ratified founder 2026-05-21.
owner: AXON Compiler + Runtime + Enterprise Team
created: 2026-05-21
target: |
  axon-enterprise **v2.0.0** — MAJOR (full Python eradication; Rust/C workspace
  consuming axon-lang 2.0.x via versioned Cargo dependency; single
  `axon-enterprise-server` axum binary; vertical cognition in Rust)
  axon-lang **v2.0.2 (or v2.1.0)** — small OSS extension-point patch (shield
  scanner registration hook) that enterprise needs; makes axon better as a
  language (axon-for-axon)
depends_on: |
  Fase 39 SHIPPED (Pure Silicon Cognition — axon-lang v2.0.0/v2.0.1; FlowEnvelope⟨T⟩;
  zero language Python; axon-frontend 1.0.0 + axon-csys 0.2.0 + axon-lang 2.0.1
  published to crates.io — THESE are the crates enterprise now depends on)
  Fase 27 SHIPPED (axon-csys-enterprise BSL Rust crate — FIPS crypto + audit-log
  mmap + PHI-scrub C23 kernels — the existing Rust/C foothold Fase 40 expands)
charter_class: |
  ARCHITECTURAL COMPLETION — Fase 40 is NOT a new feature cycle. It is the
  honest completion of the v2.0.0 RELEASE CYCLE that Fase 39 left open. By the
  founder's own catch-up-always directive, the v2.0.0 change has not reached any
  Rust adopter until the enterprise Docker image runs on v2.0.0. The pin-cap
  `axon-lang<2.0.0` (PR #48) is a tourniquet, not a cure. Fase 40 removes the
  tourniquet by making enterprise a 100% Rust/C product.
pillars: |
  - **MATHEMATICS** — enterprise inherits FlowEnvelope⟨T⟩ + Theorem 5.1 by Cargo
    dependency; the ψ-vector wire contract is identical across OSS and BSL.
  - **LOGIC** — single-stack. No hybrid. No FFI. No dual-runtime parity tax. The
    same code runs in OSS and enterprise because it IS the same crate, version-pinned.
  - **PHILOSOPHY** — "silicon cognition" extends to the business layer: the
    commercial product is metal-bound too. Enterprise is the heart (the business);
    axon-lang is the contribution (the community footprint). Cargo lets both
    coexist — enterprise can even consume a privatized axon-lang unchanged.
  - **COMPUTING** — one axum process, one binary, one image. The enterprise server
    and axon-server converge into a single compiled artifact.
---

# ▶ 1. The honest reframe

Fase 39 shipped the **language**: axon-lang v2.0.0/v2.0.1 is live cross-stack,
zero language Python, FlowEnvelope⟨T⟩ canonical, the adopter T9XX↔D5 gap closed
via axon-E039. **That part is genuinely complete.**

But the **v2.0.0 release cycle is NOT complete.** By the founder's catch-up-always
directive ([[feedback_enterprise_catch_up_always]]), a release reaches Rust
adopters only via the enterprise Docker image — and that image is pinned to the
v1.x line because the Python `axon_enterprise` package imports `axon.runtime.*`
modules the purge deleted. Calling Fase 39 "CLOSED" with this open was a eufemism.

**Fase 40 completes the cycle.** When it lands, enterprise runs on v2.0.0 as a
100% Rust/C product and the pin-cap is lifted. Only then is v2.0.0 truly shipped.

# ▶ 2. The coupling diagnosis (measured 2026-05-21)

Of **30,076 LOC** Python in `axon_enterprise`:

| Layer | LOC | Couples to purged `axon.*`? |
|-------|-----|------------------------------|
| Shield vertical (HIPAA / legal / AML R&D) | ~1,501 | ✗ YES → `axon.runtime.shield_scanners`, `shield.dual_llm_scanner`, `ensemble_scanner` |
| Supervisor (hierarchy / factory) | ~1,932 | ✗ YES → `axon.runtime.supervisor.DaemonSupervisor` |
| `http/api/primitives.py` catalogs | lazy imports | ✗ YES (function-local; don't break at import) |
| SaaS control plane (tenant, db, identity, rbac, sso, jwt_issuer, secrets, crypto, studio, config, most of http) | ~26,600 | ✓ ZERO axon.* coupling |

**Only ~3,400 LOC actually break.** The other 88% is a Python SaaS multitenant
backend with no language coupling at all. The founder's decision is to Rust-ify
ALL of it anyway (no hybrid) — see D1.

**Existing Rust/C foothold:** `axon-csys-enterprise/` already ships 28 Rust files
+ C23 kernels (FIPS crypto glue, audit-log mmap, PHI-scrub) from Fase 27. Fase 40
expands this crate into the full enterprise workspace — not a greenfield start.

**Root cause uncovered:** enterprise has been running on the **Python runtime as
Docker ENTRYPOINT** all along; the Rust `axon-server` binary shipped in the image
but was never the entrypoint (Dockerfile.enterprise lines 110-117 anticipate the
cutover). The vertical scanners were Python overrides of the Python shield
framework. v2.0.0 purged that runtime → broke the actual execution path.

# ▶ 3. Architecture — Cargo dependency, NOT a fork

The founder's instinct ("enterprise interprets its own language, same code") is
correct. The mechanism is a **versioned Cargo dependency**, not a filesystem copy:

```toml
# axon-enterprise/Cargo.toml (workspace)
[dependencies]
axon-frontend = "1.0.0"   # same lexer/parser/type-checker as OSS
axon-csys     = "0.2.0"   # same C23 kernels (envelope / Theorem 5.1 / BPE / ...)
axon-lang     = "2.0.1"   # same runtime (axon-rs)
```

A copy gives identical code **once**; a Cargo dependency gives identical code
**on every fix, forever** — and eliminates the parity tax Fase 39 just killed
(a fork would re-introduce it as Rust↔Rust drift). Privatization-safe: the day
axon-lang moves to a private registry / git / vendored source, only the Cargo
`source` changes — the architecture is unaffected.

**Workspace shape:**

```
axon-enterprise/  (Rust workspace, BSL)
├── Cargo.toml                → deps: axon-frontend, axon-csys, axon-lang
├── axon-csys-enterprise/     → EXISTING C23 kernels (FIPS / audit / PHI) — Fase 27
├── crates/vertical/          → shield HIPAA/legal/AML in Rust (port of ~1.5K LOC)
├── crates/supervisor/        → enterprise supervision on axon-rs DaemonSupervisor
├── crates/saas/              → multitenancy: db / identity / rbac / sso / jwt / secrets
└── crates/server/            → `axon-enterprise-server` = axon-server (axum)
                                 + SaaS routes + vertical layer, ONE binary
```

**HTTP converges on axum.** axon-rs already uses axum; the SaaS HTTP layer
(currently starlette) re-homes onto the same axum app → one server, one process,
one image. ENTRYPOINT flips to `axon-enterprise-server`.

# ▶ 4. Decisiones

| # | Decisión | Estado |
|---|----------|--------|
| **D1** | Enterprise = **100% Rust/C, no Python, no hybrid.** Consumes axon-lang via versioned Cargo dependency (NOT a fork). All SaaS + vertical logic rewritten to Rust/C. Hybrid is technical debt that would force a regression right after Fase 39 freed us. | **ratified founder 2026-05-21** |
| **D2** | Construct-before-purge (mirror 39.D7): build + verify each Rust layer BEFORE deleting its Python counterpart. Purga only runs when the Rust path is proven. | propuesta |
| **D3** | Enterprise-only primitives are **two-tier**: (1) runtime primitives (scanners / backends / OTS / effect handlers) plug into axon-rs registries — immediate, clean, covers 100% of today's verticals; (2) novel-syntax primitives need a deliberate compiler extension-point in axon-frontend — deferred to a dedicated sub-fase when first needed. We do NOT pretend tier-2 is free. | propuesta |
| **D4** | HTTP converges on **axum** (axon-rs's stack). The enterprise server and axon-server become ONE compiled binary `axon-enterprise-server`. | propuesta |
| **D5** | Vertical cognition (shield HIPAA/legal/AML) ships as a **BSL, feature-gated** Rust crate consulted by axon-rs `apply_shield` via the D3-tier-1 registration hook. The OSS axon-server never ships vertical R&D. | propuesta |
| **D6** | **Privatization optionality preserved.** The architecture must not assume crates.io-public-forever; Cargo private-registry / git / vendor must all work. | propuesta |
| **D7** | **SAML risk flagged early.** Rust SAML (`samael`) is younger than `pysaml2`; evaluate in the SSO sub-fase and harden/vendor if the gap is material. The one domain where the Rust ecosystem is thinner. | propuesta |
| **D8** | The pin-cap `axon-lang<2.0.0` (PR #48) **stays** until Fase 40 completes; lifted only at the real enterprise v2.0.0 release. The adopter stays on v1.x meanwhile (it "puede esperar sin problemas"). | propuesta |
| **D9** | Adopter cutover (`output: T` → `output: FlowEnvelope<T>`) sequenced at the very end, on the real v2.0.0 image. | propuesta |
| **D10** | `axon-csys-enterprise` (existing Fase 27 crate) is **expanded**, not replaced — it is the workspace's C23 foundation. | propuesta |

# ▶ 5. Sub-fases (construct-before-purge, topological)

| Sub-fase | Surface | Status |
|----------|---------|--------|
| **40.a** ✅ SHIPPED 2026-05-21 | Workspace foundation: promote `axon-csys-enterprise` into a workspace; add Cargo deps on axon-frontend 1.0.0 + axon-csys 0.2.0 + axon-lang 2.0.1; prove enterprise can lex/parse/type-check/run a vertical `.axon` program through the OSS language ("interprets its own language"). | ✅ Branch `feature/fase-40-enterprise-pure-silicon` (commit `9c6debd`). Root virtual `Cargo.toml` with `[workspace.dependencies]` pinning `=1.0.0`/`=0.2.0`/`=2.0.1` as the single source of truth (D1 versioned dependency, not a fork). `axon-csys-enterprise` axon-csys pin advanced `=0.1.1`→`=0.2.0` via the workspace so the tree resolves ONE axon-csys (the one axon-lang 2.0.1 depends on) — byte-identity drift gates stay green. New `crates/enterprise-lang` façade re-exports the OSS pipeline (`checker`/`compiler`/`runner` + `frontend` + `csys`) through one boundary; `AXON_LANG_VERSION` resolved at compile time. **Proof**: vertical HIPAA `.axon` fixture type-checks AND compiles to IR through the dependency (IR `_meta.axon_version=="2.0.1"`, flow present); `AXON_LANG_VERSION=="2.0.1"`. Workspace builds clean (axon-lang 2.0.1 pulled from crates.io, 9m29s first build); 5 enterprise-lang tests + all axon-csys-enterprise drift gates (31+32+13+47+34+…) green. Type-check + compile are the deterministic offline proof; runtime *execution* of a flow (reaches a backend) lands with the vertical scanner in 40.c. | 
| **40.b** ✅ SHIPPED 2026-05-22 | OSS shield extension-point in **axon-rs** (`pub` scanner-registration hook so the BSL vertical crate injects scanners into `apply_shield`). Ships as axon-lang v2.1.0. *Axon-for-axon: a clean language extension point.* | ✅ **axon-lang v2.1.0 LIVE cross-stack** (crates.io + GitHub Release v2.1.0 with 6 platform binaries + PyPI 2.1.0 wrapper verified end-to-end via clean `pip install` → `axon version`). New `axon::shield_registry` module: `ShieldScanner` trait + `ShieldVerdict {Pass(String) \| Reject {code, reason}}` + `ShieldScanContext` + process-global `RwLock` registry (`register`/`lookup`/`unregister`/`registered_shield_names`/`has_registered_scanners`/`clear`). `run_shield_apply` (dispatcher) consults it: `Pass` binds possibly-redacted content; `Reject` → `DispatchError::BackendError {name:"shield:<n>", message:"[<code>] <reason>"}` + binds NO output; unregistered name → OSS identity (backwards-compatible, wire shape unchanged). MINOR bump (new public API); axon-frontend 1.0.0 + axon-csys 0.2.0 unchanged, not re-published. +7 tests (4 registry + 3 dispatcher, parallel-safe via unique names); **2204 axon-rs lib green, zero regressions**. Commits `9409de5` (feat) + `7fc5d3e` (release). **Enterprise 40.c** bumps the workspace pin `axon-lang =2.0.1`→`=2.1.0` to consume this hook. | 
| **40.c** ✅ SHIPPED 2026-05-22 | Vertical cognition → Rust (the R&D crown jewels): port HIPAA / legal / AML scanner families (~1.5K LOC) + dual-LLM + ensemble onto the 40.b hook + OSS shield framework. BSL, feature-gated. | ✅ New BSL crate `crates/vertical` (`axon-enterprise-vertical`) registers HIPAA/legal/AML `ShieldScanner`s against the 40.b `axon::shield_registry` hook. **HIPAA**: 18-category Safe Harbor (SSN/MRN/phone/dates/ICD-10/NDC/controlled-substances/name+DOB composite/portal URLs); CPT contextual ported WITHOUT look-ahead (linear-time regex has none → 5-digit + context-keyword check). **Legal**: attorney-client privilege + work-product (Hickman) + settlement/FRE408; public case citations alone do NOT breach (false-positive reduction preserved). **Fintech**: Luhn-validated PAN + ISO-13616 mod-97 IBAN (iterative, no bignum) + SWIFT BIC + smurf (2+ $9k–$9.99k) + OFAC. **Better-than-market**: (1) checksum validation eliminates the false positives regex-only scanners produce; (2) every verdict MASKS the detected secret (PCI first6/last4 for PANs; label-only for free-text PHI/privilege) — closes the Python original's raw `match[:80]` PHI/PAN leak; (3) deterministic/total/never-panic/linear-time. Judge rubrics (HIPAA/legal/AML) preserved verbatim as constants for the async dual-LLM escalation. `register_hipaa/legal/aml/all()` wire scanners at boot under names `hipaa`/`legal`/`aml`. Workspace pin advanced `axon-lang =2.0.1`→`=2.1.0`; enterprise-lang version asserts updated. **25 vertical tests + full workspace green** (enterprise-lang 5 + axon-csys-enterprise drift gates), zero regressions. Commit `acd40cb`. **Honest scope**: deterministic pattern gate ships now; async LLM judge + 2-of-3 ensembles need an async-scanner hook extension (follow-on). | 
| **40.d** ✅ SHIPPED 2026-05-22 | Supervisor enterprise layer → Rust: port hierarchy / factory (~1.9K LOC) onto axon-rs `DaemonSupervisor`. | ✅ New BSL crate `crates/supervisor` (`axon-enterprise-supervisor`) WRAPS the OSS `axon::event_bus::DaemonSupervisor` (not a fork — composes around it). **backoff**: `DecorrelatedJitterBackoff` (AWS decorrelated-jitter, deterministic per-instance LCG, pure `compute_delay`, bounded `[base,cap]`). **policies**: full `on_stuck` vocabulary (restart/hibernate/escalate/retry/forge/noop) → OSS resolution + side-effects-as-data (sync/pure/testable — the Rust analog of the Python async callbacks). **isolation**: `TenantBudgetRegistry` (sliding-minute restart budget + concurrent-cascade guard + snapshot-size cap; per-tenant isolation; monotonic-ms clock for determinism). **health**: `HealthProbeRegistry` (heartbeat/watchdog/custom-predicate). **audit**: `SupervisorAuditChain` — per-tenant HMAC-SHA256 Merkle chain via the **FIPS-routable axon-csys-enterprise crypto** (dogfoods the validated path) + `verify_chain` (tamper-evident; tampering test proves detection). **hierarchy**: `SupervisionNode` OTP-style escalation tree (bottom-up, relative paths). `EnterpriseSupervisor::on_crash` orchestrates budget-gate → audit → policy → backoff → OSS `report_crash`/`stop` → structured `CrashOutcome`. **27 supervisor tests + full workspace green** (vertical 25 + enterprise-lang 5 + axon-csys-enterprise drift gates), zero regressions. Commit `b32e138`. **Honest scope**: deterministic core ships; infra adapters (Redis-Redlock leader election, OTel/Prometheus exporters, durable replay-token store, legal-basis compliance gate) wire with the SaaS infra (40.f–40.l) via the `AuditSink` trait + `on_crash` side-effect surface. | 
| **40.e** ✅ SHIPPED 2026-05-22 | Catalogs / discovery → Rust: `primitives.py` catalogs (legal_basis / ots / stream / trust / buffer) served from the axon-server discovery endpoint. | ✅ New `axon_enterprise_lang::primitives::primitive_catalogs()` rebuilds the pre-v2.0.0 Python `/primitives` payload, reading each catalogue from its **single canonical source** (never re-declaring → no drift): `trust_proofs`←`axon_frontend::refinement::TRUST_CATALOG`, `backpressure_policies`←`axon_frontend::stream_effect::BACKPRESSURE_CATALOG`, `legal_bases`←`axon_frontend::legal_basis::LEGAL_BASIS_CATALOG`, `ots_backends`←`axon_frontend::ots_catalog::OTS_BACKEND_CATALOG`, `buffer_kinds_seeded`←`axon::buffer::BufferKindRegistry::global()` (read-only; pre-seeded with standard kinds on first access — never interned/mutated here). **Founder caution on ots/stream honoured**: reads are pure + side-effect-free; tests PIN `ots_backends == ["native","ffmpeg"]` exactly + assert backpressure equals the canonical catalogue and matches `BackpressurePolicy::ALL.len()`, so any upstream change is caught at the enterprise boundary not in production. Closes the last lazy `axon.*` import in the enterprise discovery surface. +6 tests; full workspace green. HTTP wiring lands in 40.l. Commit `85e0f10`. | 
| **40.f** ✅ SHIPPED 2026-05-22 | SaaS — DB + migrations → Rust (`sqlx` + `refinery`/`sqlx migrate`); tenant + RLS policies. | ✅ New BSL crate `crates/saas-db` (`axon-enterprise-db`) **builds ON the OSS data plane** (reuse, not reinvention): re-exports `axon::tenant` (`current_tenant_id`/`TenantContext`/`TenantPlan` — one source of truth, shared with the OSS runtime) + uses the GUC `axon.current_tenant` identical to `axon::storage_postgres` (so policies work whether the session is opened by OSS or enterprise — discovered the OSS runtime already has the pool + tenant task-local + `SET LOCAL axon.current_tenant`). Enterprise-only: **rls.rs** — per-tenant RLS generators: `tenant_isolation` **FAIL-CLOSED** (`current_setting('axon.current_tenant',true) IS NOT NULL` → no tenant context sees ZERO rows) + `admin_bypass` (axon_admin BYPASSRLS) + `full_policy_set`; pure SQL generators, **fully unit-tested** (security-critical crown jewel). **pool.rs** — production-hardened pool adding per-connection safeguards the OSS pool lacks (statement_timeout / lock_timeout / idle_in_transaction_session_timeout as startup params), same `sqlx::PgPool` type, primary+replica-fallback. **config.rs** — `DbConfig` (env + defaults matching engine.py). **session.rs** — `SET_TENANT_GUC_SQL` (`"SET LOCAL axon.current_tenant = $1"`, bound value, no injection surface) + `apply_tenant_guc`. sqlx pinned to 0.8 (axon-lang's) so PgPool/Transaction types unify. **12 tests + full workspace green.** Commit `cd3c081`. **Honest scope**: per-domain schemas/migrations land with their domains (40.g+); live-DB pool/session integration tested in the Postgres CI lane at 40.l. | 
| **40.g** ✅ SHIPPED 2026-05-22 | SaaS — Identity → Rust (`argon2` / `totp-rs`; password policy / lockout / sessions). | ✅ New BSL crate `crates/saas-identity` (`axon-enterprise-identity`) — deterministic security core built to **exceed market implementations**. **password.rs**: Argon2id (OWASP 2024 t=3/m=64MiB/p=4) + constant-time verify (all failures → InvalidCredentials) + **anti-enumeration timing parity** (`burn_equivalent_time` spends equal CPU when the account is absent) + transparent `needs_rehash`. **policy.rs**: length + **zxcvbn entropy** (not regex rules — blocks `Summer2024!`-class + penalises user_inputs) + **HIBP k-anonymity** (SHA-1 prefix sent, suffix checked locally — full password never leaves the process); breach LOGIC pure + tested. **totp.rs**: RFC 6238 hand-rolled on HMAC-SHA1 + dynamic truncation, **VERIFIED against the RFC 6238 Appendix B test vectors**; **constant-time** code compare (subtle); **replay-aware** (returns matched time-step); base32 RFC 4648 verified; provisioning URI. **lockout.rs**: progressive soft/hard/permanent tiers. **errors.rs**: stable codes + `reveal_to_client` anti-enumeration flag. **25 tests incl. RFC 6238 + RFC 4648 vectors; full workspace green.** Commit `151d985`. **Honest scope**: deterministic primitives + HIBP logic ship; DB-backed session store + AuthService orchestration compose with 40.f DB at 40.l; TOTP secret encryption-at-rest composes with the envelope at 40.k. | 
| **40.h** ✅ SHIPPED 2026-05-22 | SaaS — RBAC → Rust (permissions / models / service / enforce / seed). | ✅ New BSL crate `crates/saas-rbac` (`axon-enterprise-rbac`), pure std-only. **catalog.rs**: 32-entry `SYSTEM_PERMISSIONS` (tenant/user/role/flow/secret/audit/metering/observability) + catalog-validated `parse_permission` + 4 built-in roles (owner=all enumerated, admin=all minus {tenant:delete, tenant:suspend, user:impersonate}, developer=flow-shaped+reads, viewer=read-only) + `effective_permissions` (role union). **enforce.rs**: `check`/`require` over a resolved permission set (a typo in `required` errors loudly via catalog validation — never a silent deny) + `require_for_roles`. **hierarchy.rs**: pure role-inheritance cycle detection (self/direct/transitive). **errors.rs**: `RbacError` + stable codes + `reveal_to_client`. **SECURITY ANTI-DRIFT**: tests pin the authorization model (owner=32; admin=29 lacking exactly the 3 sensitive ops; viewer=read-only; developer=flow-shaped) so an accidental privilege change fails CI. **16 tests + full workspace green.** Commit `8dfbfa1`. **Honest scope**: pure authorization core ships; DB-backed `RbacService` (resolve roles→perms, grant/revoke, per-tenant seed) composes on 40.f DB at 40.l. | 
| **40.i** ✅ SHIPPED 2026-05-22 | SaaS — JWT issuer + JWKS → Rust (`jsonwebtoken` / `josekit`; local + KMS signer; revocation; key management). | ✅ New BSL crate `crates/saas-jwt` (`axon-enterprise-jwt`) — **superior to the common HS256-shared-secret design** via asymmetric **EdDSA (Ed25519)** (deterministic sigs, no RNG-failure risk, 32B keys/64B sigs, fast). **signer.rs**: `Signer` trait (KMS/RS256 plug in identically) + `Ed25519Signer` + JWK/JWKS (OKP) + b64url. **issuer.rs**: mint with **RESERVED-CLAIM protection** — caller `extra` cannot forge `tenant_id`/`roles`/`iss` (stripped before signing); UUID-v4 jti. **verify.rs**: `verify_strict` (rejects malleable sigs) + **ALGORITHM-CONFUSION DEFENCE** (header `alg` must be EdDSA — blocks `alg:none`/key-confusion) + exp/nbf/iss/aud validation. **keyring.rs**: **zero-downtime rotation** (active signs, grace keys still verify; JWKS publishes active+grace sorted by kid). **revocation.rs**: jti denylist with TTL. **12 tests with REAL Ed25519 signatures** (mint/verify/tamper/expiry/audience/rotation+grace/forge-attempt); full workspace green. Commit `da53674`. **Honest scope**: deterministic core ships; DB-backed key store + KMS signer (impl the `Signer` trait) + JWKS/token endpoints compose at 40.k/40.l. | 
| **40.j** ✅ SHIPPED 2026-05-22 | SaaS — SSO → Rust (`openidconnect` for OIDC/PKCE/discovery/id-token; **SAML risk per D7**). | ✅ New BSL crate `crates/saas-sso` (`axon-enterprise-sso`). **pkce.rs**: RFC 7636 **S256 ONLY** (`plain` rejected — downgrade defence), verified against the RFC 7636 Appendix B vector. **state.rs**: CSRF state + replay nonce + PKCE pair generation; validation rejects replay (single-use) / expiry / mismatch. **id_token.rs**: OIDC ID-token claim validation (exact iss, aud-contains-client_id, exp, nonce) per OIDC Core §3.1.3.7. **discovery.rs**: discovery-doc parse. **mapper.rs**: OIDC/SAML claims → canonical identity + group→role resolution (no implicit creation, dedup preserving order). **saml.rs**: **type-state safety boundary** (founder D7 hardening, commit `c3c3cbb`) — `VerifiedSamlAssertion` has NO public constructor; the only path is `verify_assertion()`, which requires an `XmlDsigBackend`. Raw input is an opaque `UnverifiedSamlDocument` with no trusted accessors → the **compiler forbids acting on unverified SAML** (illegal states unrepresentable). **Strict binding (anti-XSW)**: backend returns ONLY the signature-verified subtree's fields (`VerifiedNodes`); raw XML never re-parsed for trusted data. **One-time-use replay cache** (TTL=NotOnOrAfter, Redis-backed at 40.l) + **clock-skew capped ≤5 min** (never widened) + **exact-binary audience** match vs SP EntityID (no trim). `XmlDsigBackend` contract documents the 40.l duties (no XXE: disable DTD/external entities; bound entity-expansion/size/time vs XML bombs; enveloped-signature over the whole element by ID; process timeout/memory cap + input sanitisation). Crypto signature verification stays delegated to the vetted backend at 40.l, but the type system now ENFORCES no assertion is trusted until that backend verified it. **18 tests (incl. RFC 7636 vector + mock-backend full path: replay/expired/audience/skew-cap); full workspace green.** Commits `9106c88` + `c3c3cbb`. **Honest scope**: HTTP fetches + ID-token SIGNATURE verification (IdP JWKS, RS256) + SAML XML-DSig compose at 40.l. | 
| **40.k** ✅ SHIPPED 2026-05-22 | SaaS — Secrets + crypto envelope → Rust (RustCrypto + `aws-sdk-kms`; local + KMS envelope; policy). | ✅ New BSL crate `crates/saas-crypto` (`axon-enterprise-crypto`) — **beats the typical "AES-GCM with one fixed key" design**. **envelope.rs**: `EnvelopeEncryption` trait + canonical AAD serialization (sorted, separator-rejecting wire contract) + versioned format (0x01 local / 0x02 KMS). **local.rs**: `LocalEnvelope` — per encrypt fresh salt → HKDF-SHA256(master, salt, info=AAD) → per-record AES-256 subkey → AES-256-GCM(nonce, pt, aad=AAD). **AAD bound in BOTH the HKDF info AND the GCM tag** → a ciphertext cannot be replayed across users/purposes (AAD-swap defence test proves it). Master key + derived subkeys `Zeroizing` (wiped on drop). **value.rs**: `SecretValue` — opaque, self-redacting (Debug/Display never leak), **ZEROIZE-ON-DROP** plaintext (a guarantee the GC'd Python original could NOT make), constant-time eq, audit-safe SHA-256 fingerprint. **14 tests** (roundtrip/AAD-swap/tamper/cross-key isolation/zeroize/SHA-256 fingerprint vector) + full workspace green. This is where 40.g's TOTP secret is sealed at rest (AAD `{user_id, purpose}`). Commit `c18009e`. **Honest scope**: deterministic local backend + SecretValue ship; KMS backend (`aws-sdk-kms`, format 0x02) implements the trait + composes at 40.l. | 
| **40.l** 🟡 CORE SHIPPED 2026-05-22 (infra assembly pending live-Postgres CI) | HTTP API convergence on **axum**: unify enterprise endpoints into the axon-rs axum app (tenant-context middleware, RBAC enforcement, audit, metering, OpenAPI, discovery). | 🟡 New BSL crate `crates/server` (`axon-enterprise-server`). 40.a–40.k shipped deterministic units; **the verified, offline-testable security CORE of the integration ships here**: **auth.rs** `evaluate_login` — the login state machine as a PURE function (lockout window → Argon2id verify → TOTP-at-rest decrypt+verify → transparent rehash) with anti-enumeration timing parity (unknown user / SSO-only account still spends a full Argon2 verify), composing 40.g identity + 40.k crypto; returns a `LoginDecision` the async wrapper persists. **8 tests incl. an end-to-end TOTP-at-rest flow** (enrol via envelope → require → wrong → correct) + rehash + lockout-crossing + every reject path. **store.rs** `UserStore`/`SessionStore` repo traits (DB boundary — keeps orchestration mockable). **schema.rs** core-table DDL from the 40.f RLS generators (fail-closed) + test. **errors.rs** `AuthError` (reveal_to_client discipline). 10 tests. Commit `e856b80`. **+ axum server assembly (commit `de790ef`)**: `http.rs` AppState (`Arc<dyn UserStore/SessionStore>` + `KeyRing` + envelope + hasher + configs) + `build_router` (`/healthz`, `/version`, `/.well-known/jwks.json`, `/token`) + the async `login` wrapper (find→evaluate→persist→mint §40.i JWT) + error→HTTP mapping (credential failures → generic 401). `store.rs` repo traits → `#[async_trait]` (dyn-compatible). `mock.rs` in-memory stores. **axum pinned to 0.8 to UNIFY with the OSS axon-server's axum** (single axum in the graph — prerequisite for one binary). **Tested offline via `tower::oneshot`**: `/token` mints a verifiable JWT with the right claims; **wrong-password ≡ unknown-user response proves anti-enumeration end-to-end**. **14 server tests + full workspace green.** **Honest status — NOT fully shipped like 40.a–k**: the HTTP surface + login flow are built+tested, but the remaining infra-bound completion (sqlx repos backing the traits, SSO `/sso/oidc|saml/*` callbacks + tenant/RBAC middleware, the KMS envelope backend, the vetted `XmlDsigBackend`, per-domain migrations, Docker cutover) needs live Postgres/AWS/HTTP and lands in the **real-Postgres CI lane**. Completes when that CI lane is green. | 
| **40.m** ✅ SHIPPED 2026-05-22 | Studio / debugger + remaining modules → Rust or honest deferral with reason. | ✅ New BSL crate `crates/studio` (`axon-enterprise-studio`), std-only. Ports the **complete deterministic part** of `studio/debugger.py`: breakpoint registry (set/remove/disable/list) + execution-snapshot store (capture/scoped-retrieval), in-memory + tested. The Python `step_into`/`step_over`/`continue_execution` were unimplemented stubs (`return None`) needing a **runtime debug hook in axon-rs** (pause-at-line + expose-locals + single-step) that does not exist — **honestly deferred** (`FlowDebugger::STEP_API_STATUS`) rather than ported as no-ops. 3 tests. Commit `853a148`. **⚠️ Surfaced a SCOPE RECKONING — see §14.** |
| | **— SaaS business domains (§14 reckoning; founder ratified 2026-05-22: port all, axon must be production-size + the real adopter uses them) —** | |
| **40.n** ✅ SHIPPED 2026-05-22 | **Persistence layer**: sqlx-backed `UserStore` / `SessionStore` + `RbacService` (roles→perms) + JWT key store + SSO state store + the `service.py`/`models.py` CRUD of the ported spine (identity/rbac/jwt/sso/secrets); per-domain migrations from the 40.f RLS generators. Unblocks the spine's persistence; query-builders + row-mappers unit-tested, live-DB paths in the Postgres CI lane. | ✅ New BSL crate `crates/saas-persistence` (`axon-enterprise-persistence`). **migrations.rs**: the COMPLETE spine schema (6 ordered migrations — baseline+extensions/schemas, identity users/memberships/sessions, rbac roles/permissions/role_permissions/user_roles, jwt_signing_keys, sso config/states, secrets); every tenant-scoped table gets **fail-closed RLS from the 40.f generators**, global tables (users/permissions/jwt-keys) stay admin_bypass-only. Fully unit-tested (DDL + RLS + users-is-global). **mappers.rs**: pure `UserRow→UserRecord` + status parsing, **FAIL-SAFE** (unknown status → Suspended, never Active) + negative-clamp; **chrono-free** (time → epoch-ms in SQL via `EXTRACT(EPOCH)*1000`). Fully unit-tested. **pg.rs**: `PgUserStore` + `PgSessionStore` implementing the 40.l traits; queries pinned as consts; sessions insert sets the tenant GUC in its tx (RLS-bound); refresh token = 32 random bytes hex, SHA-256 at rest (raw never stored) — unit-tested. Query paths compile-verified; correctness in the Postgres CI lane. **8 tests + full workspace green.** Commit `d9dd61a`. **Honest scope**: the RBAC grant/revoke + JWT key-rotation + SSO config/state CRUD stores follow the identical pattern (tested mappers + compile-verified sqlx + CI) and land with their domains (40.o+). | 
| **40.o** ✅ SHIPPED 2026-05-22 | `metering` (1,717 LOC) → Rust: usage metering + billing counters + overage + invoice surfacing. | ✅ New BSL crate `crates/saas-metering` (`axon-enterprise-metering`) — the **deterministic, money-critical billing core**, ported 1:1 from the Fase 10 Python `metering/`. **events.rs**: closed `MetricType` catalog (9 metrics — flow.execution/deployed, llm.tokens_in/out, storage/egress.bytes, api.calls, compute.time, provider.cost_passthrough) each paired with a stable `MetricUnit` (aggregation never guesses) + wire-slug roundtrip. **pricing.rs**: the 3 built-in `PlanSpec`s (starter free+hard_cap, pro $49/mo overage, enterprise $499/mo) + `plan_by_id`; **billing anti-drift tests pin every canonical number** so an accidental rate change fails CI. **quota.rs**: `evaluate_quota` PURE decision — hard-cap blocks any over-allowance, overage plans always allow + annotate the overage; metrics without an allowance are unlimited; tokens gate on the full included pool. **invoicing.rs**: `InvoiceGenerator` overage math ported verbatim (overage = max(0, total−included), **ceil-to-cent** no sub-cent drift; tokens use included/2 split; compute millicents/1000), deterministic line ordering by metric slug, **5 exact-cents test vectors** (pro 60k exec → 14_900; token/storage/compute → 15_650; 19% tax → 5_831). **errors.rs**: `MeteringError` taxonomy (PlanNotFound/QuotaExceeded/RateLimited/InvoiceAlreadyIssued/Backend) + stable `code()` slugs. **migrations.rs**: metering schema — **global** `pricing_plans` catalog (seeded from BUILT_IN_PLANS, the single comparison point) + **tenant-scoped** `tenant_subscriptions`/`usage_events`/`invoices` with **§40.f fail-closed RLS**, idempotent ingest (unique tenant+idempotency_key) + one-invoice-per-period + rollup indexes. **23 tests + full workspace green (zero failures).** Commit `5ee18d9`. **Honest scope**: the Stripe client + DB usage-event aggregation are integration layers that compose at §40.w; the billing arithmetic ships + is fully tested offline. |
| **40.p** ✅ SHIPPED 2026-05-22 | `audit` (1,065 LOC) → Rust: per-tenant Merkle audit log + JSONL/ZIP export, building on the `axon-csys-enterprise` C23 mmap kernel + the §40.d supervisor chain. | ✅ New BSL crate `crates/saas-audit` (`axon-enterprise-audit`) — the **tamper-evident compliance audit log**, a per-tenant **SHA-256 hash chain** (distinct from the §40.d supervisor HMAC chain) ported 1:1 from the Fase 10 Python `audit/`, with crypto delegated to the **FIPS-routable `axon-csys-enterprise` SHA-256** (the trail dogfoods the validated path). **events.rs**: closed `AuditEventType` catalog (**70 types / 12 categories**) — and a robustness fix: the Python `category()` **panicked on `replay:`/`pem:`** (no such `EventCategory`); the Rust `category()` is **total** (proven by a test resolving all 70) via added `Replay`+`Pem` categories. Slug roundtrip + uniqueness + count anti-drift. **canonical.rs**: `genesis_hash` (`SHA-256(GENESIS_MAGIC‖tenant)`, anyone can verify the first link) + `compute_event_hash` (`SHA-256(prev‖0x1e‖tenant‖0x1e‖seq8BE‖0x1e‖type‖0x1e‖canonical_json)`) over a **canonical JSON** matching the Python contract exactly — sorted keys, no spaces, `ensure_ascii` incl. **UTF-16 surrogate pairs** above U+FFFF (vector-tested vs `é\n🔐` → `é\n🔐`). **chain.rs**: validated `AuditWriteRequest` → `AuditLog::append` → `AuditRecord`; the structured `verify_chain`/`require_chain_healthy` catches **body tamper** (event_hash mismatch), a **severed `prev_hash` link**, and a **sequence gap** — never raising (returns `AuditChainReport` for dashboards/pagers); per-tenant chains verify independently. **export.rs**: `events_to_jsonl` (one canonical object/line, hashes base64url-no-pad) + a **hand-rolled byte-deterministic STORED ZIP** (CRC-32 IEEE — vector `123456789`→`0xCBF43926`; fixed 1980 timestamp, no extra fields → re-export is byte-identical for checksummable evidence; superior to the `zip` crate which embeds the wall clock). **migrations.rs**: `audit_events` tenant-scoped **fail-closed §40.f RLS** + a **DB-level append-only trigger (`SQLSTATE 42501`)** so tamper-evidence does not rely on app discipline + the `UNIQUE (tenant_id, sequence_number)` anti-fork constraint + rollup indexes. **errors.rs**: `AuditError` taxonomy (all `reveal_to_client=false`). **24 tests + full workspace green (zero failures).** Commit `0425ff4`. **Honest scope**: the advisory-locked (`pg_advisory_xact_lock(hashtext(tenant_id))`) sqlx writer + the admin export/verify endpoints compose at §40.w; the chain + crypto + export logic ships + is fully tested offline. |
| **40.q** ✅ SHIPPED 2026-05-22 | `compliance` (2,984 LOC) → Rust: the compliance engine (Fase 29 lineage — policy/control/framework/gap/evidence). | ✅ New BSL crate `crates/saas-compliance` (`axon-enterprise-compliance`) — the **GDPR/CCPA/SOC 2 operations engine** (the actual Python module is data-subject-rights ops, not the Fase 29 diagnostics; the plan's label was approximate). DB workers (`FOR UPDATE SKIP LOCKED` polling), S3/filesystem blob streaming, and the ASGI residency middleware are integration (§40.w); the **decisions + crypto + packaging** ship + are fully tested offline. **models.rs**: `ComplianceRequestKind` (sar_export/erasure) + `ComplianceRequestStatus` (6 states incl. the erasure-only `awaiting_purge` intermediate) + slug roundtrip + terminal-state. **state.rs** (the high-value pure core): the ticket lifecycle state machine — `is_claimable` (queued & due), `dispatch_action` (the worker's pure **two-stage erasure / export decision**, TOTAL over kind×status — export→RunExport, erasure queued→RunSoftDelete, awaiting_purge & due→RunAnonymize, terminal→Skip), `validate_complete` (only `in_progress`/`awaiting_purge` may complete — a wrong transition here corrupts the queue, so pinned), `purge_window_end_ms` (now + soft_delete_days). **residency.rs**: `evaluate_residency` (Allow / **308-redirect** / **421-Misdirected**) + `build_redirect_url` (`{region}` host templating, query preservation) + `TenantRegionCache` (TTL expiry, monotonic-ms supplied → pure). **legal_holds.rs**: `HoldRegistry` enforcing **at most one active hold per (tenant, subject)** with normalised (trim+lowercase) subject matching, idempotent release, and the `assert_no_hold` erasure guard. **erasure.rs**: deterministic **`anonymized_email`** (`erased-<sha256(email)[..16]>@axon.internal` — same subject always → same identity), `subject_fingerprint` (full SHA-256 hex — proves a subject was processed without storing PII), `build_purge_report` (version/tenant/request/fingerprint/anonymized_email/counts — **vector-tested to contain NO raw PII** + byte-deterministic via the §40.p canonical serializer), `erasure_blob_key` (zero-padded date path). **evidence.rs**: SOC 2 `build_manifest` (embeds the **audit-chain verification report** + counts) + `build_evidence_bundle` reusing the §40.p **byte-deterministic STORED ZIP** (replaces the Python timestamped tar.gz → re-export is byte-identical + checksummable; 7 fixed-order members) + `evidence_blob_key`. **blob.rs**: `BlobStore` trait + the **`reject_path_traversal` guard** (rejects `..` segments before any I/O) + `content_digest` (backend-independent SHA-256+size) + `InMemoryBlobStore`. **migrations.rs**: `compliance_requests` + `legal_holds` tenant-scoped **fail-closed §40.f RLS**; the **partial worker-claim index** `(status, scheduled_for) WHERE status IN ('queued','awaiting_purge')` (O(log N) claim) + the **partial unique active-hold index** `(tenant, subject) WHERE released_at IS NULL` + FK `axon_admin.tenants` `ON DELETE RESTRICT`. **errors.rs**: `ComplianceError` taxonomy (`reveal_to_client` flags match Python — backend opaque, the rest surfaced). **35 tests + full workspace green (zero failures/warnings).** Legitimately depends on `axon-enterprise-audit` (evidence bundles embed the audit chain + reuse its deterministic ZIP). Commit `f290263`. **Honest scope**: the advisory-locked worker loop + S3/local blob backends + the residency ASGI middleware + DB-row fetching for evidence/SAR compose at §40.w. |
| **40.r** ✅ SHIPPED 2026-05-22 | `diagnostics` (1,935 LOC) → Rust: the diagnostics engine (Fase 29 lineage — policy/telemetry/suggest/store/gate). | ✅ New BSL crate `crates/saas-diagnostics` (`axon-enterprise-diagnostics`) — the **Fase 29 vertical-aware diagnostic stack** (genuine Fase 29 lineage; D1-D9 ratificadas). **No DB tables** — the recent-store is in-memory + durable records flow through the §40.p audit `COMPLIANCE_PARSE_ERROR` event, so this crate ships no migrations (faithful to the Python design). OTel/Prometheus fan-outs (§40.u), the dashboard endpoint, and the CI CLI (§40.v) are integration. **policy.rs**: closed `TenantVertical` catalog (generic/hipaa/legal/fintech) + `DiagnosticPolicy` (strict/telemetry/recovery/extra_keywords dials) + `resolve_policy_for_vertical` with the **D1/D2 defaults pinned** (HIPAA/legal default-strict+telemetry-on, fintech recovery+telemetry-on, generic = OSS Fase 28 verbatim) + `matches_oss_default` (D9 invariant) + `VerticalRegistry` (unregistered → generic). **telemetry.rs**: the **D4-privacy boundary baked into the type** — `ParserDiagnostic` has NO source/snippet field, so "never emit source text" is compiler-enforced; `emit_parser_error` is a **no-op when telemetry disabled** (D9 gate); `AuditSink` trait + `InMemoryAuditSink` (FIFO-bounded, D8 per-tenant isolation). **suggest_dicts.rs**: the **154 curated terms EMBEDDED via `include_str!`** (52 hipaa + 51 legal + 51 fintech — superior to the Python `importlib.resources` filesystem load: ships compiled-in, version-locked, no runtime file dependency); **D3** non-empty-provenance + **D8** vertical-match + no-duplicate validation; `assert_no_cross_vertical_contamination` (pairwise-disjoint D8 gate, run over the real data in tests); `policy_with_suggest_dict` enrichment. **store.rs**: `RecentDiagnosticsStore` per-tenant capacity-bounded ring buffer (FIFO eviction, D8-scoped, chrono-free epoch-ms) + line-bucket aggregation sorted count-desc. **gate.rs**: the pure CI compliance-gate — `GateVerdict`/`GateConfig`/`GateResult` + `evaluate` (JSON payload → verdict, raw/aggregated severity counting, error/warning/hint thresholds, `FAIL_INPUT` on malformed input rather than panic) + the exit-code projection (PASS→0 / FAIL_EXCEEDED→1 / FAIL_INPUT→2) + `format_summary` (D4-safe, no source). **28 tests + full workspace green (zero failures/warnings)** — including the 154-term D3 + D8 contamination checks over the real embedded dictionaries. Dep: serde_json only. Commit `78d3c9d`. **Honest scope**: the OTel span + Prometheus counter sinks (§40.u), the `/api/v1/tenant/diagnostics/recent` dashboard endpoint, the `axon-enterprise diagnostics gate` CLI (§40.v), and the current-`TenantContext` policy resolution compose at integration. |
| **40.s** | `api_keys` (359) + `invitations` (235) → Rust: tenant API-key issuance/verification + user-invitation lifecycle. | ⏳ |
| **40.t** | `cognitive_states` (579) + `replay` (460) → Rust: cognitive-state + replay-token persistence. | ⏳ |
| **40.u** | `config` (742) → Rust (consolidate per-crate configs into a settings layer) + `observability` (926) → Rust (OTel / Prometheus / structured-log exporters). | ⏳ |
| **40.v** | `cli` (1,311) → Rust: the enterprise CLI, converged onto the axon-server CLI surface. | ⏳ |
| **40.w** | `http` (4,637) API convergence: the remaining REST endpoints (beyond 40.l's auth spine) onto the axum app + tenant-context + RBAC-enforcement middleware + OpenAPI/discovery; one binary with the OSS axon-server. | ⏳ |
| | **— Finale (unchanged; runs only after every domain is ported) —** | |
| **40.x** | Test migration (mirror 39.g): enterprise Python tests → Rust integration / subprocess tests; honest quarantine of the rest with PR reason. | ⏳ |
| **40.y** | Purga: remove ALL Python from axon-enterprise (mirror 39.h). `axon_enterprise/` + `pyproject.toml` + `alembic/` Python → gone; repo becomes a pure Rust/C workspace. | ⏳ |
| **40.z** | Dockerfile cutover: single `axon-enterprise-server` binary compiled in; `ENTRYPOINT` flip; remove the `AXON_VERSION` download stage (axon-lang is a compiled-in Cargo dep now, not a downloaded binary); multi-arch amd64/arm64. | ⏳ |
| **40.aa** | Release axon-enterprise **v2.0.0** (the REAL catch-up) + ECR image + **lift the pin-cap** (`<2.0.0` → `>=2.0.0` / or drop the bound). The v2.0.0 cycle completes HERE. | ⏳ |
| **40.ab** | Adopter cutover (`output: T` → `output: FlowEnvelope<T>`) verified on staging + green in production on the v2.0.0 image. | ⏳ |

> Sub-fases are gated individually by an explicit founder "procede". 40.f→40.k
> (the SaaS domains) are largely independent and may be reordered as convenient.

# ▶ 6. Enterprise-only primitives — the two-tier model (D3)

The founder's vision: "enterprise tendrá primitivas que lang no verá porque
vivirán solo en el código de enterprise." Honest breakdown:

- **Tier 1 — runtime primitives** (new shield scanners, backends, OTS pipelines,
  algebraic-effect handlers): plug into the `pub` registries axon-rs exposes
  (40.b ships the shield hook). Enterprise authors them directly in its repo;
  OSS never sees them; the generic language syntax (`shield apply X`) drives
  them. **Covers 100% of today's verticals — clean and immediate.**
- **Tier 2 — novel-syntax primitives** (a keyword/grammar only enterprise's
  parser understands): requires a deliberate extension-point in axon-frontend
  (a hand-written recursive-descent parser does not accept injected grammar for
  free). Real language design work; **not free.** Deferred to a dedicated
  sub-fase the first time enterprise needs syntax OSS will never have.

# ▶ 7. SaaS → Rust mapping + the SAML caveat

| Python domain (today) | Rust target | Maturity |
|-----------------------|-------------|----------|
| sqlalchemy + alembic | `sqlx` + `refinery` | solid |
| argon2 / TOTP | `argon2` (RustCrypto) / `totp-rs` | solid |
| JWT issuer + JWKS | `jsonwebtoken` + `josekit` | solid |
| OIDC / PKCE | `openidconnect` | solid |
| **SAML** | `samael` | **younger than `pysaml2` — D7 risk** |
| RBAC / secrets / crypto / KMS | Rust + `aws-sdk-kms` + RustCrypto | solid |
| HTTP (starlette/FastAPI) | **`axum`** (converges with axon-rs) | solid |

Most domains have mature Rust crates; the HTTP layer converging on axum is a net
architectural win. SAML is the single thin spot — evaluated explicitly in 40.j.

# ▶ 8. Scope discipline (out of scope)

- ❌ Forking axon-lang (D1 — Cargo dependency instead).
- ❌ FFI / ctypes bridge (the 27.k.1 path — superseded by full Rust; no parity tax).
- ❌ A transient hybrid release (founder rejected: hybrid = debt = regression).
- ❌ Tier-2 novel-syntax primitives (D3 — deferred until first needed).
- ❌ Privatizing axon-lang now (architecture preserves the OPTION; not exercised here).

# ▶ 9. The closing condition

Fase 40 closes — and the v2.0.0 cycle finally completes — when ALL of:

- ✅ Sub-fases 40.a → 40.r SHIPPED.
- ✅ axon-enterprise is a pure Rust/C workspace; `find . -name "*.py"` returns
  empty (zero Python — mirror of the Fase 39 audit, now for the business repo).
- ✅ axon-enterprise depends on axon-lang 2.0.x via versioned Cargo dependency.
- ✅ Single `axon-enterprise-server` axum binary; Docker ENTRYPOINT flipped; ECR
  image built multi-arch.
- ✅ Vertical cognition (HIPAA/legal/AML) runs in Rust, feature-gated BSL.
- ✅ The pin-cap is lifted; enterprise v2.0.0 released.
- ✅ The adopter's coordinated migration verified on staging + green in production.
- ✅ Memory + Fase 39 plan updated to reflect the v2.0.0 cycle as truly closed.

## 9.1 Anti-conditions (we did it wrong if any apply)

- ❌ Any Python remains in axon-enterprise.
- ❌ A copy of axon-lang's code lives in the enterprise repo (fork drift).
- ❌ Enterprise reaches axon-lang via FFI/subprocess instead of a Cargo dependency.
- ❌ A dual-runtime parity gate exists (the tax Fase 39 killed must stay dead).
- ❌ The pin-cap was lifted before the Rust path was proven (D2 violated).

# ▶ 14. Scope reckoning (surfaced at 40.m, 2026-05-22)

40.m's "remaining modules" inventory revealed that the original sub-fase set
(40.a–40.r) **under-scoped the SaaS breadth**. The plan enumerated db / identity
/ rbac / jwt / sso / secrets-crypto + verticals / supervisor / catalogs / studio
— but `axon_enterprise/` holds **~17K LOC across 12 more domains with no
sub-fase**:

| Domain | LOC | Nature |
|--------|-----|--------|
| `http` | 4,637 | HTTP API layer — largely composes at 40.l (axum) |
| `compliance` | 2,984 | compliance engine (Fase 29 lineage) — substantial |
| `diagnostics` | 1,935 | diagnostics (Fase 29 lineage) — substantial |
| `metering` | 1,717 | usage metering + billing — substantial |
| `cli` | 1,311 | enterprise CLI — converges with axon-server CLI |
| `audit` | 1,065 | Merkle audit log (axon-csys-enterprise has the C23 mmap kernel; supervisor has a chain) |
| `observability` | 926 | OTel / Prometheus exporters — infra integration |
| `config` | 742 | settings (partly covered by per-crate configs) |
| `cognitive_states` | 579 | cognitive-state persistence |
| `replay` | 460 | replay tokens |
| `api_keys` | 359 | tenant API keys |
| `invitations` | 235 | user invitations |

Plus the DB-backed `service.py` / `models.py` layers of the already-ported
domains (those shipped their deterministic CORES only).

**Implication:** the purga (40.o) CANNOT run until these are ported or
explicitly dropped — deleting `axon_enterprise/` Python today loses audit /
metering / compliance / diagnostics / etc. The release (40.q) + pin-cap lift
require a functionally-complete Rust enterprise.

**Decision RATIFIED (founder, 2026-05-22):** port **all 12 domains** — no triage,
no deferral. Rationale (verbatim intent): *"axon debe tener tamaño producción; si
en v1 tenía todo esto, en v2 no se entiende que no lo tenga. Los 12 dominios los
usa el adopter SaaS real que está esperando a axon — es un proyecto real."* The
tail was re-planned with explicit sub-fases **40.n–40.w** for persistence + the 12
domains; the finale (test migration / purga / Docker / release / adopter) moved to
**40.x–40.ab** and runs ONLY after every domain is ported. The auth/security spine
(db/identity/rbac/jwt/sso/crypto/supervisor/vertical) + the login-flow integration
are DONE; 40.n–40.w are the remaining ~17K-LOC body. Same discipline as 40.a–40.m:
deterministic cores unit-tested offline, live-DB/AWS/HTTP paths in the Postgres CI
lane.

---

> Related plans: [[project-fase-39-plan]] (the language half of v2.0.0),
> [[project_axon_enterprise_charter]] (privileged vertical layer),
> [[feedback_zero_py_files_north_star]] (now extended to the business repo),
> [[feedback_axon_for_axon]] (40.b shield hook is language work),
> [[feedback_enterprise_catch_up_always]] (the directive Fase 40 honors).
