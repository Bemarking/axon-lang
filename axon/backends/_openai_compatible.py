"""Shared compilation primitives for OpenAI Chat Completions-compatible backends.

A growing set of providers expose an OpenAI-compatible Chat Completions
endpoint (`POST /v1/chat/completions` with the same request/response
shape): OpenAI itself, Moonshot Kimi, Zhipu GLM (v4 endpoint), Ollama
(local), OpenRouter (multi-provider gateway), and many others. They
differ in:

  - Base URL (provider-specific)
  - Default model identifiers
  - Auth header format (typically Bearer)
  - Tool-call edge cases (older Ollama models lack function calling)

…but the **prompt structure** the compiler must emit is identical:
``[{role: "system", content: ...}, {role: "user", content: ...}]``
with optional ``tools: [{type: "function", function: {name, description,
parameters}}]``.

This module supplies that shared compilation surface as a private base
class. The five v1.16.0 backends (OpenAI, Kimi, GLM, Ollama, OpenRouter)
inherit from ``OpenAICompatibleBackend`` and override only the
``name`` property + provider-specific quirks. Per Fase 22 D1, each
backend remains its own publicly-importable module — adopters never see
this base class — so registry semantics, file boundaries, and
provider-specific docstring discoverability stay intact.

The Anthropic and Gemini backends do NOT inherit from this — their
prompt structures differ enough (system field outside messages array,
``input_schema`` vs ``parameters``, etc.) that mixing would force
branches everywhere. Keeping them as siblings preserves the clarity of
the compilation pipeline.
"""

from __future__ import annotations

from typing import Any

from axon.backends.base_backend import (
    BaseBackend,
    CompilationContext,
    CompiledStep,
)
from axon.compiler.ir_nodes import (
    IRAnchor,
    IRContext,
    IRIntent,
    IRNode,
    IRPersona,
    IRProbe,
    IRReason,
    IRStep,
    IRToolSpec,
    IRWeave,
)


