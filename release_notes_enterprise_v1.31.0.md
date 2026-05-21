# axon-enterprise v1.31.0 — catch-up to axon-lang 1.40.0 (Cardinality Coverage Complete, Fase 38.x.f)

**Minor catch-up.** Lifts the enterprise stack to axon-lang 1.40.0 + axon-frontend 0.21.0, inheriting transitively the v1.39.0 → v1.40.0 promotion from the narrow Retrieve Cardinality Gate to a **FULL bilateral cardinality surface** at compile time.

## What enterprise tenants get

Beyond the v1.30.0 narrow catch (retrieve-tail + singular-output → `axon-T9XX`), v1.31.0 closes ALL remaining cardinality mismatch classes at `axon check`:

- **D1 expanded** — `for x in xs { … }` tails + singular outputs → `axon-T9XX`
- **D3 bilateral** — singular tails + `output: List<T>` → `axon-T9XX` symmetric
- **D5** — `output: Stream<T>` + non-stream tails (and the bilateral arm) → `axon-T9YY stream_cardinality_mismatch`
- **D6** — `if/else` branches disagreeing on cardinality → `axon-W003`
- **D2** — runtime D5 hint payload enriched: `expected_cardinality` / `got_cardinality` / `got_length` / `remediation_url` surface in `audit_log`
- **D4** — `AXON_VERBOSE_D5_HINT` env var exposes the full audit payload to the client response body for dev/staging (OWASP-safe by default; opt-in only)
- **Parser fix** — `axonendpoint output:` now generic-aware (`List<T>` + `Stream<T>` properly captured; pre-existing single-token bug closed)

## Vertical inheritance

- **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** — clinical investigative `for record in cases { … }` flows + singular endpoint outputs caught at `axon check` instead of opaque runtime D5; `Stream<ClinicalToken>` outputs verified against stream-producing flows.
- **FRE 502 + Upjohn / Hickman + ABA Rule 1.6** — privilege-review `for doc in corpus { … }` flows with singular-output endpoints emit T9XX at compile time; branch-disagreement W003 catches conditional-shape mismatches in privilege-assessment flows.
- **BSA / OFAC / MiFID II AML** — investigative `for tx in transactions { … }` flows + singular AML-decision endpoints emit T9XX; `Stream<AlertChunk>` outputs verified against streaming sources.
- **FedRAMP AU-2** government decision support — benefit-eligibility flows with `if applicant_tier { … } else { … }` branches disagreeing on cardinality emit W003 with actionable hint at `axon check`.

## Catch-up surface

- `pyproject.toml`: version 1.30.0 → 1.31.0, dep pin `axon-lang>=1.39.0` → `>=1.40.0`.
- `axon_enterprise/__init__.py`: `__version__` 1.30.0 → 1.31.0.

axon-frontend Rust crate dep bumps transitively from 0.20.0 → 0.21.0 (new public `Cardinality` enum + propagation pass + expanded gate + parser fix).

v1.31.0 is a lean catch-up — same shape as v1.29.0 / v1.29.1 / v1.29.2 / v1.29.3 / v1.29.4 / v1.30.0. Per the standing rule (every axon-lang release ships an axon-enterprise catch-up), this closes the v1.40.0 cycle in lockstep.

## Migration

**No breaking changes.** Adopters with `output: List<T>` endpoints whose pre-existing flows were well-formed (plural tail) continue to pass. Adopters with latent shape mismatches v1.30.0 silently passed now get an actionable T9XX/T9YY/W003 at `axon check` BEFORE production. Set `AXON_VERBOSE_D5_HINT=1` for verbose hint at the client response body (dev/staging only).
