---
title: "Plan vivo: Fase 22 — Native multi-provider backend coverage"
status: DRAFTED 2026-05-08 — sub-fases 22.a–22.f pendientes; target axon-lang v1.16.0 (next minor)
owner: AXON Language Team
created: 2026-05-08
updated: 2026-05-08
target: axon-lang v1.16.0 (PyPI + crates.io); axon-enterprise lockstep version-only bump
depends_on: Fase 20 SHIPPED (Production Shield Runtime); Fase 21 SHIPPED (Integration Surface enterprise)
---

## ▶ Status snapshot (2026-05-08 — DRAFTED)

| Sub-phase | Status | LOC target | Module(s) / Notes |
|---|---|---|---|
| 22.a Kimi (Moonshot) native backend — **PRIORITY** | ⏳ NEXT | ~600 | `axon/backends/kimi_backend.py` (nuevo) + register + tests |
| 22.b GLM (Zhipu /智谱AI) native backend — **PRIORITY** | ⏳ pending | ~600 | `axon/backends/glm_backend.py` (nuevo) + register + tests |
| 22.c OpenAI backend — **complete the stub** | ⏳ pending | ~525 | `axon/backends/openai_backend.py` (currently 85 LOC stub raising `NotImplementedError`) |
| 22.d Ollama backend — **complete the stub** | ⏳ pending | ~520 | `axon/backends/ollama_backend.py` (currently 90 LOC stub) |
| 22.e OpenRouter native backend (multi-provider gateway) | ⏳ pending | ~500 | `axon/backends/openrouter_backend.py` — single dep with model routing across providers |
| 22.f Cross-backend integration test pack + drift gate | ⏳ pending | ~300 | `tests/test_backend_parity.py` — same flow compiled against every backend, asserts IR-shape parity + sane response shape per provider |

**Acceptance metrics target:**

- **`get_backend("kimi")` and `get_backend("glm")` return live instances** that compile axon IR end-to-end and execute against their respective provider APIs without raising `NotImplementedError`.
- **`get_backend("openai")` and `get_backend("ollama")` no longer raise `NotImplementedError`** — the false-advertising gap (registered but unusable) closes alongside the new additions.
- **≥80 new tests** total: unit per backend (compilation correctness against IR fixtures) + integration smoke (live provider call gated behind env var) + cross-backend parity (drift gate).
- **Drift gate**: `BACKEND_REGISTRY` contents match the documented backend list in this plan + each registered class implements every `BaseBackend` abstract method without raising. Catches any future backend that registers as a stub.
- **Documentation**: `README.md` backend matrix updated with the full list, install commands per backend (`pip install axon-lang[kimi]`, etc.), and required env vars per provider.

## How to apply (post-SHIPPED)

When the user mentions Kimi, Moonshot, GLM, Zhipu, OpenRouter, OpenAI, Ollama, or "switching backends" — answer with the registry shape after Fase 22: 7 native backends, each compile-and-execute through their provider's native SDK, no stubs in the registry. Pre-Fase-22 only `anthropic` and `gemini` were live; the other registry entries either threw `NotImplementedError` or didn't exist. Fase 22 closes the gap.

---

