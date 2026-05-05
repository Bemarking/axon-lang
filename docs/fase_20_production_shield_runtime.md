---
title: "Plan vivo: Fase 20 — Production Shield Runtime + Plugin Registry + Vertical R&D split"
status: PLANNED — sub-fases 20.a–20.k pendientes
owner: AXON Language Team
created: 2026-05-05
updated: 2026-05-05
target: axon-lang v1.15.0 (PyPI + crates.io) + axon-enterprise v1.7.0 (vertical scanners) — coordinated cross-stack + cross-repo
depends_on: Fase 18 / 19 SHIPPED (drift gate + observability + property tests + dispatcher contract)
---

# FASE 20 — PRODUCTION SHIELD RUNTIME + PLUGIN REGISTRY + VERTICAL R&D SPLIT

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** Cierra el último compile-only/runtime-stub gap conocido en AXON. El TypeChecker valida desde Fase 11 que un Shield declara una de 6 estrategias (`pattern` / `classifier` / `dual_llm` / `canary` / `perplexity` / `ensemble`); el runtime hoy ignora la estrategia y siempre devuelve `scan_passed = True`. Fase 20 implementa los scanners reales, añade categoría `capability_validate` para D8 capability-gate criptográfico, y expone el plugin registry `axon.runtime.shield_scanners.register(category, fn)` para que adopters extiendan sin forkear.
- **Why:** Shield es la primitiva núcleo del Epistemic Security Kernel — la promesa diferencial de AXON como lenguaje cognitivo determinista basado en matemáticas. Un Shield que el typechecker valida pero el runtime no ejecuta es **una falsa garantía de seguridad** — peor que no tener Shield. Cualquier adopter en producción enterprise lo necesita real.
- **OSS / ENTERPRISE / SPLIT split:** Esta fase es paradigmática del charter axon-enterprise: el OSS recibe arquitectura + contratos + scanners genéricos baseline; **enterprise recibe los catálogos verticales (HIPAA PHI, legal privilege, FDA/GxP, fintech AML), judge LLMs pre-prompted, y ensemble configs por dominio**. La asimetría es intencional — un fork OSS puede mejorar el runtime; lo que no puede replicar trivialmente es el conocimiento vertical curado en enterprise.
- **Robustness target:** ship Hypothesis property tests para cada strategy (≥100 casos); adversarial fuzz que intente pasar prompts maliciosos por cada scanner; drift gate extension que falla si `scan_passed = True` aparece hardcoded; ≥+80 nuevos tests con ≥85% coverage del nuevo código.

---

## 2. Audit findings — qué dejó Fase 19 y qué falta

Inspección empírica de v1.14.0 (commit `bb7e61c`):

| Concern | Pre-Fase-20 state | Risk |
|---|---|---|
| Las 6 strategies declaradas son no-op | `_VALID_SHIELD_STRATEGIES = {pattern, classifier, dual_llm, canary, perplexity, ensemble}` en `type_checker.py:2916`; `_execute_shield_step` en `executor.py:3470` documenta literalmente *"The actual scanning is deferred to a future phase"* y línea `executor.py:3546` hace `scan_passed = True` incondicionalmente. | Falsa garantía: el flow compila green, los tests verdes, pero ningún prompt malicioso es interceptado. Adopters en healthcare / legal / fintech tienen una ESK no-op pensando que está activa. |
| `_VALID_SCAN_CATEGORIES` no incluye `capability_validate` | 11 categorías (`prompt_injection`, `jailbreak`, `data_exfil`, `pii_leak`, `toxicity`, `bias`, `hallucination`, `code_injection`, `social_engineering`, `model_theft`, `training_poisoning`). D8 capability gate solo enforza allow/deny lists — no valida criptográficamente capability tokens. | Adopters que firman capabilities con ed25519 / HMAC / JWT (Fase 11.a Trust Types catalog) no pueden expresar la validación a través del Shield; la valida ad-hoc en código adopter, perdiendo el determinismo del compile-time check. |
| No hay plugin hook `axon.runtime.shield_scanners.register(...)` | Comment en `_execute_shield_step` lo nombra como "future phase". | Adopters con detector de PHI custom (HIPAA), patrones legales privilege-aware, o reglas fintech AML deben forkear el repo. Ya hay un adopter pidiéndolo. |
| Drift gate no asserta scanner real | `tests/test_fase19_drift_gate.py` asserta que no haya `_stub: True` en dispatchers; **no asserta** que Shield no haga `scan_passed = True` hardcoded. | Si la implementación regresara al estado actual (todo pasa), CI quedaría verde. |
| Sin tests adversariales | Property tests + fuzz solo cubren control flow + memory + CPS. Shield no tiene fuzz que intente pasar prompts maliciosos. | Cobertura a ciegas — cualquier strategy puede tener falsos negativos invisibles. |

