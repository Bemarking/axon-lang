---
title: "Plan vivo: Fase 40 — Enterprise Pure Silicon (the real v2.0.0 catch-up: axon-enterprise → 100% Rust/C)"
status: 🛠️ IN PROGRESS — 40.a SHIPPED 2026-05-21 (Rust workspace foundation; enterprise interprets its own language via versioned Cargo dependency). D1 ratified founder 2026-05-21.
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
| **40.b** | OSS shield extension-point in **axon-rs** (`pub` scanner-registration hook so the BSL vertical crate injects scanners into `apply_shield`). Ships as axon-lang v2.0.2/v2.1.0. *Axon-for-axon: a clean language extension point.* | ⏳ |
| **40.c** | Vertical cognition → Rust (the R&D crown jewels): port HIPAA / legal / AML scanner families (~1.5K LOC) + dual-LLM + ensemble onto the 40.b hook + OSS shield framework. BSL, feature-gated. | ⏳ |
| **40.d** | Supervisor enterprise layer → Rust: port hierarchy / factory (~1.9K LOC) onto axon-rs `DaemonSupervisor`. | ⏳ |
| **40.e** | Catalogs / discovery → Rust: `primitives.py` catalogs (legal_basis / ots / stream / trust / buffer) served from the axon-server discovery endpoint. | ⏳ |
| **40.f** | SaaS — DB + migrations → Rust (`sqlx` + `refinery`/`sqlx migrate`); tenant + RLS policies. | ⏳ |
| **40.g** | SaaS — Identity → Rust (`argon2` / `totp-rs`; password policy / lockout / sessions). | ⏳ |
| **40.h** | SaaS — RBAC → Rust (permissions / models / service / enforce / seed). | ⏳ |
| **40.i** | SaaS — JWT issuer + JWKS → Rust (`jsonwebtoken` / `josekit`; local + KMS signer; revocation; key management). | ⏳ |
| **40.j** | SaaS — SSO → Rust (`openidconnect` for OIDC/PKCE/discovery/id-token; **SAML risk per D7**). | ⏳ |
| **40.k** | SaaS — Secrets + crypto envelope → Rust (RustCrypto + `aws-sdk-kms`; local + KMS envelope; policy). | ⏳ |
| **40.l** | HTTP API convergence on **axum**: unify enterprise endpoints into the axon-rs axum app (tenant-context middleware, RBAC enforcement, audit, metering, OpenAPI, discovery). | ⏳ |
| **40.m** | Studio / debugger + remaining modules → Rust or honest deferral with reason. | ⏳ |
| **40.n** | Test migration (mirror 39.g): enterprise Python tests → Rust integration / subprocess tests; honest quarantine of the rest with PR reason. | ⏳ |
| **40.o** | Purga: remove ALL Python from axon-enterprise (mirror 39.h). `axon_enterprise/` + `pyproject.toml` + `alembic/` Python → gone; repo becomes a pure Rust/C workspace. | ⏳ |
| **40.p** | Dockerfile cutover: single `axon-enterprise-server` binary compiled in; `ENTRYPOINT` flip; remove the `AXON_VERSION` download stage (axon-lang is a compiled-in Cargo dep now, not a downloaded binary); multi-arch amd64/arm64. | ⏳ |
| **40.q** | Release axon-enterprise **v2.0.0** (the REAL catch-up) + ECR image + **lift the pin-cap** (`<2.0.0` → `>=2.0.0` / or drop the bound). The v2.0.0 cycle completes HERE. | ⏳ |
| **40.r** | Adopter cutover (`output: T` → `output: FlowEnvelope<T>`) verified on staging + green in production on the v2.0.0 image. | ⏳ |

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

---

> Related plans: [[project-fase-39-plan]] (the language half of v2.0.0),
> [[project_axon_enterprise_charter]] (privileged vertical layer),
> [[feedback_zero_py_files_north_star]] (now extended to the business repo),
> [[feedback_axon_for_axon]] (40.b shield hook is language work),
> [[feedback_enterprise_catch_up_always]] (the directive Fase 40 honors).