# FASE 22 — NATIVE MULTI-PROVIDER BACKEND COVERAGE

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** Brings axon-lang's documented 7-backend matrix to reality. Pre-Fase-22, `BACKEND_REGISTRY` advertised 4 backends but only 2 (`anthropic`, `gemini`) were full implementations — `openai` and `ollama` were 85-90 LOC stubs raising `NotImplementedError`. Three additional backends from the original product spec (`kimi`, `glm`, `openrouter`) were missing entirely. Fase 22 ships full native implementations for all five gaps.
- **Why:** Adopter-agnostic backend coverage was a v1.0 product promise. Running a flow against `kimi` returning `ValueError: Unknown backend 'kimi'` is worse than no advertisement; `openai` raising `NotImplementedError` mid-execution is worst-case (looks supported, dies in production). Honest registry alignment is overdue.
- **Priority order:** 22.a (Kimi) and 22.b (GLM) ship first — explicit user request, currently no path to use those providers natively. 22.c (OpenAI completion) and 22.d (Ollama completion) close the false-advertising gap. 22.e (OpenRouter) is the multi-provider gateway, deferred until 22.a–d demonstrate the per-backend pattern is solid. 22.f drift gate ensures the registry never falls back to a stub silently.
- **Robustness target:** every backend implementation includes (a) live integration test gated behind `AXON_KIMI_API_KEY` / equivalent env var for skip-on-missing-credentials, (b) IR-shape parity across all backends via the cross-backend test pack, (c) registry contract tests that fail loudly if any registered class has a method raising `NotImplementedError`.

---

## 2. Audit findings — qué hay vs qué se prometió

Inspección empírica de master post-v1.15.4:

### 2.1 BACKEND_REGISTRY actual

[`axon/backends/__init__.py`](axon/backends/__init__.py):

```python
BACKEND_REGISTRY: dict[str, type[BaseBackend]] = {
    "anthropic": AnthropicBackend,
    "gemini": GeminiBackend,
    "openai": OpenAIBackend,
    "ollama": OllamaBackend,
}
```

### 2.2 Implementación real vs registry

| Backend | LOC del archivo | Estado |
|---|---|---|
| `anthropic` | 613 | ✅ Full implementation |
| `gemini` | 619 | ✅ Full implementation |
| `openai` | 85 | ⚠️ **STUB** — class extends `BaseBackend`, every method raises `NotImplementedError` |
| `ollama` | 90 | ⚠️ **STUB** — same shape |

### 2.3 Backends esperados vs registrados

Lista de producto original: `KIMI, GLM, OPENROUTER, OLLAMA, ANTHROPIC, GEMINI, OPENAI` (7 providers).

| Provider | Registrado | Implementado |
|---|---|---|
| ANTHROPIC | ✅ | ✅ |
| GEMINI | ✅ | ✅ |
| OPENAI | ✅ | ⚠️ stub |
| OLLAMA | ✅ | ⚠️ stub |
| KIMI | ❌ | ❌ |
| GLM | ❌ | ❌ |
| OPENROUTER | ❌ | ❌ |

**Brecha total: 5 de 7 advertidos no funcionan en producción** (3 ausentes + 2 stubs).

### 2.4 Severidad

| Tipo de gap | Adopter experience | Severidad |
|---|---|---|
| Backend ausente del registry (`kimi`, `glm`, `openrouter`) | `ValueError: Unknown backend 'kimi'. Available: anthropic, gemini, ollama, openai` — claro, debuggable, pero bloquea uso | Alta |
| Backend registrado como stub (`openai`, `ollama`) | `NotImplementedError` mid-execution después de "compilar OK" — **silent compile-time pass, runtime explosion**, peor que el caso anterior | **Crítica** |

Los stubs son **strictly worse** que los ausentes: el typechecker + compile pipeline aceptan `backend = "openai"` sin queja, el adopter despliega a producción, el primer flow ejecuta y muere con `NotImplementedError`. Igual que los bugs de Fase 21 (kitchen door) y v1.15.4 (silent data corruption): falla silente que aparece en el peor momento.

---

## 3. Architecture — single contract, N implementations

### 3.1 BaseBackend contract (ya existe)

[`axon/backends/base_backend.py`](axon/backends/base_backend.py) (1679 LOC) define el contrato abstracto que todo backend debe satisfacer. Cada implementación:

1. Compila `IRProgram` → `CompiledProgram` (estructura provider-native: messages, tools, schemas).
2. Implementa `complete(step, ctx)` → `ModelResponse` con `content`, `structured`, `confidence`, `usage`.
3. Maneja errores transport (rate limits, timeouts, network) y los normaliza a `ModelCallError`.

### 3.2 Pattern shared por todos los backends nuevos