class OpenAICompatibleBackend(BaseBackend):
    """Compilation primitives shared by every OpenAI Chat Completions-shape backend.

    Subclasses MUST override ``name``. Subclasses MAY override
    ``compile_tool_spec`` to disable tools (e.g., older Ollama models
    that don't support function calling) or ``_persona_directive`` to
    tune system-prompt voice for the target model family.
    """

    # ── Required overrides ───────────────────────────────────────────

    @property
    def name(self) -> str:  # noqa: D401 — abstract; concrete subclass supplies
        raise NotImplementedError(
            "OpenAICompatibleBackend subclasses MUST override .name"
        )

    # ── System prompt compilation ────────────────────────────────────

    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        """Produce the string that becomes the ``system`` role message.

        Structure mirrors what every Chat Completions API expects:
        identity → context → constraints, separated by blank lines so
        the model parses the sections distinctly.
        """
        sections: list[str] = []
        if persona is not None:
            sections.append(self._persona_directive(persona))
        if context is not None:
            sections.append(self._context_directive(context))
        if anchors:
            sections.append(self._anchor_directive(anchors))
        return "\n\n".join(sections)

    def _persona_directive(self, persona: IRPersona) -> str:
        lines: list[str] = [f"You are {persona.name}."]
        if persona.description:
            lines.append(persona.description)
        if persona.domain:
            lines.append(f"Areas of expertise: {', '.join(persona.domain)}.")
        if persona.tone:
            lines.append(f"Communication tone: {persona.tone}.")
        if persona.language:
            lines.append(f"Respond in: {persona.language}.")
        if persona.confidence_threshold is not None:
            lines.append(
                "Only assert claims you are at least "
                f"{persona.confidence_threshold:.0%} confident about."
            )
        if persona.cite_sources:
            lines.append("Always cite your sources.")
        if persona.refuse_if:
            lines.append(
                "Refuse to engage if: " + "; ".join(persona.refuse_if) + "."
            )
        return "\n".join(lines)

    def _context_directive(self, context: IRContext) -> str:
        lines: list[str] = ["[SESSION CONFIGURATION]"]
        depth_map = {
            "shallow": "Concise, high-level responses.",
            "standard": "Balanced, moderately detailed responses.",
            "deep": "Thorough, detailed analysis.",
            "exhaustive": (
                "Exhaustive analysis covering all angles. "
                "Leave nothing unexamined."
            ),
        }
        if context.depth:
            lines.append(
                "  Depth: "
                + depth_map.get(context.depth, f"Analysis depth: {context.depth}.")
            )
        if context.language:
            lines.append(f"  Language: {context.language}")
        if context.max_tokens is not None:
            lines.append(f"  Target response length: ~{context.max_tokens} tokens")
        if context.cite_sources:
            lines.append("  Citation required: yes")
        return "\n".join(lines)

    def _anchor_directive(self, anchors: list[IRAnchor]) -> str:
        lines: list[str] = [
            "[HARD CONSTRAINTS — NON-NEGOTIABLE]",
            "",
        ]
        for i, anchor in enumerate(anchors, 1):
            lines.append(f"CONSTRAINT {i}: {anchor.name}")
            if anchor.require:
                lines.append(f"  → MUST: {anchor.require}")
            if anchor.reject:
                lines.append(f"  → MUST NOT: {', '.join(anchor.reject)}")
            if anchor.enforce:
                lines.append(f"  → ENFORCE: {anchor.enforce}")
            if anchor.confidence_floor is not None:
                lines.append(
                    f"  → MIN CONFIDENCE: {anchor.confidence_floor:.0%}"
                )
            if anchor.unknown_response:
                lines.append(
                    f'  → WHEN UNCERTAIN, respond with: "{anchor.unknown_response}"'
                )
            lines.append("")
        return "\n".join(lines).rstrip()

    # ── Step compilation ─────────────────────────────────────────────

    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        """Dispatch to the right specialised compiler for the IR node type."""
        if isinstance(step, IRStep):
            return self._compile_named_step(step, context)
        if isinstance(step, IRIntent):
            return self._compile_intent(step)
        if isinstance(step, IRProbe):
            return self._compile_probe(step)
        if isinstance(step, IRReason):
            return self._compile_reason(step)
        if isinstance(step, IRWeave):
            return self._compile_weave(step)
        return CompiledStep(
            step_name=getattr(step, "name", step.node_type),
            user_prompt=f"[{step.node_type}] Execute this operation.",
        )

    def _compile_named_step(
        self, step: IRStep, context: CompilationContext
    ) -> CompiledStep:
        prompt_parts: list[str] = []
        if step.given:
            prompt_parts.append(f"Given the input: {step.given}")
        if step.probe is not None:
            prompt_parts.append(self._format_probe(step.probe))
        elif step.reason is not None:
            prompt_parts.append(self._format_reason(step.reason))
        elif step.weave is not None:
            prompt_parts.append(self._format_weave(step.weave))
        elif step.ask:
            prompt_parts.append(step.ask)
        if step.output_type:
            prompt_parts.append(
                f"\nYour output MUST conform to the type: {step.output_type}"
            )
        if step.confidence_floor is not None:
            prompt_parts.append(
                f"\nMinimum confidence required: {step.confidence_floor:.0%}. "
                "If you cannot meet this threshold, indicate uncertainty."
            )

        tool_decls: list[dict[str, Any]] = []
        if step.use_tool is not None:
            tool_name = step.use_tool.tool_name
            if tool_name in context.tools:
                tool_decls.append(self.compile_tool_spec(context.tools[tool_name]))
            argument_str = (
                f" with: {step.use_tool.argument}"
                if step.use_tool.argument
                else ""
            )
            prompt_parts.append(
                f"\nUse the tool '{step.use_tool.tool_name}'{argument_str}"
            )

        return CompiledStep(
            step_name=step.name,
            user_prompt="\n".join(prompt_parts),
            tool_declarations=tool_decls,
            metadata={"ir_node_type": "step"},
        )

    def _compile_intent(self, intent: IRIntent) -> CompiledStep:
        parts: list[str] = []
        if intent.given:
            parts.append(f"Given: {intent.given}")
        parts.append(intent.ask)
        if intent.output_type_name:
            type_str = intent.output_type_name
            if intent.output_type_generic:
                type_str += f"<{intent.output_type_generic}>"
            if intent.output_type_optional:
                type_str += " (may be null)"
            parts.append(f"\nExpected output type: {type_str}")
        if intent.confidence_floor is not None:
            parts.append(f"\nMinimum confidence: {intent.confidence_floor:.0%}")
        return CompiledStep(
            step_name=intent.name,
            user_prompt="\n".join(parts),
            metadata={"ir_node_type": "intent"},
        )

    def _compile_probe(self, probe: IRProbe) -> CompiledStep:
        fields_str = ", ".join(probe.fields)
        prompt = (
            f"Analyze the following and extract these specific fields: "
            f"[{fields_str}]\n\nSource: {probe.target}\n\n"
            f"Return the results as a structured JSON object with exactly "
            f"these keys: {fields_str}. If a field cannot be determined, "
            f"set its value to null."
        )
        return CompiledStep(
            step_name=f"probe_{probe.target}",
            user_prompt=prompt,
            output_schema={
                "type": "object",
                "properties": {f: {"type": "string"} for f in probe.fields},
                "required": list(probe.fields),
            },
            metadata={"ir_node_type": "probe"},
        )

    def _compile_reason(self, reason: IRReason) -> CompiledStep:
        parts: list[str] = []
        if reason.about:
            parts.append(f"Reason carefully about: {reason.about}")
        if reason.given:
            parts.append(f"Based on: {', '.join(reason.given)}")
        if reason.ask:
            parts.append(f"\n{reason.ask}")
        if reason.depth > 1:
            parts.append(
                f"\nPerform {reason.depth} levels of analysis, "
                "each building on the previous."
            )
        if reason.show_work or reason.chain_of_thought:
            parts.append(
                "\nShow your complete reasoning step by step. "
                "Make your chain of thought explicit and traceable."
            )
        if reason.output_type:
            parts.append(f"\nFinal output must conform to type: {reason.output_type}")
        return CompiledStep(
            step_name=reason.name or f"reason_{reason.about}",
            user_prompt="\n".join(parts),
            metadata={
                "ir_node_type": "reason",
                "depth": reason.depth,
                "show_work": reason.show_work,
            },
        )

    def _compile_weave(self, weave: IRWeave) -> CompiledStep:
        parts: list[str] = [
            f"Synthesize the following sources into a coherent result: "
            f"[{', '.join(weave.sources)}]"
        ]
        if weave.target:
            parts.append(f"\nTarget output: {weave.target}")
        if weave.format_type:
            parts.append(f"Output format: {weave.format_type}")
        if weave.priority:
            parts.append(
                f"Priority ordering (address first to last): "
                + " → ".join(weave.priority)
            )
        if weave.style:
            parts.append(f"Style: {weave.style}")
        return CompiledStep(
            step_name=f"weave_{weave.target}" if weave.target else "weave",
            user_prompt="\n".join(parts),
            metadata={"ir_node_type": "weave"},
        )

    # ── Tool spec compilation (OpenAI function format) ───────────────

    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        """Produce the OpenAI Chat Completions function/tool format.

        Shape: ``{"type": "function", "function": {"name", "description",
        "parameters": JSONSchema}}`` — accepted verbatim by every
        OpenAI-compatible provider that supports tool calling.
        """
        properties: dict[str, Any] = {
            "query": {
                "type": "string",
                "description": f"The input query for {tool.name}",
            }
        }
        if tool.max_results is not None:
            properties["max_results"] = {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": tool.max_results,
            }
        desc_parts: list[str] = [f"External tool: {tool.name}"]
        if tool.provider:
            desc_parts.append(f"Provider: {tool.provider}")
        if tool.timeout:
            desc_parts.append(f"Timeout: {tool.timeout}")
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": ". ".join(desc_parts),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": ["query"],
                },
            },
        }

    # ── Agent BDI prompt ─────────────────────────────────────────────

    def compile_agent_system_prompt(
        self,
        agent_name: str,
        goal: str,
        strategy: str,
        tools: list[str],
        epistemic_state: str,
        iteration: int,
        max_iterations: int,
    ) -> str:
        """Build a BDI-cycle system prompt tuned for OpenAI-shape models.

        The structure (Identity → Epistemic State → Strategy → Tools →
        Budget) follows the same convention as the Anthropic backend so
        downstream telemetry / trace shape stays consistent across
        provider switches.
        """
        parts: list[str] = [
            f"You are Agent {agent_name}, an autonomous cognitive entity "
            "operating on BDI (Belief-Desire-Intention) architecture.",
            f"Your singular objective: {goal}",
        ]
        lattice_map = {
            "doubt": "LOW CONFIDENCE — treat all information as uncertain, verify before acting",
            "speculate": "EMERGING — some evidence gathered, hypotheses forming",
            "believe": "CONVERGENT — strong evidence supports your conclusions",
            "know": "TERMINAL — sufficient certainty achieved, ready to finalize",
        }
        state_desc = lattice_map.get(epistemic_state, f"UNKNOWN ({epistemic_state})")
        parts.append(
            f"\n[EPISTEMIC STATE]\nCurrent: {epistemic_state} — {state_desc}\n"
            "Tarski lattice: doubt ⊏ speculate ⊏ believe ⊏ know\n"
            "Advance along this lattice toward convergence."
        )
        parts.append(self._strategy_protocol(strategy))
        if tools:
            parts.append(
                f"\n[AVAILABLE TOOLS]\nYou have access to: {', '.join(tools)}\n"
                "Use tools deliberately — each invocation consumes budget. "
                "Prefer the most direct tool for your current sub-goal."
            )
        remaining = max_iterations - iteration
        parts.append(
            f"\n[CONVERGENCE BUDGET]\nCycle: {iteration + 1} of {max_iterations}\n"
            f"Remaining: {remaining}\n"
            "You MUST converge within the remaining budget. "
            "If you cannot make progress, report it explicitly."
        )
        return "\n".join(parts)

    def _strategy_protocol(self, strategy: str) -> str:
        if strategy == "react":
            return (
                "\n[STRATEGY: ReAct]\n"
                "Loop: 1) THOUGHT — analyze beliefs, 2) ACTION — tool call or "
                "reasoning, 3) OBSERVATION — process result. "
                "Repeat until epistemic state ≥ believe."
            )
        if strategy == "reflexion":
            return (
                "\n[STRATEGY: Reflexion]\n"
                "ReAct + self-critique: 1) THOUGHT, 2) ACTION, 3) OBSERVATION, "
                "4) CRITIQUE — evaluate own reasoning, identify gaps, "
                "5) REVISION — adjust approach. Critique is mandatory before "
                "advancing epistemic state."
            )
        if strategy == "plan_and_execute":
            return (
                "\n[STRATEGY: Plan-and-Execute]\n"
                "PHASE 1 PLANNING: generate complete numbered action plan. "
                "PHASE 2 EXECUTION: execute sequentially, verify each step. "
                "Re-plan if reality diverges."
            )
        return (
            f"\n[STRATEGY: {strategy}]\n"
            f"Execute using the '{strategy}' deliberation protocol. "
            "Follow the body steps defined in the agent block."
        )

    # ── Internal formatting helpers ──────────────────────────────────

    def _format_probe(self, probe: IRProbe) -> str:
        return (
            f"Extract the following from {probe.target}: "
            f"[{', '.join(probe.fields)}]\n"
            "Return structured results for each field."
        )

    def _format_reason(self, reason: IRReason) -> str:
        parts: list[str] = []
        if reason.about:
            parts.append(f"Reason about: {reason.about}")
        if reason.ask:
            parts.append(reason.ask)
        if reason.show_work:
            parts.append("Show your complete reasoning process.")
        return "\n".join(parts)

    def _format_weave(self, weave: IRWeave) -> str:
        text = (
            f"Synthesize [{', '.join(weave.sources)}] into "
            f"{weave.target or 'a coherent result'}"
        )
        if weave.priority:
            text += f" prioritizing: {', '.join(weave.priority)}"
        return text