**Severidad uniforme**: cada item es un **production-readiness concern de seguridad**, no una optimización. v1.14.0 es honesta sobre lo que ya envió (Fases 18 + 19); Fase 20 cierra el último mile estructural conocido del ESK.

---

## 3. Architecture — three concerns, one release, vertical split

### 3.1 Plugin registry — punto de extensión del adopter

`axon/runtime/shield_scanners.py` (nuevo) expone:

```python
class ShieldScanner(Protocol):
    def scan(self, target: str, *, context: ScanContext) -> ScanResult: ...

class ShieldScannerRegistry:
    def register(self, category: str, scanner: ShieldScanner, *, strategy: str = "pattern") -> None
    def lookup(self, category: str, strategy: str) -> ShieldScanner | None
    def known(self) -> dict[str, list[str]]  # {category: [strategy, ...]}
```

Default registry pre-pobla los scanners OSS (pattern + canary + capability_validate baseline). Adopters extienden por código:

```python
from axon.runtime.shield_scanners import default_registry
default_registry.register("phi_leak", MyPhiLeakScanner(), strategy="classifier")
```

Inyectado en `Executor.__init__` con la misma disciplina `is None` que ya usan `continuity_signer` / `hibernation_store` / `pix_registry` (lección de Fase 19 — empty store es falsy → `or` lo descarta silenciosamente).

### 3.2 6 strategies — semántica + dependencias

| Strategy | Semantic | Soft deps | OSS / ENTERPRISE | Notes |
|---|---|---|---|---|
| `pattern` | Regex contra catálogos de threat patterns | ninguna | **OSS baseline; ENTERPRISE catálogos** | OSS ships catálogos genéricos (prompt_injection, jailbreak basic). Enterprise ships catálogos verticales: HIPAA PHI regex set, legal privilege markers, FDA validation phrases. |
| `canary` | Inyectar canary tokens en el contexto; detectar si aparecen en output (data exfil signal) | ninguna | **OSS** | Mecanismo genérico; tokens son aleatorios per-flow. |
| `capability_validate` (categoría nueva) | Verificación criptográfica de capability tokens (ed25519 / HMAC / JWT) | `cryptography` | **OSS** | Reusa `axon.runtime.pem.continuity_token` infra. Generalización del D8 capability gate. |
| `classifier` | ML classifier (HF embeddings → cosine vs threat embeddings) | `transformers` (soft) | **SPLIT** | OSS = protocolo + integración HuggingFace genérica. **ENTERPRISE = pre-trained classifiers en healthcare PHI synthetic / legal contract leaks / financial fraud**. |
| `dual_llm` | Judge LLM evalúa el target contra rubric de threat | LLM client (existing) | **SPLIT** | OSS = arquitectura + judge prompt genérico. **ENTERPRISE = judge prompts curados + few-shot examples por vertical (HIPAA, GDPR Art. 25, MiFID II, FDA 21 CFR Part 11)**. |
| `perplexity` | Entropy-based detection: prompts adversariales suelen ser high-perplexity contra el modelo base | logits del modelo (Anthropic SDK no expone — limitante real) | **OSS feature-flagged** | Solo activable cuando el backend expone logits. Documentar como "available with: OpenAI API, vLLM, llama.cpp". Anthropic-bound flows degradan a fallback `dual_llm`. |
| `ensemble` | Vota sobre N scanners; threshold configurable | depende de los scanners compuestos | **SPLIT** | OSS = composition operator + thresholds + vote strategies. **ENTERPRISE = ensemble configs por vertical (ej. healthcare = pattern HIPAA + classifier PHI + dual_llm GDPR judge, threshold ≥ 2/3)**. |

### 3.3 Vertical R&D — qué se queda en enterprise (charter recordatorio)

Per `memory/project_axon_enterprise_charter.md` — axon-enterprise no es wrapper multitenant. Esta fase es paradigmática:

- **OSS** = el lenguaje + el contrato + los scanners arquitecturales + los baselines genéricos. Un adopter OSS con `pattern` + `canary` + `capability_validate` + `classifier` (HuggingFace genérico) tiene un Shield funcional, sin depender de enterprise.
- **ENTERPRISE** = los catálogos verticales pre-curados. Un adopter healthcare que toma enterprise recibe **HIPAA PHI patterns + ICD-10/CPT vocabulary scanners + GDPR Art. 25 judge prompts + ensemble config "healthcare-grade" pre-tuneado**. Replicar esto requiere I+D + dataset curation + legal review — **moat real**.
- **SPLIT** (la mayoría de las strategies): la mecánica vive OSS; la inteligencia vertical vive enterprise.

---

## 4. Sub-phases