```
axon/backends/
├── base_backend.py             # contract (no change)
├── anthropic_backend.py        # full impl (no change)
├── gemini_backend.py           # full impl (no change)
├── openai_backend.py           # 22.c: complete the stub
├── ollama_backend.py           # 22.d: complete the stub
├── kimi_backend.py             # 22.a: NEW, ~600 LOC
├── glm_backend.py              # 22.b: NEW, ~600 LOC
└── openrouter_backend.py       # 22.e: NEW, ~500 LOC
```

Cada nuevo backend mirror la estructura de `anthropic_backend.py` (más completo + más reciente):
- `class XBackend(BaseBackend):` con `compile_program`, `compile_unit`, `compile_step`, `complete`
- Provider SDK como soft dep en `pyproject.toml [project.optional-dependencies]` (`pip install axon-lang[kimi]`)
- Env vars convencionales: `AXON_KIMI_API_KEY` / `AXON_GLM_API_KEY` / etc.
- Manejo de errores: rate limits → retry, timeouts → `ModelCallError` con context; mismo discipline que `anthropic_backend.py`.

### 3.3 Provider details per backend

#### 22.a — Kimi (Moonshot AI)

- **API**: OpenAI-compatible (`api.moonshot.cn/v1`); usa el SDK oficial `openai` con `base_url` apuntando a Moonshot.
- **Modelos**: `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k`, `kimi-latest`.
- **Context windows**: hasta 128k tokens (kimi-latest hasta 200k).
- **Strengths a documentar**: Chinese language excellence, long-context retrieval, function calling.
- **Auth**: Bearer API key.
- **Soft dep**: `openai>=1.0` (mismo SDK que 22.c — comparten dep, separar codepath).

#### 22.b — GLM (Zhipu AI / 智谱AI)

- **API**: ZhipuAI's native API (`open.bigmodel.cn/api/paas/v4`) o vía SDK `zhipuai`.
- **Modelos**: `glm-4-plus`, `glm-4-air`, `glm-4-airx`, `glm-4-flash` (free tier), `glm-4v` (vision).
- **Context windows**: hasta 128k.
- **Strengths a documentar**: Chinese reasoning, RAG-tuned variants, agentic flows.
- **Auth**: JWT-based (token = `api_key.expires_at`, signed).
- **Soft dep**: `zhipuai>=2.0`.

#### 22.c — OpenAI (complete the stub)

- **API**: Chat Completions + Responses API (más reciente, 2025).
- **Modelos**: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `o1`, `o1-mini`, `o3-mini`.
- **Strengths**: function calling maduro, JSON mode, structured outputs (schema-validated).
- **Auth**: Bearer API key.
- **Soft dep**: `openai>=1.0` (compartido con 22.a).
- **Reuso**: `kimi_backend.py` puede heredar/composer con `openai_backend.py` por el SDK común — TBD durante implementación.

#### 22.d — Ollama (complete the stub)

- **API**: Local HTTP (`http://localhost:11434/api/chat`).
- **Modelos**: cualquier modelo `ollama pull`-eado (llama3, mistral, qwen, etc.).
- **Strengths**: zero-network, on-prem, offline-capable, cero costo de API.
- **Auth**: ninguno (local).
- **Soft dep**: `httpx` (ya core dep) o el SDK `ollama-python`.
- **Manejo de errores**: detectar "Ollama no está corriendo" con error claro vs "modelo no descargado".

#### 22.e — OpenRouter (multi-provider gateway, deferred)

- **API**: `openrouter.ai/api/v1`, OpenAI-compatible.
- **Modelos**: 200+ modelos de todos los providers (Anthropic, OpenAI, Mistral, Cohere, etc.) por slug `provider/model-name`.
- **Strengths**: un solo billing + key, fallback chains, model routing por costo/latency.
- **Auth**: Bearer API key.
- **Soft dep**: `openai>=1.0` (compartido con 22.a y 22.c — todos OpenAI-API-shape).
- **Por qué deferred**: agrega complejidad de slug parsing (`anthropic/claude-3-5-sonnet` vs solo `claude-3-5-sonnet`); vale shipping primero los providers directos para que el patrón quede claro.

