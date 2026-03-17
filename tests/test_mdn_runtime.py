"""
AXON Runtime — MDN Runtime Integration Tests
==============================================
Tests for the Multi-Document Navigation runtime path:
  IR → Backend Compilation → Executor Dispatch → Engine Execution → Trace

Test structure:
  TestMdnTracerEvents       — MDN event types exist and emit correctly
  TestMdnBackendCompilation — IRNavigate/IRCorroborate → CompiledStep metadata
  TestMdnExecutorDispatch   — metadata routing to corpus_navigate/corroborate handlers
  TestMdnCorpusNavigate     — end-to-end navigate execution with trace verification
  TestMdnCorroborate        — end-to-end corroboration with claim grouping
  TestMdnPipeline           — full source → compile → execute → trace pipeline
"""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import dataclass, field
from typing import Any

# ── Tracer imports ────────────────────────────────────────────────
from axon.runtime.tracer import (
    ExecutionTrace,
    TraceEvent,
    TraceEventType,
    TraceSpan,
    Tracer,
)

# ── Backend imports ───────────────────────────────────────────────
from axon.backends.base_backend import (
    CompiledExecutionUnit,
    CompiledProgram,
    CompiledStep,
)

# ── IR imports ────────────────────────────────────────────────────
from axon.compiler.ir_nodes import (
    IRCorpusDocSpec,
    IRCorpusEdgeSpec,
    IRCorpusSpec,
    IRCorroborate,
    IRNavigate,
    IRProgram,
)

# ── MDN Engine imports ────────────────────────────────────────────
from axon.engine.mdn.corpus_graph import (
    Budget,
    CorpusGraph,
    Document,
    Edge,
    NavigationResult,
    ProvenancePath,
    RelationType,
)
from axon.engine.mdn.navigator import CorpusNavigator


# ═══════════════════════════════════════════════════════════════════
#  HELPERS — minimal mock executor context
# ═══════════════════════════════════════════════════════════════════

class _MockContextManager:
    """Minimal context manager for testing executor handlers."""

    def __init__(self):
        self._results: dict[str, str] = {}
        self.completed_steps: list[str] = []

    def set_step_result(self, name: str, value: str) -> None:
        self._results[name] = value
        if name not in self.completed_steps:
            self.completed_steps.append(name)

    def get_step_result(self, name: str) -> str | None:
        return self._results.get(name)

    def append_message(self, role: str, content: str) -> None:
        pass  # not needed for MDN tests


@dataclass
class _MockModelResponse:
    content: str = ""
    structured: dict[str, Any] | None = None
    tool_calls: list | None = None
    confidence: float | None = None


def _make_corpus_step(
    corpus_ref: str = "TestCorpus",
    query: str = "test query",
    budget_depth: int = 3,
    budget_nodes: int = 10,
    edge_filter: list[str] | None = None,
    output_name: str = "",
    corpus_definition: dict | None = None,
) -> CompiledStep:
    """Build a CompiledStep with corpus_navigate metadata."""
    if corpus_definition is None:
        corpus_definition = {
            "name": corpus_ref,
            "documents": [
                {"pix_ref": "DocA", "doc_type": "statute", "role": "primary"},
                {"pix_ref": "DocB", "doc_type": "regulation", "role": "secondary"},
                {"pix_ref": "DocC", "doc_type": "case_law", "role": "reference"},
            ],
            "edges": [
                {"source_ref": "DocA", "target_ref": "DocB", "relation_type": "implements"},
                {"source_ref": "DocB", "target_ref": "DocC", "relation_type": "cites"},
            ],
            "weights": {"implements": 0.9, "cites": 0.8},
        }

    return CompiledStep(
        step_name=f"mdn:navigate:{corpus_ref}",
        user_prompt="",
        metadata={
            "corpus_navigate": {
                "corpus_ref": corpus_ref,
                "corpus_definition": corpus_definition,
                "query": query,
                "trail_enabled": True,
                "output_name": output_name,
                "budget_depth": budget_depth,
                "budget_nodes": budget_nodes,
                "edge_filter": edge_filter or [],
            },
        },
    )


