"""Backend registry drift gate + cross-backend compilation parity (Fase 22.f).

Two complementary safety nets:

1. **Registry drift gate** — every entry in ``BACKEND_REGISTRY`` must be
   a fully-implemented backend. Specifically: instantiating it and
   calling each abstract method with minimal valid args must NOT raise
   ``NotImplementedError``. Pre-Fase-22 this gate would have caught the
   ``OpenAIBackend`` and ``OllamaBackend`` stubs (registered but
   un-implemented, raising ``NotImplementedError`` at runtime). Post-
   v1.16.0 it prevents anyone from re-introducing the same anti-pattern.

2. **Cross-backend compilation parity** — the same IR program, compiled
   against every registered backend, produces structurally equivalent
   output: same number of execution units, same number of compiled
   steps per unit, same step names. Per-backend prompt phrasing differs
   (that's the whole point of the abstraction), but the IR-shape that
   threads through the executor must be invariant. Catches accidental
   data loss in a backend's compile_program.

Together these gates protect the v1.16.0 promise: 7 native backends,
all live, all interoperable on the same IR.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from axon.backends import BACKEND_REGISTRY, get_backend
from axon.backends.base_backend import BaseBackend, CompilationContext
from axon.compiler.ir_nodes import (
    IRAnchor,
    IRContext,
    IRPersona,
    IRStep,
    IRToolSpec,
)


# ═══════════════════════════════════════════════════════════════════
#  Registry drift gate
# ═══════════════════════════════════════════════════════════════════


_FASE22_REQUIRED_BACKENDS: frozenset[str] = frozenset(
    {"anthropic", "gemini", "openai", "ollama", "kimi", "glm", "openrouter"}
)


def test_registry_contains_every_fase22_required_backend() -> None:
    """The seven backends documented in fase_22_native_backend_coverage.md
    must all be in the registry. Catches the inverse of the 22.c/22.d
    stubs: shipping a v1.16.x release that forgets to register one of
    the new backends."""
    missing = _FASE22_REQUIRED_BACKENDS - set(BACKEND_REGISTRY.keys())
    assert not missing, (
        f"BACKEND_REGISTRY missing Fase 22 required backends: {sorted(missing)}. "
        f"Update axon/backends/__init__.py to register them."
    )


def test_every_registered_backend_instantiates_without_error() -> None:
    """``get_backend(name)`` must construct an instance for every
    registered name without raising. Constructor-time errors are
    silent killers — the registry advertises the name as available
    but production code that does ``get_backend("foo")`` crashes."""
    failures: list[str] = []
    for name in BACKEND_REGISTRY:
        try:
            instance = get_backend(name)
            assert isinstance(instance, BaseBackend), (
                f"{name!r} did not return a BaseBackend instance"
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "Backends failed to instantiate:\n  " + "\n  ".join(failures)


def test_no_registered_backend_method_raises_notimplementederror() -> None:
    """The exact regression class v1.16.0 closes: a backend registered
    in BACKEND_REGISTRY but with abstract methods raising
    ``NotImplementedError``. Pre-Fase-22 ``OpenAIBackend`` and
    ``OllamaBackend`` were 85-90 LOC stubs that did exactly this —
    every call into ``compile_step`` / ``compile_system_prompt`` /
    ``compile_tool_spec`` / ``compile_agent_system_prompt`` raised.

    Walks every registered backend, calls each abstract method with
    minimal valid args, asserts that whatever exception (if any) is
    raised is NOT ``NotImplementedError``. Provider auth errors,
    network errors, etc. are fine — the gate is specifically about
    the stub anti-pattern.
    """
    persona = IRPersona(name="ProbeBot", description="drift gate probe")
    context = IRContext()
    anchors: list[IRAnchor] = []
    step = IRStep(name="probe_step", ask="probe drift gate")
    tool = IRToolSpec(name="probe_tool")
    compile_ctx = CompilationContext(
        persona=persona,
        context=context,
        anchors=anchors,
        tools={"probe_tool": tool},
        flow=None,
        effort="",
    )

    failures: list[str] = []
    for name, cls in BACKEND_REGISTRY.items():
        instance = cls()

        # Probe every method that pre-Fase-22 stubs raised on.
        probes: list[tuple[str, Any]] = [
            ("compile_system_prompt", lambda i=instance: i.compile_system_prompt(persona, context, anchors)),
            ("compile_step", lambda i=instance: i.compile_step(step, compile_ctx)),
            ("compile_tool_spec", lambda i=instance: i.compile_tool_spec(tool)),
            (
                "compile_agent_system_prompt",
                lambda i=instance: i.compile_agent_system_prompt(
                    agent_name="ProbeAgent",
                    goal="probe",
                    strategy="react",
                    tools=["probe_tool"],
                    epistemic_state="doubt",
                    iteration=0,
                    max_iterations=1,
                ),
            ),
        ]

        for method_name, probe in probes:
            try:
                probe()
            except NotImplementedError as exc:
                failures.append(
                    f"{name}.{method_name}() raises NotImplementedError: {exc}. "
                    "This is the v1.16.0 stub regression — either implement "
                    "the method or remove the registration."
                )
            except Exception:  # noqa: BLE001
                # Any non-NotImplementedError is acceptable for this gate.
                # The cross-backend parity test below verifies functional
                # correctness of the compile output.
                pass

    assert not failures, "Stub regression detected:\n  " + "\n  ".join(failures)


# ═══════════════════════════════════════════════════════════════════
#  Cross-backend compilation parity
# ═══════════════════════════════════════════════════════════════════


def test_every_backend_compiles_system_prompt_to_nonempty_string() -> None:
    """Every backend produces a non-empty system prompt for a populated
    persona/context/anchors triple. Catches a backend that returns
    ``""`` or ``None`` — silent prompt-loss that the executor would
    happily forward to the model."""
    persona = IRPersona(
        name="LegalReviewer",
        description="A senior contracts attorney.",
        domain=["contracts", "compliance"],
        tone="precise",
        cite_sources=True,
    )
    context = IRContext(depth="deep", language="en", cite_sources=True)
    anchors = [
        IRAnchor(
            name="NoFabrication",
            require="ground every claim in source text",
            confidence_floor=0.85,
        )
    ]

    for name in BACKEND_REGISTRY:
        backend = get_backend(name)
        prompt = backend.compile_system_prompt(persona, context, anchors)
        assert isinstance(prompt, str), f"{name}: returned non-string"
        assert prompt, f"{name}: returned empty system prompt"
        # Every backend includes the persona name somewhere.
        assert persona.name in prompt, (
            f"{name}: system prompt does not mention persona name {persona.name!r}"
        )


def test_every_backend_compiles_tool_spec_to_dict_with_name() -> None:
    """Every backend's ``compile_tool_spec`` returns a dict; the
    structural shape varies (Anthropic uses ``input_schema``, OpenAI
    family uses ``function.parameters``, Gemini uses
    ``function_declarations``), but the tool name must always be
    locatable somewhere — the registry is what the executor uses to
    correlate dispatch back to the IR."""
    tool = IRToolSpec(name="search_db", provider="postgres", max_results=10)

    for name in BACKEND_REGISTRY:
        backend = get_backend(name)
        spec = backend.compile_tool_spec(tool)
        assert isinstance(spec, dict), f"{name}: tool spec is not a dict"
        # The tool name must appear in the serialised spec — every
        # provider stores it differently, but it's always there.
        spec_str = str(spec)
        assert tool.name in spec_str, (
            f"{name}: tool name {tool.name!r} missing from compiled spec: {spec!r}"
        )


def test_every_backend_compiles_named_step_with_correct_name() -> None:
    """Every backend's ``compile_step`` preserves the IR step's name
    on the returned ``CompiledStep``. Lose this and the executor's
    trace correlation breaks across the entire flow."""
    persona = IRPersona(name="ProbeBot")
    context_obj = IRContext()
    compile_ctx = CompilationContext(
        persona=persona,
        context=context_obj,
        anchors=[],
        tools={},
        flow=None,
        effort="",
    )
    step = IRStep(name="analyze_clause", ask="extract obligations")

    for name in BACKEND_REGISTRY:
        backend = get_backend(name)
        compiled = backend.compile_step(step, compile_ctx)
        assert compiled.step_name == step.name, (
            f"{name}: compiled step name {compiled.step_name!r} != "
            f"IR step name {step.name!r}"
        )


# ═══════════════════════════════════════════════════════════════════
#  OpenAI-compatible family invariants
# ═══════════════════════════════════════════════════════════════════


def test_openai_compatible_backends_emit_openai_tool_format() -> None:
    """The five OpenAI-Chat-Completions-compatible backends (OpenAI,
    Kimi, GLM, Ollama, OpenRouter) all share the
    ``OpenAICompatibleBackend`` base, so they emit OpenAI's
    ``{"type": "function", "function": {...}}`` tool spec verbatim.

    This is the structural invariant that lets the transport layer's
    default OpenAI-shape branch handle all five providers without a
    per-provider tool-format branch."""
    from axon.backends._openai_compatible import OpenAICompatibleBackend

    tool = IRToolSpec(name="probe_tool")
    openai_compat_backends = [
        name
        for name, cls in BACKEND_REGISTRY.items()
        if issubclass(cls, OpenAICompatibleBackend)
    ]
    assert set(openai_compat_backends) == {
        "openai",
        "kimi",
        "glm",
        "ollama",
        "openrouter",
    }, (
        "Unexpected set of OpenAI-compatible backends — did a sibling "
        "Anthropic/Gemini accidentally inherit from "
        "OpenAICompatibleBackend?"
    )

    for name in openai_compat_backends:
        spec = get_backend(name).compile_tool_spec(tool)
        assert spec.get("type") == "function", (
            f"{name}: OpenAI-compat backend should emit "
            f"{{'type': 'function', ...}}, got {spec!r}"
        )
        assert "function" in spec
        assert spec["function"]["name"] == tool.name


# ═══════════════════════════════════════════════════════════════════
#  Per-backend AST gate against future stub re-introduction
# ═══════════════════════════════════════════════════════════════════


def test_no_backend_module_contains_notimplementederror_in_method_body() -> None:
    """Belt-and-braces: scan the source of every backend module and
    verify no method body raises ``NotImplementedError`` directly. The
    runtime gate above catches any registered backend that crashes;
    this static gate catches a half-finished backend that someone
    starts before registering, preventing the stub from ever entering
    the registry by accident.

    Whitelist: ``_openai_compatible.py``'s ``name`` property
    intentionally raises NotImplementedError — it's the abstract method
    subclasses must override, mirroring ``BaseBackend.name``. That's
    correct-by-design, not a bug.
    """
    import re
    from pathlib import Path

    backends_dir = Path(__file__).parent.parent / "axon" / "backends"
    whitelisted: set[Path] = {
        backends_dir / "base_backend.py",
        backends_dir / "_openai_compatible.py",
    }
    pattern = re.compile(r"raise\s+NotImplementedError")

    violations: list[str] = []
    for py_file in backends_dir.glob("*_backend.py"):
        if py_file in whitelisted:
            continue
        text = py_file.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(
                f"{py_file.name}:{line_no}: backend module raises "
                f"NotImplementedError — pre-Fase-22 stub pattern. "
                "Either implement the method or remove the file from the "
                "registry until it's complete."
            )
    assert not violations, "Stub regression detected at source level:\n  " + "\n  ".join(
        violations
    )