### 3.4 Cross-backend test pack (22.f)

Test que ejerce el mismo flow IR contra todos los backends registrados y asserta:

- Cada backend produce un `CompiledProgram` con la misma estructura IR-shape (sin pérdida de información).
- Cada backend acepta el mismo set de IR primitivas (Persona, Context, Anchor, Step, Tool).
- Live integration tests gated behind env vars: salen como `pytest.skip` cuando la API key no está, corren cuando está. Cada backend tiene 1-2 smoke tests live.
- **Drift gate**: introspección de `BACKEND_REGISTRY` — para cada `cls`, instancia, llama cada método del `BaseBackend` con args minimal, asserta que ningún método raise `NotImplementedError`. Si alguien agrega un nuevo backend stub al registry, falla CI loud and early. Esta es la red de seguridad estructural — la lección de v1.15.1/22.b extendida al backend layer.

---

## 4. Sub-fases — desglose, dependencies, classification

| # | Title | Classification | Depends on | Approximate scope |
|---|---|---|---|---|
| 22.a | Kimi (Moonshot) native backend | OSS | — | ~600 LOC backend + 20 unit tests + 2 live integration smoke + register in `__init__.py` |
| 22.b | GLM (Zhipu) native backend | OSS | — (parallel a 22.a) | ~600 LOC + 20 unit + 2 live smoke + register |
| 22.c | OpenAI — complete the stub | OSS | — | ~525 LOC reemplazando el stub + 20 unit + 2 live smoke (gated `OPENAI_API_KEY`) |
| 22.d | Ollama — complete the stub | OSS | — | ~520 LOC reemplazando stub + 15 unit + 1 live smoke (gated `OLLAMA_RUNNING=1`) |
| 22.e | OpenRouter native backend | OSS | 22.a + 22.c (OpenAI-shape pattern proven) | ~500 LOC + 15 unit + 2 live smoke (gated) |
| 22.f | Cross-backend test pack + drift gate | OSS | 22.a–22.d shipped | ~300 LOC test code; AST/registry introspection gates |

**Classification**: 100% OSS. axon-lang core, no enterprise-only behavior. axon-enterprise gets the new backends transparently via the same `BACKEND_REGISTRY`.

**Parallelisability**: 22.a + 22.b + 22.c + 22.d are independent; can ship in any order or in a single release. 22.e depends on the OpenAI-shape implementations being solid (Kimi, OpenAI both use the same SDK pattern). 22.f goes last so it gates the full set.

---

## 5. Decisions (D1–D7)

**D1 — Each backend native vs OpenAI-compat shim**

Kimi y OpenRouter exponen una OpenAI-compatible API — técnicamente podrían vivir como un solo `OpenAICompatibleBackend` parametrizado por base_url + auth. Decisión: **shipearlos como módulos separados** (`kimi_backend.py`, `openrouter_backend.py`). Razón: cada provider tiene quirks que se acumulan en la implementación (rate limit headers, error shape, model param names, tool format). Un wrapper genérico se vuelve un branch-fest. Compartir el SDK `openai` está bien; compartir el codepath completo no.

**D2 — Vendor SDKs vs httpx-direct**

Para cada backend usar el **SDK oficial del provider** cuando exista (`openai`, `zhipuai`, `anthropic`, `google-generativeai`). Razón: evita reimplementar retry/streaming/auth. Trade-off: dep adicional. Mitigación: cada SDK como `[project.optional-dependencies]` opcional, instalable como `pip install axon-lang[kimi]`. Adopters que no usan un provider no pagan el dep.

**D3 — Soft deps + skip-on-missing**