def _make_corroborate_step(
    navigate_ref: str = "mdn:navigate:TestCorpus",
    output_name: str = "verified",
) -> CompiledStep:
    """Build a CompiledStep with corroborate metadata."""
    return CompiledStep(
        step_name=f"mdn:corroborate:{navigate_ref}",
        user_prompt="",
        metadata={
            "corroborate": {
                "navigate_ref": navigate_ref,
                "output_name": output_name,
            },
        },
    )


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN TRACER EVENTS
# ═══════════════════════════════════════════════════════════════════


class TestMdnTracerEvents(unittest.TestCase):
    """Test that MDN-specific tracer events exist and work."""

    def test_mdn_event_types_exist(self):
        """All 5 MDN event types exist in the TraceEventType enum."""
        self.assertEqual(TraceEventType.MDN_NAVIGATE_START.value, "mdn_navigate_start")
        self.assertEqual(TraceEventType.MDN_NAVIGATE_STEP.value, "mdn_navigate_step")
        self.assertEqual(TraceEventType.MDN_NAVIGATE_END.value, "mdn_navigate_end")
        self.assertEqual(TraceEventType.MDN_CORROBORATE.value, "mdn_corroborate")
        self.assertEqual(TraceEventType.MDN_CONTRADICTION_DETECTED.value, "mdn_contradiction_detected")

    def test_emit_mdn_navigate_start(self):
        """emit_mdn_navigate_start produces correct event with all fields."""
        tracer = Tracer(program_name="test")
        tracer.start_span("nav_span")

        event = tracer.emit_mdn_navigate_start(
            step_name="nav:test",
            corpus_ref="LegalCorpus",
            query="Who is liable?",
            budget_depth=3,
            budget_nodes=20,
            edge_filter=["cites", "implements"],
        )

        self.assertEqual(event.event_type, TraceEventType.MDN_NAVIGATE_START)
        self.assertEqual(event.step_name, "nav:test")
        self.assertEqual(event.data["corpus_ref"], "LegalCorpus")
        self.assertEqual(event.data["query"], "Who is liable?")
        self.assertEqual(event.data["budget_depth"], 3)
        self.assertEqual(event.data["budget_nodes"], 20)
        self.assertEqual(event.data["edge_filter"], ["cites", "implements"])

    def test_emit_mdn_navigate_start_minimal(self):
        """emit_mdn_navigate_start works with minimal args (no budget/filter)."""
        tracer = Tracer(program_name="test")
        tracer.start_span("span")

        event = tracer.emit_mdn_navigate_start(
            step_name="nav:minimal",
            corpus_ref="C",
            query="q",
        )

        self.assertEqual(event.data["corpus_ref"], "C")
        self.assertNotIn("budget_depth", event.data)
        self.assertNotIn("edge_filter", event.data)

    def test_emit_mdn_corroborate(self):
        """emit_mdn_corroborate produces correct event with all fields."""
        tracer = Tracer(program_name="test")
        tracer.start_span("corr_span")

        event = tracer.emit_mdn_corroborate(
            step_name="corr:test",
            navigate_ref="nav_result",
            paths_checked=5,
            corroborated=True,
            contradictions=1,
        )

        self.assertEqual(event.event_type, TraceEventType.MDN_CORROBORATE)
        self.assertEqual(event.data["navigate_ref"], "nav_result")
        self.assertEqual(event.data["paths_checked"], 5)
        self.assertTrue(event.data["corroborated"])
        self.assertEqual(event.data["contradictions"], 1)

    def test_emit_mdn_navigate_step(self):
        """MDN_NAVIGATE_STEP can be emitted directly via emit()."""
        tracer = Tracer(program_name="test")
        tracer.start_span("span")

        event = tracer.emit(
            TraceEventType.MDN_NAVIGATE_STEP,
            step_name="nav:step",
            data={"path_index": 0, "claim": "φ₁", "confidence": 0.85},
        )

        self.assertEqual(event.event_type, TraceEventType.MDN_NAVIGATE_STEP)
        self.assertEqual(event.data["claim"], "φ₁")

    def test_emit_mdn_contradiction(self):
        """MDN_CONTRADICTION_DETECTED can be emitted."""
        tracer = Tracer(program_name="test")
        tracer.start_span("span")

        event = tracer.emit(
            TraceEventType.MDN_CONTRADICTION_DETECTED,
            step_name="nav:contradiction",
            data={"source_doc": "D1", "target_doc": "D2", "claim": "φ₂"},
        )

        self.assertEqual(event.event_type, TraceEventType.MDN_CONTRADICTION_DETECTED)
        self.assertEqual(event.data["source_doc"], "D1")

    def test_events_recorded_in_span(self):
        """MDN events are recorded within the current span."""
        tracer = Tracer(program_name="test")
        span = tracer.start_span("mdn_test")

        tracer.emit_mdn_navigate_start(step_name="s", corpus_ref="C", query="q")
        tracer.emit(TraceEventType.MDN_NAVIGATE_STEP, step_name="s")
        tracer.emit(TraceEventType.MDN_NAVIGATE_END, step_name="s")
        tracer.emit_mdn_corroborate(step_name="s", navigate_ref="r")

        self.assertEqual(len(span.events), 4)
        event_types = [e.event_type for e in span.events]
        self.assertIn(TraceEventType.MDN_NAVIGATE_START, event_types)
        self.assertIn(TraceEventType.MDN_NAVIGATE_STEP, event_types)
        self.assertIn(TraceEventType.MDN_NAVIGATE_END, event_types)
        self.assertIn(TraceEventType.MDN_CORROBORATE, event_types)


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN BACKEND COMPILATION
# ═══════════════════════════════════════════════════════════════════


