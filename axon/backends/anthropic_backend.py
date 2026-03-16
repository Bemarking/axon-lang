"""
AXON Backends — Anthropic (Claude) Backend
============================================
Compiles AXON IR into Claude-native prompt structures.

This backend produces prompts optimized for the Claude model family:
  - System prompts with persona identity and anchor enforcement
  - User messages with structured instructions
  - Tool use declarations in Claude's native format
  - Chain-of-thought via extended thinking patterns
  - Structured extraction via JSON output schemas

The output is ready for consumption by the Anthropic Messages API
(Phase 3 Runtime will handle actual HTTP calls).
"""

from __future__ import annotations

from typing import Any

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
from axon.backends.base_backend import (
    BaseBackend,
    CompiledStep,
    CompilationContext,
)


class AnthropicBackend(BaseBackend):
    """
    Compiles AXON IR to Claude-native prompt structures.

    Produces output compatible with the Anthropic Messages API:
      - system: persona + anchors + context configuration
      - messages: [{role: "user", content: ...}]
      - tools: [{name, description, input_schema}]
    """

    @property
    def name(self) -> str:
        return "anthropic"

    # ═══════════════════════════════════════════════════════════════
    #  SYSTEM PROMPT COMPILATION
    # ═══════════════════════════════════════════════════════════════

    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        """
        Build a Claude system prompt from persona, context, and anchors.

        Structure:
          1. Persona identity block
          2. Context configuration block
          3. Anchor enforcement block (hard constraints)
        """
        sections: list[str] = []

        # — Persona identity —
        if persona is not None:
            sections.append(self._compile_persona_block(persona))

        # — Context configuration —
        if context is not None:
            sections.append(self._compile_context_block(context))

        # — Anchor enforcement (Anchor Enforcer injection point) —
        if anchors:
            sections.append(self._compile_anchor_block(anchors))

        return "\n\n".join(sections)

    def _compile_persona_block(self, persona: IRPersona) -> str:
        """Compile persona into a Claude identity block."""
        lines: list[str] = [f"You are {persona.name}."]

        if persona.description:
            lines.append(persona.description)

        if persona.domain:
            domain_str = ", ".join(persona.domain)
            lines.append(f"Your areas of expertise: {domain_str}.")

        if persona.tone:
            lines.append(f"Communication tone: {persona.tone}.")

        if persona.language:
            lines.append(f"Respond in: {persona.language}.")

        if persona.confidence_threshold is not None:
            lines.append(
                f"Only provide claims you are at least "
                f"{persona.confidence_threshold:.0%} confident about."
            )

        if persona.cite_sources:
            lines.append("Always cite your sources.")

        if persona.refuse_if:
            refuse_str = "; ".join(persona.refuse_if)
            lines.append(f"Refuse to engage if: {refuse_str}.")

        return "\n".join(lines)

    def _compile_context_block(self, context: IRContext) -> str:
        """Compile context into session configuration instructions."""
        lines: list[str] = ["[SESSION CONFIGURATION]"]

        if context.depth:
            depth_map = {
                "shallow": "Provide concise, high-level responses.",
                "standard": "Provide balanced, moderately detailed responses.",
                "deep": "Provide thorough, detailed analysis.",
                "exhaustive": (
                    "Provide exhaustive analysis covering all angles. "
                    "Leave nothing unexamined."
                ),
            }
            instruction = depth_map.get(
                context.depth,
                f"Analysis depth: {context.depth}.",
            )
            lines.append(f"  Depth: {instruction}")

        if context.language:
            lines.append(f"  Language: {context.language}")

        if context.max_tokens is not None:
            lines.append(
                f"  Target response length: ~{context.max_tokens} tokens"
            )

        if context.cite_sources:
            lines.append("  Citation required: yes")

        return "\n".join(lines)

    def _compile_anchor_block(self, anchors: list[IRAnchor]) -> str:
        """
        Compile anchors into hard constraint instructions.

        These are formatted as non-negotiable rules that Claude
        must follow in every response. Uses imperative language
        designed for maximum compliance.
        """
        lines: list[str] = [
            "[HARD CONSTRAINTS — THESE RULES ARE ABSOLUTE AND NON-NEGOTIABLE]",
            "",
        ]

        for i, anchor in enumerate(anchors, 1):
            lines.append(f"CONSTRAINT {i}: {anchor.name}")

            if anchor.require:
                lines.append(f"  → You MUST: {anchor.require}")
            if anchor.reject:
                reject_str = ", ".join(anchor.reject)
                lines.append(f"  → You MUST NOT: {reject_str}")
            if anchor.enforce:
                lines.append(f"  → ENFORCE: {anchor.enforce}")
            if anchor.confidence_floor is not None:
                lines.append(
                    f"  → MINIMUM CONFIDENCE: {anchor.confidence_floor:.0%} — "
                    f"below this threshold, do not make the claim."
                )
            if anchor.unknown_response:
                lines.append(
                    f"  → WHEN UNCERTAIN, respond exactly with: "
                    f'"{anchor.unknown_response}"'
                )
            lines.append("")

        return "\n".join(lines).rstrip()

    # ═══════════════════════════════════════════════════════════════
    #  STEP COMPILATION
    # ═══════════════════════════════════════════════════════════════

    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        """
        Compile an IR step into a Claude-optimized prompt.

        Dispatches to specialized compilers based on the step type
        and its contained cognitive operations.
        """
        if isinstance(step, IRStep):
            return self._compile_step_node(step, context)
        if isinstance(step, IRIntent):
            return self._compile_intent(step, context)
        if isinstance(step, IRProbe):
            return self._compile_probe(step, context)
        if isinstance(step, IRReason):
            return self._compile_reason(step, context)
        if isinstance(step, IRWeave):
            return self._compile_weave(step, context)

        # Fallback for other IR node types
        return CompiledStep(
            step_name=getattr(step, "name", step.node_type),
            user_prompt=f"[{step.node_type}] Execute this operation.",
        )

    def _compile_step_node(
        self, step: IRStep, context: CompilationContext
    ) -> CompiledStep:
        """Compile a named cognitive step."""
        prompt_parts: list[str] = []

        # Given (input binding)
        if step.given:
            prompt_parts.append(f"Given the input: {step.given}")

        # Embedded cognitive operations
        if step.probe is not None:
            probe_prompt = self._format_probe(step.probe)
            prompt_parts.append(probe_prompt)
        elif step.reason is not None:
            reason_prompt = self._format_reason(step.reason)
            prompt_parts.append(reason_prompt)
        elif step.weave is not None:
            weave_prompt = self._format_weave(step.weave)
            prompt_parts.append(weave_prompt)
        elif step.ask:
            prompt_parts.append(step.ask)

        # Output type expectation
        if step.output_type:
            prompt_parts.append(
                f"\nYour output MUST conform to the type: {step.output_type}"
            )

        # Confidence floor
        if step.confidence_floor is not None:
            prompt_parts.append(
                f"\nMinimum confidence required: "
                f"{step.confidence_floor:.0%}. "
                f"If you cannot meet this threshold, indicate uncertainty."
            )

        # Tool declarations for this step
        tool_decls: list[dict[str, Any]] = []
        if step.use_tool is not None:
            tool_name = step.use_tool.tool_name
            if tool_name in context.tools:
                tool_decls.append(
                    self.compile_tool_spec(context.tools[tool_name])
                )
            prompt_parts.append(
                f"\nUse the tool '{step.use_tool.tool_name}'"
                + (
                    f" with: {step.use_tool.argument}"
                    if step.use_tool.argument
                    else ""
                )
            )

        return CompiledStep(
            step_name=step.name,
            user_prompt="\n".join(prompt_parts),
            tool_declarations=tool_decls,
            metadata={"ir_node_type": "step"},
        )

    def _compile_intent(
        self, intent: IRIntent, context: CompilationContext
    ) -> CompiledStep:
        """Compile an atomic semantic instruction."""
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
            parts.append(
                f"\nMinimum confidence: {intent.confidence_floor:.0%}"
            )

        return CompiledStep(
            step_name=intent.name,
            user_prompt="\n".join(parts),
            metadata={"ir_node_type": "intent"},
        )

    def _compile_probe(
        self, probe: IRProbe, context: CompilationContext
    ) -> CompiledStep:
        """Compile a structured extraction directive."""
        fields_str = ", ".join(probe.fields)
        prompt = (
            f"Analyze the following and extract these specific fields: "
            f"[{fields_str}]\n\n"
            f"Source: {probe.target}\n\n"
            f"Return the results as a structured JSON object with "
            f"exactly these keys: {fields_str}. "
            f"If a field cannot be determined, set its value to null."
        )

        return CompiledStep(
            step_name=f"probe_{probe.target}",
            user_prompt=prompt,
            output_schema={
                "type": "object",
                "properties": {
                    f: {"type": "string"} for f in probe.fields
                },
                "required": list(probe.fields),
            },
            metadata={"ir_node_type": "probe"},
        )

    def _compile_reason(
        self, reason: IRReason, context: CompilationContext
    ) -> CompiledStep:
        """Compile a chain-of-thought reasoning directive."""
        parts: list[str] = []

        # Frame the reasoning task
        if reason.about:
            parts.append(f"Reason carefully about: {reason.about}")

        if reason.given:
            given_str = ", ".join(reason.given)
            parts.append(f"Based on: {given_str}")

        if reason.ask:
            parts.append(f"\n{reason.ask}")

        # Depth and work-showing configuration
        if reason.depth > 1:
            parts.append(
                f"\nPerform {reason.depth} levels of analysis, "
                f"each building on the previous."
            )

        if reason.show_work or reason.chain_of_thought:
            parts.append(
                "\nShow your complete reasoning process step by step. "
                "Make your chain of thought explicit and traceable."
            )

        if reason.output_type:
            parts.append(
                f"\nFinal output must conform to type: {reason.output_type}"
            )

        return CompiledStep(
            step_name=reason.name or f"reason_{reason.about}",
            user_prompt="\n".join(parts),
            metadata={
                "ir_node_type": "reason",
                "depth": reason.depth,
                "show_work": reason.show_work,
            },
        )

    def _compile_weave(
        self, weave: IRWeave, context: CompilationContext
    ) -> CompiledStep:
        """Compile a semantic synthesis directive."""
        sources_str = ", ".join(weave.sources)
        parts: list[str] = [
            f"Synthesize the following sources into a coherent result: "
            f"[{sources_str}]"
        ]

        if weave.target:
            parts.append(f"\nTarget output: {weave.target}")

        if weave.format_type:
            parts.append(f"Output format: {weave.format_type}")

        if weave.priority:
            priority_str = " → ".join(weave.priority)
            parts.append(
                f"Priority ordering (address first to last): {priority_str}"
            )

        if weave.style:
            parts.append(f"Style: {weave.style}")

        return CompiledStep(
            step_name=f"weave_{weave.target}" if weave.target else "weave",
            user_prompt="\n".join(parts),
            metadata={"ir_node_type": "weave"},
        )

    # ═══════════════════════════════════════════════════════════════
    #  TOOL SPEC COMPILATION
    # ═══════════════════════════════════════════════════════════════

    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        """
        Compile a tool specification into Claude's native tool format.

        Produces the structure expected by the Anthropic Messages API:
        {
            "name": "...",
            "description": "...",
            "input_schema": { "type": "object", "properties": {...} }
        }
        """
        # Build description from tool metadata
        desc_parts: list[str] = [
            f"External tool: {tool.name}"
        ]
        if tool.provider:
            desc_parts.append(f"Provider: {tool.provider}")
        if tool.timeout:
            desc_parts.append(f"Timeout: {tool.timeout}")

        # Build input schema from what we know about the tool
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

        return {
            "name": tool.name,
            "description": ". ".join(desc_parts),
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": ["query"],
            },
        }

    # ═══════════════════════════════════════════════════════════════
    #  AGENT BDI SYSTEM PROMPT — Claude-Optimized
    # ═══════════════════════════════════════════════════════════════

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
        """
        Build a Claude-optimized system prompt for agent BDI cycles.

        Uses Claude's preferred imperative instruction style:
          - Direct identity declaration ("You are Agent {name}")
          - Structured sections with [SECTION] headers
          - Explicit constraint enumeration
          - Chain-of-thought encouragement via thinking blocks

        The prompt adapts per strategy to leverage Claude's strengths:
          - react: Thought/Action/Observation pattern
          - reflexion: ReAct + self-critique block
          - plan_and_execute: Upfront plan generation then sequential execution
          - custom: Minimal framing, user-defined body steps only
        """
        parts: list[str] = []

        # ── Agent Identity ──────────────────────────────────────
        parts.append(
            f"You are Agent {agent_name}, an autonomous cognitive entity "
            f"operating on BDI (Belief-Desire-Intention) architecture."
        )
        parts.append(f"Your singular objective: {goal}")

        # ── Epistemic State ─────────────────────────────────────
        lattice_map = {
            "doubt": "LOW CONFIDENCE — treat all information as uncertain, verify before acting",
            "speculate": "EMERGING — some evidence gathered, hypotheses forming",
            "believe": "CONVERGENT — strong evidence supports your conclusions",
            "know": "TERMINAL — sufficient certainty achieved, ready to finalize",
        }
        state_desc = lattice_map.get(
            epistemic_state, f"UNKNOWN ({epistemic_state})"
        )
        parts.append(
            f"\n[EPISTEMIC STATE]\n"
            f"Current state: {epistemic_state} — {state_desc}\n"
            f"Tarski lattice: doubt ⊏ speculate ⊏ believe ⊏ know\n"
            f"Your goal is to advance along this lattice toward convergence."
        )

        # ── Strategy-Specific Protocol ──────────────────────────
        parts.append(self._compile_strategy_protocol(strategy))

        # ── Available Tools ─────────────────────────────────────
        if tools:
            tool_list = ", ".join(tools)
            parts.append(
                f"\n[AVAILABLE TOOLS]\n"
                f"You have access to: {tool_list}\n"
                f"Use tools deliberately — each invocation consumes budget resources. "
                f"Prefer the most direct tool for your current sub-goal."
            )

        # ── Budget Constraints ──────────────────────────────────
        remaining = max_iterations - iteration
        parts.append(
            f"\n[CONVERGENCE BUDGET]\n"
            f"Cycle: {iteration + 1} of {max_iterations}\n"
            f"Remaining cycles: {remaining}\n"
            f"You MUST converge within the remaining budget. "
            f"If you cannot make progress, report that explicitly "
            f"rather than consuming cycles without advancement."
        )

        return "\n".join(parts)

    def _compile_strategy_protocol(self, strategy: str) -> str:
        """Compile strategy-specific BDI reasoning instructions for Claude."""
        if strategy == "react":
            return (
                "\n[STRATEGY: ReAct]\n"
                "Follow the Thought → Action → Observation loop:\n"
                "1. THOUGHT: Analyze current beliefs and determine next action\n"
                "2. ACTION: Execute a tool call or produce intermediate reasoning\n"
                "3. OBSERVATION: Process the result and update your beliefs\n"
                "Repeat until your epistemic state reaches 'believe' or 'know'."
            )
        elif strategy == "reflexion":
            return (
                "\n[STRATEGY: Reflexion]\n"
                "Follow the ReAct loop with self-critique:\n"
                "1. THOUGHT: Analyze current beliefs and determine next action\n"
                "2. ACTION: Execute a tool call or produce intermediate reasoning\n"
                "3. OBSERVATION: Process the result\n"
                "4. CRITIQUE: Evaluate your own reasoning — identify gaps, "
                "contradictions, or missed alternatives\n"
                "5. REVISION: Adjust your approach based on self-critique\n"
                "The critique step is mandatory before advancing epistemic state."
            )
        elif strategy == "plan_and_execute":
            return (
                "\n[STRATEGY: Plan-and-Execute]\n"
                "Two-phase deliberation:\n"
                "PHASE 1 — PLANNING: Generate a complete action plan with "
                "numbered steps before executing any action. "
                "Each step should have a clear sub-goal and expected output.\n"
                "PHASE 2 — EXECUTION: Execute the plan sequentially. "
                "After each step, verify it succeeded. "
                "If reality diverges from the plan, re-plan from the current state."
            )
        else:
            return (
                f"\n[STRATEGY: {strategy}]\n"
                f"Execute using the '{strategy}' deliberation protocol. "
                f"Follow the body steps defined in the agent block."
            )

    # ═══════════════════════════════════════════════════════════════
    #  INTERNAL FORMATTING HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _format_probe(self, probe: IRProbe) -> str:
        """Format a probe directive as prompt text."""
        fields_str = ", ".join(probe.fields)
        return (
            f"Extract the following from {probe.target}: [{fields_str}]\n"
            f"Return structured results for each field."
        )

    def _format_reason(self, reason: IRReason) -> str:
        """Format a reason chain as prompt text."""
        parts: list[str] = []
        if reason.about:
            parts.append(f"Reason about: {reason.about}")
        if reason.ask:
            parts.append(reason.ask)
        if reason.show_work:
            parts.append("Show your complete reasoning process.")
        return "\n".join(parts)

    def _format_weave(self, weave: IRWeave) -> str:
        """Format a weave directive as prompt text."""
        sources_str = ", ".join(weave.sources)
        text = f"Synthesize [{sources_str}] into {weave.target or 'a coherent result'}"
        if weave.priority:
            text += f" prioritizing: {', '.join(weave.priority)}"
        return text