Cada backend `import`-ea su SDK lazy dentro de `__init__` o en el primer `complete()` call. `ImportError` se traduce a un `RuntimeError` con mensaje claro: `"Kimi backend requires 'openai' package. Install via: pip install axon-lang[kimi]"`. Esto preserva la importabilidad de `axon.backends` cuando un provider opcional no está instalado.

**D4 — Env var convention**

`AXON_<PROVIDER>_API_KEY` (e.g., `AXON_KIMI_API_KEY`, `AXON_GLM_API_KEY`). Documentado en cada `<provider>_backend.py` docstring + en el `INTEGRATION_GUIDE.md` y README. Razón: prefijo `AXON_` evita colisión con variables que el adopter ya tiene de otros usos del SDK (`OPENAI_API_KEY` de un script no-axon).

**D5 — Live integration tests gated**

Cada backend ships 1-2 tests que hacen llamada real al provider. Gated: `pytest.skip` si `AXON_<PROVIDER>_API_KEY` no está en env. CI corre los gated tests con secrets configured. Adopters corriendo `pytest tests/` sin keys ven los tests skipped, no failed. Smoke real catches API contract drift (provider cambia response shape, retiramos modelo, etc.).

**D6 — Stubs eliminados, no improved**

Para 22.c y 22.d, **borrar el stub completo** y reescribir desde cero a partir del template de `anthropic_backend.py`. Razón: los 85-90 LOC actuales son `NotImplementedError` shells, no hay lógica que rescatar. Reescribir es más limpio que diff-add.

**D7 — Versioning**

Fase 22 = next minor `axon-lang v1.16.0`. Razón: agregar backends es feature-add (additive, no breaking). Backends existentes siguen funcionando idénticos. Adopters que dependen de "openai exists in registry" ahora obtienen funcionalidad real en lugar de `NotImplementedError` — strict improvement, not breaking. axon-enterprise lockstep version-only bump.

---

## 6. Tests target — ≥80 nuevos

| Suite | File (proposed) | Tests | Coverage |
|---|---|---|---|
| Kimi unit | `tests/test_kimi_backend.py` | ~20 | compile IR shapes (Persona/Context/Anchor/Tool), prompt formatting, response parsing, rate-limit retry, error mapping |
| Kimi live (gated) | same file, `pytest.mark.live_kimi` | 2 | smoke completion + structured output via JSON mode |
| GLM unit | `tests/test_glm_backend.py` | ~20 | same coverage matrix |
| GLM live (gated) | same | 2 | smoke + tool call |
| OpenAI unit | `tests/test_openai_backend.py` | ~20 | covers function_call, JSON mode, structured outputs, o1 reasoning models |
| OpenAI live (gated) | same | 2 | smoke + structured |
| Ollama unit | `tests/test_ollama_backend.py` | ~15 | local HTTP shape, model-not-pulled error, ollama-not-running error |
| Ollama live (gated, requires `OLLAMA_RUNNING=1`) | same | 1 | smoke against local llama3 |
| Cross-backend parity | `tests/test_backend_parity.py` | ~10 | same IR → all backends compile without error, structurally similar shapes |
| Registry drift gate | same file | ~5 | every registered class has all `BaseBackend` abstract methods overridden + none raise `NotImplementedError` on minimal call |

**Total**: ~97 nuevos. Más cualquiera que surja durante implementación.

---

## 7. Drift gate / charter compliance

**Registry drift gate** (en `test_backend_parity.py`):

```python
def test_no_backend_in_registry_raises_not_implemented():
    """Every backend in BACKEND_REGISTRY must be live, not a stub.
    The pre-Fase-22 OpenAI/Ollama stubs were silent failures: they
    passed compilation, then raised NotImplementedError mid-execution.
    This gate prevents anyone from re-introducing the pattern."""
    for name, cls in BACKEND_REGISTRY.items():
        instance = cls()
        for method_name in BaseBackend.__abstractmethods__:
            method = getattr(instance, method_name)
            with pytest.raises(Exception) as exc_info:
                # Call with minimal valid args; whatever raises (including
                # provider auth errors) is fine — what we're catching is
                # specifically NotImplementedError.
                ...
            assert not isinstance(exc_info.value, NotImplementedError), (
                f"Backend {name!r} method {method_name!r} raises "
                f"NotImplementedError — stub regression detected. "
                f"Either implement the method or remove the registration."
            )
```