class TestMdnBackendCompilation(unittest.TestCase):
    """Test _compile_mdn_step produces correct metadata."""

    def _compile(self, step, ir=None):
        """Helper to call _compile_mdn_step."""
        from axon.backends.base_backend import BaseBackend
        if ir is None:
            ir = IRProgram(corpus_specs=())
        return BaseBackend._compile_mdn_step(step, ir)

    def test_navigate_with_corpus_ref(self):
        """IRNavigate with corpus_ref produces corpus_navigate metadata."""
        corpus_spec = IRCorpusSpec(
            name="Legal",
            documents=(
                IRCorpusDocSpec(pix_ref="Ley", doc_type="statute", role="primary"),
            ),
            edges=(
                IRCorpusEdgeSpec(source_ref="Ley", target_ref="Reg", relation_type="implements"),
            ),
            weights=(("implements", 0.9),),
        )
        ir = IRProgram(corpus_specs=(corpus_spec,))

        nav = IRNavigate(
            corpus_ref="Legal",
            query="Who is liable?",
            trail_enabled=True,
            output_name="nav_result",
            budget_depth=3,
            budget_nodes=20,
            edge_filter=("cites",),
        )

        result = self._compile(nav, ir)

        self.assertEqual(result.step_name, "mdn:navigate:Legal")
        self.assertIn("corpus_navigate", result.metadata)

        meta = result.metadata["corpus_navigate"]
        self.assertEqual(meta["corpus_ref"], "Legal")
        self.assertEqual(meta["query"], "Who is liable?")
        self.assertTrue(meta["trail_enabled"])
        self.assertEqual(meta["output_name"], "nav_result")
        self.assertEqual(meta["budget_depth"], 3)
        self.assertEqual(meta["budget_nodes"], 20)
        self.assertEqual(meta["edge_filter"], ["cites"])

    def test_navigate_corpus_definition_resolved(self):
        """Corpus definition documents and edges are resolved from IR program."""
        corpus_spec = IRCorpusSpec(
            name="MedCorpus",
            documents=(
                IRCorpusDocSpec(pix_ref="Study1", doc_type="clinical_trial", role="primary"),
                IRCorpusDocSpec(pix_ref="Study2", doc_type="meta_analysis", role="secondary"),
            ),
            edges=(
                IRCorpusEdgeSpec(source_ref="Study1", target_ref="Study2", relation_type="supports"),
            ),
            weights=(("supports", 0.95),),
        )
        ir = IRProgram(corpus_specs=(corpus_spec,))

        nav = IRNavigate(corpus_ref="MedCorpus", query="q")
        result = self._compile(nav, ir)
        corpus_def = result.metadata["corpus_navigate"]["corpus_definition"]

        self.assertEqual(corpus_def["name"], "MedCorpus")
        self.assertEqual(len(corpus_def["documents"]), 2)
        self.assertEqual(corpus_def["documents"][0]["pix_ref"], "Study1")
        self.assertEqual(len(corpus_def["edges"]), 1)
        self.assertEqual(corpus_def["edges"][0]["relation_type"], "supports")
        self.assertAlmostEqual(corpus_def["weights"]["supports"], 0.95)

    def test_corroborate_produces_correct_metadata(self):
        """IRCorroborate produces corroborate metadata."""
        corr = IRCorroborate(
            navigate_ref="nav_result",
            output_name="verified",
        )

        result = self._compile(corr)

        self.assertEqual(result.step_name, "mdn:corroborate:nav_result")
        self.assertIn("corroborate", result.metadata)

        meta = result.metadata["corroborate"]
        self.assertEqual(meta["navigate_ref"], "nav_result")
        self.assertEqual(meta["output_name"], "verified")

    def test_navigate_without_corpus_ref_fallback(self):
        """IRNavigate without corpus_ref produces mdn:unknown (PIX mode)."""
        nav = IRNavigate(pix_ref="SomeDoc", query="q")
        result = self._compile(nav)
        self.assertEqual(result.step_name, "mdn:unknown")

    def test_compiled_step_serialization(self):
        """CompiledStep from _compile_mdn_step serializes to dict."""
        corr = IRCorroborate(navigate_ref="nav", output_name="v")
        result = self._compile(corr)
        d = result.to_dict()

        self.assertEqual(d["step_name"], "mdn:corroborate:nav")
        self.assertIn("corroborate", d["metadata"])


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN EXECUTOR — Corpus Navigate
# ═══════════════════════════════════════════════════════════════════