- **20.a** `axon/runtime/shield_scanners.py` — `ShieldScanner` Protocol + `ShieldScannerRegistry` + thread-safe in-memory default + `Executor.__init__` injection (`is None` discipline). **OSS.**
- **20.b** `pattern` strategy — regex matcher with curated threat catalogs (prompt_injection / jailbreak / code_injection baseline catalogs). Sub-Protocol `PatternScanner` for adopter custom catalogs. **OSS baseline + ENTERPRISE catálogos verticales.**
- **20.c** `canary` strategy — injects per-flow random canary tokens into context, asserts they don't leak into outputs (data exfil signal). Generic mechanism. **OSS.**
- **20.d** `capability_validate` category + scanner — ed25519 / HMAC / JWT capability token verification reusing `ContinuityTokenSigner` infra. New `_VALID_SCAN_CATEGORIES` entry. **OSS.**
- **20.e** `classifier` strategy — HuggingFace `transformers` soft-dep for embeddings; cosine sim vs threat embedding bank. **SPLIT** — OSS protocol + generic integration; enterprise pre-trained banks (PHI, legal, fintech).
- **20.f** `dual_llm` strategy — judge LLM evaluation with rubric. Reuses existing `ModelClient`. **SPLIT** — OSS architecture + generic prompt; enterprise pre-curated rubrics by vertical.
- **20.g** `perplexity` strategy — feature-flagged; activates only when backend exposes logits. Falls back to dual_llm with logged warning when unavailable. **OSS.**
- **20.h** `ensemble` strategy — composes N scanners with configurable vote strategy (majority / unanimous / threshold). **SPLIT** — OSS operator; enterprise vertical-specific configs.
- **20.i** Hypothesis property tests + adversarial fuzz: each strategy gets ≥100 inputs from threat corpora; fuzz tries to bypass each scanner with mutations of known malicious prompts. **OSS.**
- **20.j** Drift gate extension: parse `_execute_shield_step` for `scan_passed = True` or `scan_passed = False` literals → fail CI if found (forces dispatch through registry). Also asserts every member of `_VALID_SHIELD_STRATEGIES` has at least one registered scanner in the default registry. **OSS.**
- **20.k** Documentation honesty + memory + plan SHIPPED + coordinated v1.15.0 release (axon-lang) + axon-enterprise v1.7.0 release (vertical scanners + healthcare/legal/fintech ensemble configs). **SPLIT.**

### 4.1 Out of scope

- **Real-time streaming scan integration**: scanners run on full target; streaming-mode partial scans are a follow-up.
- **Scanner result caching across flows**: each scan is independent; caching by content-hash is a perf optimization for a follow-up.
- **Custom strategy beyond the 6**: `_VALID_SHIELD_STRATEGIES` stays closed-set in OSS. Adopters who want a 7th must extend the catalog via PR; enterprise can add internal-only strategies.
- **Logits exposure for Anthropic backend**: the SDK does not expose logits; perplexity strategy is feature-flagged off for Anthropic-bound flows. Closing this requires upstream SDK work or self-hosting via Bedrock — outside Fase 20 scope.
- **Compliance evidence packagers** (SOC 2 / HIPAA / FedRAMP audit reports auto-generated from shield events): enterprise concern; tracked separately under axon-enterprise compliance phase.

---

## 5. Acceptance gate

Fase 20 ships when ALL of the following hold green on master:

1. Every strategy in `_VALID_SHIELD_STRATEGIES` has a registered scanner in `default_registry`. Drift gate enforces.
2. `tests/test_fase20_shield_*.py` ≥ 80 new tests across the 6 strategies + registry + capability_validate.
3. Adversarial fuzz: each strategy survives ≥30 mutation rounds against a baseline corpus of malicious prompts (CommonAttacks, do-anything-now, prompt-leak attempts).
4. `scan_passed = True` literal removed from `axon/runtime/executor.py` (drift gate enforces).
5. `axon-enterprise` v1.7.0 ships HIPAA / legal / fintech catálogos + healthcare / legal ensemble configs as separate package; CI cross-stack test confirms enterprise overlays load against OSS registry.
6. Documentation: this plan flipped to SHIPPED; memory record updated; CHANGELOG.md + README.md mention the new shield registry + how to extend.
7. No regression: 849 Python + 1195 Rust tests stay green; cross-stack parity goldens unchanged.

---

## 6. How to apply

When the user mentions Shield runtime, scan_passed, dual_llm judge, capability validate, plugin scanner, HIPAA / legal / fintech vertical scanners, or asks "is X strategy actually wired" — read this plan first. The classifier OSS / ENTERPRISE / SPLIT in §3.2 is the source of truth for what goes where.

**Anti-pattern reminder (per charter):** never publish HIPAA PHI patterns / legal privilege regex / fintech AML rules to the OSS repo. Those live in `axon-enterprise` exclusively.

---

## 7. Target

- `axon-lang v1.15.0` (PyPI + crates.io, coordinated cross-stack)
- `axon-frontend v0.7.0` if any new IR fields added (currently no parser-level changes anticipated; revisit at 20.a)
- `axon-enterprise v1.7.0` (private repo) — vertical scanner catálogos + healthcare / legal / fintech ensemble configs