**Backend completeness gate**:

```python
def test_documented_backends_match_registry():
    """The backends documented in this fase plan must all be in the
    registry. Catches the inverse: shipping a Fase 22 release that
    forgets to register one of the new backends."""
    expected = {"anthropic", "gemini", "openai", "ollama", "kimi", "glm"}
    # OpenRouter optional — ships in 22.e, may lag.
    assert expected <= set(BACKEND_REGISTRY.keys()), (
        f"Missing from BACKEND_REGISTRY: {expected - set(BACKEND_REGISTRY.keys())}"
    )
```

---

## 8. Ship target

- **axon-lang v1.16.0** — minor bump (additive features, no breaking).
- **axon-enterprise lockstep version-only bump** — picks up the new backends transparently via the shared `BACKEND_REGISTRY`. No enterprise-side code changes needed.
- **Release workflow**: standard per `feedback_version_bump_ordering.md` — features ship first across all 22.a–f, version bump is the release commit at the end.
- **Documentation deliverables**:
  - `README.md` backend matrix updated (all 7 providers, install commands, env var conventions).
  - `axon-enterprise/docs/INTEGRATION_GUIDE.md` updated — adopters discover available backends via `/.well-known/axon-capabilities.json` once 22.f drift gate confirms the registry is honest.

---

## 9. Out of scope (para esta fase)

- **Streaming responses** — algunos providers stream tokens; soporte unificado de streaming es una fase separada (Fase 23+ candidate).
- **Multi-modal** — vision / audio / video. Anthropic + Gemini + GLM-4v ya soportan imágenes; unificar la API multi-modal es scope mayor.
- **Function calling unification** — cada provider tiene su shape de tool definition; un wrapper único para cualquier backend es trabajo de su propia fase.
- **Cost tracking / token accounting** — algunos backends devuelven usage metrics, otros no. Fase de observability.
- **Routing / fallback chains** — ya existe `MetaBackend` parcial; promoverlo a primary feature es trabajo aparte.

---

## 10. Summary table — 30-second decision support

| Question | Answer |
|---|---|
| ¿Es esto urgente? | **Alta para 22.a/b/c/d** (cierra la falsedad de registry). Media para 22.e (OpenRouter útil pero diferible). |
| ¿Toca axon-enterprise? | Solo version-only bump lockstep. Cero código nuevo del lado enterprise. |
| ¿Rompe algo existente? | **No.** Los 2 backends que sí funcionaban (`anthropic`, `gemini`) intactos. Los 2 stubs (`openai`, `ollama`) pasan de raise NotImplementedError → funcionar — strict improvement. Los 3 ausentes (`kimi`, `glm`, `openrouter`) son adición pura. |
| ¿Cuánto código nuevo? | ~3.4k LOC backends + ~97 tests + actualizaciones de docs. |
| ¿Qué desbloquea? | Adopters que querían usar Kimi/GLM nativamente pueden hacerlo. Adopters que pensaban que `openai`/`ollama` funcionaban dejan de descubrir el `NotImplementedError` en producción. Backend matrix honesta. |
| ¿Cuál es el primer commit? | 22.a — Kimi native backend (priority del usuario). Luego 22.b GLM. Luego 22.c/d para cerrar los stubs. 22.e diferido. 22.f como release commit final. |

---

**Próximo paso operacional**: confirmar prioridad + arrancar 22.a (Kimi native backend). Trabajo estimado: ~1.5 horas para 22.a sola, end-to-end (incluye tests + register + docs section). Sub-fases 22.b–d shipeadas después de 22.a en cadena.