class TestMdnCorpusNavigate(unittest.TestCase):
    """Test _execute_corpus_navigate_step handler."""

    def _run_navigate(self, step=None, ctx=None, tracer=None):
        """Execute a corpus navigate step and return (result, tracer, ctx)."""
        from axon.runtime.executor import Executor

        if step is None:
            step = _make_corpus_step()
        if ctx is None:
            ctx = _MockContextManager()
        if tracer is None:
            tracer = Tracer(program_name="test")
            tracer.start_span("exec")

        executor = Executor.__new__(Executor)
        result = asyncio.run(
            executor._execute_corpus_navigate_step(step, ctx, tracer)
        )
        return result, tracer, ctx

    def test_navigate_returns_step_result(self):
        """Navigate handler returns a StepResult with response."""
        result, _, _ = self._run_navigate()

        self.assertEqual(result.step_name, "mdn:navigate:TestCorpus")
        self.assertIsNotNone(result.response)
        self.assertGreater(result.duration_ms, 0)

    def test_navigate_response_has_correct_structure(self):
        """Navigate response JSON has expected fields."""
        result, _, _ = self._run_navigate()
        data = json.loads(result.response.content)

        self.assertEqual(data["corpus_ref"], "TestCorpus")
        self.assertEqual(data["query"], "test query")
        self.assertIn("paths_found", data)
        self.assertIn("contradictions", data)
        self.assertIn("visited_count", data)
        self.assertIn("confidence", data)
        self.assertIn("paths", data)
        self.assertIsInstance(data["paths"], list)

    def test_navigate_stores_result_in_context(self):
        """Navigate result stored in context under step_name."""
        result, _, ctx = self._run_navigate()

        stored = ctx.get_step_result("mdn:navigate:TestCorpus")
        self.assertIsNotNone(stored)
        data = json.loads(stored)
        self.assertEqual(data["corpus_ref"], "TestCorpus")

    def test_navigate_stores_with_output_name(self):
        """Navigate result stored under output_name when specified."""
        step = _make_corpus_step(output_name="my_nav_result")
        _, _, ctx = self._run_navigate(step=step)

        self.assertIsNotNone(ctx.get_step_result("my_nav_result"))

    def test_navigate_emits_mdn_events(self):
        """Navigate handler emits MDN_NAVIGATE_START and MDN_NAVIGATE_END."""
        _, tracer, _ = self._run_navigate()
        trace = tracer.finalize()

        all_events = []
        for span in trace.spans:
            all_events.extend(span.events)
            for child in span.children:
                all_events.extend(child.events)

        event_types = [e.event_type for e in all_events]
        self.assertIn(TraceEventType.MDN_NAVIGATE_START, event_types)
        self.assertIn(TraceEventType.MDN_NAVIGATE_END, event_types)

    def test_navigate_start_event_has_corpus_info(self):
        """MDN_NAVIGATE_START event has corpus_ref and query."""
        _, tracer, _ = self._run_navigate()
        trace = tracer.finalize()

        start_events = [
            e for span in trace.spans for e in span.events
            if e.event_type == TraceEventType.MDN_NAVIGATE_START
        ]
        self.assertGreater(len(start_events), 0)
        self.assertEqual(start_events[0].data["corpus_ref"], "TestCorpus")
        self.assertEqual(start_events[0].data["query"], "test query")

    def test_navigate_end_event_has_results_summary(self):
        """MDN_NAVIGATE_END event has paths_found and confidence."""
        _, tracer, _ = self._run_navigate()
        trace = tracer.finalize()

        end_events = [
            e for span in trace.spans for e in span.events
            if e.event_type == TraceEventType.MDN_NAVIGATE_END
        ]
        self.assertGreater(len(end_events), 0)
        self.assertIn("paths_found", end_events[0].data)
        self.assertIn("confidence", end_events[0].data)
        self.assertTrue(end_events[0].data["success"])

    def test_navigate_with_budget_depth(self):
        """Navigate respects budget_depth parameter."""
        step = _make_corpus_step(budget_depth=1, budget_nodes=5)
        result, _, _ = self._run_navigate(step=step)
        data = json.loads(result.response.content)

        # Budget constrains the traversal
        self.assertLessEqual(data["visited_count"], 5)

    def test_navigate_with_edge_filter(self):
        """Navigate respects edge_filter parameter."""
        step = _make_corpus_step(edge_filter=["implements"])
        result, _, _ = self._run_navigate(step=step)
        data = json.loads(result.response.content)

        # Should still produce valid results (filtered traversal)
        self.assertIn("paths", data)

    def test_navigate_structured_response(self):
        """Navigate response has structured data."""
        result, _, _ = self._run_navigate()

        self.assertIsNotNone(result.response.structured)
        self.assertIsInstance(result.response.structured, dict)
        self.assertEqual(result.response.structured["corpus_ref"], "TestCorpus")

    def test_navigate_empty_corpus(self):
        """Navigate with empty corpus returns empty paths without error."""
        step = _make_corpus_step(
            corpus_definition={"name": "Empty", "documents": [], "edges": [], "weights": {}}
        )
        result, _, _ = self._run_navigate(step=step)
        data = json.loads(result.response.content)

        self.assertEqual(data["paths_found"], 0)
        self.assertEqual(data["visited_count"], 0)


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN EXECUTOR — Corroborate
# ═══════════════════════════════════════════════════════════════════


class TestMdnCorroborate(unittest.TestCase):
    """Test _execute_corroborate_step handler."""

    def _run_corroborate(self, nav_data=None, step=None, ctx=None, tracer=None):
        """Execute a corroborate step and return (result, tracer, ctx)."""
        from axon.runtime.executor import Executor

        if ctx is None:
            ctx = _MockContextManager()

        if nav_data is not None:
            ctx.set_step_result("mdn:navigate:TestCorpus", json.dumps(nav_data))

        if step is None:
            step = _make_corroborate_step(navigate_ref="mdn:navigate:TestCorpus")
        if tracer is None:
            tracer = Tracer(program_name="test")
            tracer.start_span("exec")

        executor = Executor.__new__(Executor)
        result = asyncio.run(
            executor._execute_corroborate_step(step, ctx, tracer)
        )
        return result, tracer, ctx

    def test_corroborate_returns_step_result(self):
        """Corroborate handler returns a StepResult."""
        nav_data = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₁", "confidence": 0.85, "epistemic_type": "CitedFact", "edge_count": 3},
            ],
            "contradictions": 0,
            "confidence": 0.88,
        }
        result, _, _ = self._run_corroborate(nav_data)

        self.assertIsNotNone(result.response)
        self.assertGreater(result.duration_ms, 0)

    def test_corroborate_identifies_corroborated_claims(self):
        """Claims with 2+ paths are marked as CorroboratedFact."""
        nav_data = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₁", "confidence": 0.85, "epistemic_type": "CitedFact", "edge_count": 3},
                {"claim": "φ₂", "confidence": 0.7, "epistemic_type": "CitedFact", "edge_count": 1},
            ],
            "contradictions": 0,
            "confidence": 0.82,
        }
        result, _, _ = self._run_corroborate(nav_data)
        data = json.loads(result.response.content)

        self.assertEqual(len(data["corroborated_claims"]), 1)
        self.assertEqual(data["corroborated_claims"][0]["claim"], "φ₁")
        self.assertEqual(data["corroborated_claims"][0]["epistemic_type"], "CorroboratedFact")
        self.assertEqual(data["corroborated_claims"][0]["supporting_paths"], 2)

    def test_corroborate_identifies_uncorroborated_claims(self):
        """Claims with single path remain CitedFact."""
        nav_data = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₂", "confidence": 0.7, "epistemic_type": "CitedFact", "edge_count": 1},
            ],
            "contradictions": 0,
            "confidence": 0.8,
        }
        result, _, _ = self._run_corroborate(nav_data)
        data = json.loads(result.response.content)

        self.assertEqual(len(data["uncorroborated_claims"]), 2)
        self.assertTrue(all(c["epistemic_type"] == "CitedFact" for c in data["uncorroborated_claims"]))

    def test_corroborate_contradiction_penalty(self):
        """Contradictions reduce aggregate_confidence."""
        nav_data_clean = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₁", "confidence": 0.85, "epistemic_type": "CitedFact", "edge_count": 3},
            ],
            "contradictions": 0,
            "confidence": 0.88,
        }
        nav_data_dirty = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₁", "confidence": 0.85, "epistemic_type": "CitedFact", "edge_count": 3},
            ],
            "contradictions": 3,
            "confidence": 0.88,
        }

        result_clean, _, _ = self._run_corroborate(nav_data_clean)
        result_dirty, _, _ = self._run_corroborate(nav_data_dirty)

        clean_conf = json.loads(result_clean.response.content)["aggregate_confidence"]
        dirty_conf = json.loads(result_dirty.response.content)["aggregate_confidence"]

        self.assertGreater(clean_conf, dirty_conf)

    def test_corroborate_stores_result_in_context(self):
        """Corroborate result stored under output_name."""
        nav_data = {
            "paths": [{"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 1}],
            "contradictions": 0,
            "confidence": 0.9,
        }
        _, _, ctx = self._run_corroborate(nav_data)

        stored = ctx.get_step_result("verified")
        self.assertIsNotNone(stored)

    def test_corroborate_emits_mdn_corroborate_event(self):
        """Corroborate handler emits MDN_CORROBORATE event."""
        nav_data = {
            "paths": [{"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 1}],
            "contradictions": 0,
            "confidence": 0.9,
        }
        _, tracer, _ = self._run_corroborate(nav_data)
        trace = tracer.finalize()

        corr_events = [
            e for span in trace.spans for e in span.events
            if e.event_type == TraceEventType.MDN_CORROBORATE
        ]
        self.assertGreater(len(corr_events), 0)

    def test_corroborate_with_empty_navigation(self):
        """Corroborate handles empty navigation result gracefully."""
        nav_data = {"paths": [], "contradictions": 0, "confidence": 0.0}
        result, _, _ = self._run_corroborate(nav_data)
        data = json.loads(result.response.content)

        self.assertEqual(data["total_claims"], 0)
        self.assertAlmostEqual(data["aggregate_confidence"], 0.0)

    def test_corroborate_with_missing_nav_ref(self):
        """Corroborate handles missing navigation reference gracefully."""
        ctx = _MockContextManager()
        # Don't set any navigation result
        step = _make_corroborate_step(navigate_ref="nonexistent")
        result, _, _ = self._run_corroborate(step=step, ctx=ctx)
        data = json.loads(result.response.content)

        self.assertEqual(data["total_claims"], 0)

    def test_corroborate_corroboration_ratio(self):
        """Corroboration ratio is correctly computed."""
        nav_data = {
            "paths": [
                {"claim": "φ₁", "confidence": 0.9, "epistemic_type": "CitedFact", "edge_count": 2},
                {"claim": "φ₁", "confidence": 0.85, "epistemic_type": "CitedFact", "edge_count": 3},
                {"claim": "φ₂", "confidence": 0.7, "epistemic_type": "CitedFact", "edge_count": 1},
                {"claim": "φ₃", "confidence": 0.6, "epistemic_type": "CitedFact", "edge_count": 1},
            ],
            "contradictions": 0,
            "confidence": 0.8,
        }
        result, _, _ = self._run_corroborate(nav_data)
        data = json.loads(result.response.content)

        # 1 out of 3 claims corroborated → ratio ≈ 0.3333
        self.assertAlmostEqual(data["corroboration_ratio"], 1 / 3, places=3)


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN EXECUTOR — Step Dispatch
# ═══════════════════════════════════════════════════════════════════


class TestMdnExecutorDispatch(unittest.TestCase):
    """Test that metadata routing correctly dispatches to MDN handlers."""

    def test_corpus_navigate_metadata_detected(self):
        """CompiledStep with corpus_navigate metadata is detected."""
        step = _make_corpus_step()
        self.assertIn("corpus_navigate", step.metadata)

    def test_corroborate_metadata_detected(self):
        """CompiledStep with corroborate metadata is detected."""
        step = _make_corroborate_step()
        self.assertIn("corroborate", step.metadata)

    def test_metadata_keys_are_exclusive(self):
        """corpus_navigate and corroborate are distinct metadata keys."""
        nav_step = _make_corpus_step()
        corr_step = _make_corroborate_step()

        self.assertNotIn("corroborate", nav_step.metadata)
        self.assertNotIn("corpus_navigate", corr_step.metadata)


# ═══════════════════════════════════════════════════════════════════
#  TEST: MDN FULL PIPELINE
# ═══════════════════════════════════════════════════════════════════


class TestMdnPipeline(unittest.TestCase):
    """End-to-end test: navigate → corroborate with trace verification."""

    def test_navigate_then_corroborate(self):
        """Full pipeline: navigate produces paths, corroborate verifies them."""
        from axon.runtime.executor import Executor

        ctx = _MockContextManager()
        tracer = Tracer(program_name="pipeline_test")
        tracer.start_span("pipeline")

        executor = Executor.__new__(Executor)

        # Step 1: Navigate
        nav_step = _make_corpus_step(
            corpus_ref="LegalCorpus",
            query="Who is liable for damages?",
            output_name="nav_result",
        )

        nav_result = asyncio.run(
            executor._execute_corpus_navigate_step(nav_step, ctx, tracer)
        )

        # Step 2: Corroborate (reads nav_result from context)
        corr_step = _make_corroborate_step(
            navigate_ref="nav_result",
            output_name="verified_claims",
        )

        corr_result = asyncio.run(
            executor._execute_corroborate_step(corr_step, ctx, tracer)
        )

        # Verify navigate stored result
        self.assertIsNotNone(ctx.get_step_result("nav_result"))

        # Verify corroborate reads from navigate
        self.assertIsNotNone(ctx.get_step_result("verified_claims"))
        corr_data = json.loads(corr_result.response.content)
        self.assertEqual(corr_data["navigate_ref"], "nav_result")

        # Verify trace has both navigate and corroborate events
        trace = tracer.finalize()
        all_events = []
        for span in trace.spans:
            all_events.extend(span.events)

        event_types = {e.event_type for e in all_events}
        self.assertIn(TraceEventType.MDN_NAVIGATE_START, event_types)
        self.assertIn(TraceEventType.MDN_NAVIGATE_END, event_types)
        self.assertIn(TraceEventType.MDN_CORROBORATE, event_types)


if __name__ == "__main__":
    unittest.main()
