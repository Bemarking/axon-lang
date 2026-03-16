"""
AXON Backends — Gemini Backend
================================
Compiles AXON IR into Google Gemini-native prompt structures.

This backend produces prompts optimized for the Gemini model family:
  - System instructions as a first-class Gemini parameter
  - Content parts with structured formatting
  - Function declarations in Gemini's FunctionDeclaration format
  - Rich grounding via context injection
  - Structured output via response schema

The output is ready for consumption by the Gemini API
(Phase 3 Runtime will handle actual HTTP calls).

Key differences from Anthropic:
  - Gemini uses "system_instruction" instead of a system message
  - Tool calls use "function_declarations" with stricter schema
  - Persona framing uses first-person identification
  - Structured output uses response_schema instead of content blocks
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


class GeminiBackend(BaseBackend):
    """
    Compiles AXON IR to Gemini-native prompt structures.

    Produces output compatible with the Gemini API:
      - system_instruction: persona + anchors + context
      - contents: [{role: "user", parts: [{text: ...}]}]
      - tools: [{function_declarations: [{...}]}]
    """

    @property
    def name(self) -> str:
        return "gemini"

    # ═══════════════════════════════════════════════════════════════
    #  SYSTEM INSTRUCTION COMPILATION
    # ═══════════════════════════════════════════════════════════════

    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        """
        Build Gemini's system_instruction from persona, context, and anchors.

        Gemini's system_instruction is applied before all content turns
        and persists across the entire generation. This makes it ideal
        for persona identity and hard constraints.
        """
        sections: list[str] = []

        # — Persona identity —
        if persona is not None:
            sections.append(self._compile_persona_block(persona))

        # — Context configuration —
        if context is not None:
            sections.append(self._compile_context_block(context))

        # — Anchor enforcement —
        if anchors:
            sections.append(self._compile_anchor_block(anchors))

        return "\n\n".join(sections)

    def _compile_persona_block(self, persona: IRPersona) -> str:
        """
        Compile persona into Gemini's system instruction format.

        Uses natural language framing optimized for Gemini's
        instruction following patterns.
        """
        lines: list[str] = [
            f"Your identity is {persona.name}."
        ]

        if persona.description:
            lines.append(persona.description)

        if persona.domain:
            domain_str = ", ".join(persona.domain)
            lines.append(f"Expertise areas: {domain_str}.")

        if persona.tone:
            lines.append(f"Tone of communication: {persona.tone}.")

        if persona.language:
            lines.append(f"Language for all responses: {persona.language}.")

        if persona.confidence_threshold is not None:
            lines.append(
                f"Only state claims when you are at least "
                f"{persona.confidence_threshold:.0%} confident."
            )

        if persona.cite_sources:
            lines.append(
                "Cite sources for factual claims using inline references."
            )

        if persona.refuse_if:
            refuse_str = "; ".join(persona.refuse_if)
            lines.append(f"Decline to respond if: {refuse_str}.")

        return "\n".join(lines)

    def _compile_context_block(self, context: IRContext) -> str:
        """Compile context into Gemini system instruction format."""
        lines: list[str] = ["## Session Parameters"]

        if context.depth:
            depth_map = {
                "shallow": "Keep responses brief and high-level.",
                "standard": "Provide clear, moderately detailed responses.",
                "deep": "Provide in-depth, comprehensive analysis.",
                "exhaustive": (
                    "Provide the most thorough analysis possible. "
                    "Cover every aspect in detail."
                ),
            }
            instruction = depth_map.get(
                context.depth,
                f"Response depth: {context.depth}.",
            )
            lines.append(f"- Depth: {instruction}")

        if context.language:
            lines.append(f"- Language: {context.language}")

        if context.max_tokens is not None:
            lines.append(
                f"- Target response length: approximately {context.max_tokens} tokens"
            )

        if context.cite_sources:
            lines.append("- Citations: Required for all factual statements")

        return "\n".join(lines)

    def _compile_anchor_block(self, anchors: list[IRAnchor]) -> str:
        """
        Compile anchors into Gemini-optimized constraint instructions.

        Uses markdown-style formatting which Gemini processes
        effectively for instruction adherence.
        """
        lines: list[str] = [
            "## Mandatory Constraints",
            "The following rules are absolute. Never violate them.",
            "",
        ]

        for i, anchor in enumerate(anchors, 1):
            lines.append(f"### Constraint {i}: {anchor.name}")

            if anchor.require:
                lines.append(f"- **MUST**: {anchor.require}")
            if anchor.reject:
                reject_str = ", ".join(anchor.reject)
                lines.append(f"- **MUST NOT**: {reject_str}")
            if anchor.enforce:
                lines.append(f"- **Rule**: {anchor.enforce}")
            if anchor.confidence_floor is not None:
                lines.append(
                    f"- **Min Confidence**: {anchor.confidence_floor:.0%} — "
                    f"do not make claims below this threshold"
                )
            if anchor.unknown_response:
                lines.append(
                    f'- **When uncertain**, respond with: '
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
        Compile an IR step into a Gemini-optimized prompt.

        Dispatches based on step type and embedded cognitive ops.
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

        # Fallback
        return CompiledStep(
            step_name=getattr(step, "name", step.node_type),
            user_prompt=f"Execute: {step.node_type}",
        )

    def _compile_step_node(
        self, step: IRStep, context: CompilationContext
    ) -> CompiledStep:
        """Compile a named cognitive step for Gemini."""
        parts: list[str] = []

        if step.given:
            parts.append(f"**Input:** {step.given}")

        # Embedded operations
        if step.probe is not None:
            parts.append(self._format_probe(step.probe))
        elif step.reason is not None:
            parts.append(self._format_reason(step.reason))
        elif step.weave is not None:
            parts.append(self._format_weave(step.weave))
        elif step.ask:
            parts.append(step.ask)

        if step.output_type:
            parts.append(
                f"\n**Required output type:** `{step.output_type}`"
            )

        if step.confidence_floor is not None:
            parts.append(
                f"\n**Minimum confidence:** {step.confidence_floor:.0%}. "
                f"Express uncertainty if below this threshold."
            )

        # Tool handling
        tool_decls: list[dict[str, Any]] = []
        if step.use_tool is not None:
            tool_name = step.use_tool.tool_name
            if tool_name in context.tools:
                tool_decls.append(
                    self.compile_tool_spec(context.tools[tool_name])
                )
            tool_msg = f"\n**Tool to use:** `{step.use_tool.tool_name}`"
            if step.use_tool.argument:
                tool_msg += f" with input: {step.use_tool.argument}"
            parts.append(tool_msg)

        return CompiledStep(
            step_name=step.name,
            user_prompt="\n".join(parts),
            tool_declarations=tool_decls,
            metadata={"ir_node_type": "step"},
        )

    def _compile_intent(
        self, intent: IRIntent, context: CompilationContext
    ) -> CompiledStep:
        """Compile an atomic intent for Gemini."""
        parts: list[str] = []

        if intent.given:
            parts.append(f"**Given:** {intent.given}")

        parts.append(intent.ask)

        if intent.output_type_name:
            type_str = intent.output_type_name
            if intent.output_type_generic:
                type_str += f"<{intent.output_type_generic}>"
            if intent.output_type_optional:
                type_str += " (nullable)"
            parts.append(f"\n**Expected output:** `{type_str}`")

        if intent.confidence_floor is not None:
            parts.append(
                f"\n**Min confidence:** {intent.confidence_floor:.0%}"
            )

        return CompiledStep(
            step_name=intent.name,
            user_prompt="\n".join(parts),
            metadata={"ir_node_type": "intent"},
        )

    def _compile_probe(
        self, probe: IRProbe, context: CompilationContext
    ) -> CompiledStep:
        """Compile a structured extraction for Gemini."""
        fields_str = ", ".join(probe.fields)

        prompt = (
            f"Extract the following fields from the given source:\n\n"
            f"**Fields to extract:** {fields_str}\n"
            f"**Source:** {probe.target}\n\n"
            f"Return a JSON object with keys: [{fields_str}]. "
            f"Use `null` for fields that cannot be determined."
        )

        # Gemini's response_schema for structured output
        schema: dict[str, Any] = {
            "type": "OBJECT",
            "properties": {
                f: {"type": "STRING"} for f in probe.fields
            },
            "required": list(probe.fields),
        }

        return CompiledStep(
            step_name=f"probe_{probe.target}",
            user_prompt=prompt,
            output_schema=schema,
            metadata={"ir_node_type": "probe"},
        )

    def _compile_reason(
        self, reason: IRReason, context: CompilationContext
    ) -> CompiledStep:
        """Compile chain-of-thought reasoning for Gemini."""
        parts: list[str] = []

        if reason.about:
            parts.append(f"**Topic:** {reason.about}")

        if reason.given:
            given_str = ", ".join(reason.given)
            parts.append(f"**Base information:** {given_str}")

        if reason.ask:
            parts.append(f"\n{reason.ask}")

        if reason.depth > 1:
            parts.append(
                f"\nPerform a {reason.depth}-level deep analysis. "
                f"Each level should build on the insights of the previous one."
            )

        if reason.show_work or reason.chain_of_thought:
            parts.append(
                "\nThink step by step. Show your complete reasoning process "
                "explicitly before arriving at your conclusion."
            )

        if reason.output_type:
            parts.append(
                f"\n**Output type:** `{reason.output_type}`"
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
        """Compile semantic synthesis for Gemini."""
        sources_str = ", ".join(weave.sources)
        parts: list[str] = [
            f"**Synthesize** the following sources: [{sources_str}]"
        ]

        if weave.target:
            parts.append(f"\n**Target output:** {weave.target}")

        if weave.format_type:
            parts.append(f"**Format:** {weave.format_type}")

        if weave.priority:
            priority_str = " → ".join(weave.priority)
            parts.append(f"**Priority order:** {priority_str}")

        if weave.style:
            parts.append(f"**Style:** {weave.style}")

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
        Compile a tool specification into Gemini's FunctionDeclaration format.

        Produces:
        {
            "name": "...",
            "description": "...",
            "parameters": {
                "type": "OBJECT",
                "properties": {...},
                "required": [...]
            }
        }

        Note: Gemini uses uppercase type names (STRING, OBJECT, INTEGER)
        and a slightly different schema structure than OpenAI/Anthropic.
        """
        # Build description
        desc_parts: list[str] = [f"Tool: {tool.name}"]
        if tool.provider:
            desc_parts.append(f"Provider: {tool.provider}")
        if tool.timeout:
            desc_parts.append(f"Timeout: {tool.timeout}")

        # Build parameter schema (Gemini format)
        properties: dict[str, Any] = {
            "query": {
                "type": "STRING",
                "description": f"The input query for {tool.name}",
            }
        }
        if tool.max_results is not None:
            properties["max_results"] = {
                "type": "INTEGER",
                "description": "Maximum number of results to return",
            }

        return {
            "name": tool.name,
            "description": ". ".join(desc_parts),
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
                "required": ["query"],
            },
        }

    # ═══════════════════════════════════════════════════════════════
    #  AGENT BDI SYSTEM PROMPT — Gemini-Optimized
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
        Build a Gemini-optimized system prompt for agent BDI cycles.

        Uses Gemini's preferred instruction style:
          - Markdown-formatted sections (##, **bold**, `code`)
          - First-person identity framing ("Your identity is Agent {name}")
          - Structured parameter blocks
          - Step-by-step reasoning via CoT markers

        The prompt adapts per strategy to leverage Gemini's strengths
        with structured markdown and explicit section demarcation.
        """
        parts: list[str] = []

        # ── Agent Identity ──────────────────────────────────────
        parts.append(
            f"# Agent: {agent_name}\n\n"
            f"Your identity is Agent {agent_name}. You are an autonomous "
            f"cognitive entity using BDI (Belief-Desire-Intention) architecture."
        )
        parts.append(f"\n**Objective:** {goal}")

        # ── Epistemic State ─────────────────────────────────────
        lattice_map = {
            "doubt": "Low confidence — verify all information before acting",
            "speculate": "Emerging — evidence gathering in progress, hypotheses forming",
            "believe": "Convergent — strong evidence supports conclusions",
            "know": "Terminal — certainty achieved, ready for final output",
        }
        state_desc = lattice_map.get(
            epistemic_state, f"Unknown ({epistemic_state})"
        )
        parts.append(
            f"\n## Current Epistemic State\n\n"
            f"- **State:** `{epistemic_state}` — {state_desc}\n"
            f"- **Lattice:** `doubt` → `speculate` → `believe` → `know`\n"
            f"- **Directive:** Advance along this lattice toward convergence."
        )

        # ── Strategy-Specific Protocol ──────────────────────────
        parts.append(self._compile_strategy_protocol_gemini(strategy))

        # ── Available Tools ─────────────────────────────────────
        if tools:
            tool_items = "\n".join(f"- `{t}`" for t in tools)
            parts.append(
                f"\n## Available Tools\n\n"
                f"{tool_items}\n\n"
                f"Use tools deliberately. Each invocation consumes budget "
                f"resources. Select the most direct tool for the current sub-goal."
            )

        # ── Budget Constraints ──────────────────────────────────
        remaining = max_iterations - iteration
        parts.append(
            f"\n## Convergence Budget\n\n"
            f"| Parameter | Value |\n"
            f"|-----------|-------|\n"
            f"| Current cycle | {iteration + 1} of {max_iterations} |\n"
            f"| Remaining | {remaining} cycles |\n\n"
            f"You **must** converge within the remaining budget. "
            f"If progress is blocked, report it explicitly rather "
            f"than consuming cycles without advancement."
        )

        return "\n".join(parts)

    def _compile_strategy_protocol_gemini(self, strategy: str) -> str:
        """Compile strategy-specific BDI reasoning instructions for Gemini."""
        if strategy == "react":
            return (
                "\n## Strategy: ReAct\n\n"
                "Follow the **Thought → Action → Observation** loop:\n\n"
                "1. **Thought:** Analyze current beliefs, determine next action\n"
                "2. **Action:** Execute a tool call or produce reasoning\n"
                "3. **Observation:** Process results, update beliefs\n\n"
                "Repeat until epistemic state reaches `believe` or `know`."
            )
        elif strategy == "reflexion":
            return (
                "\n## Strategy: Reflexion\n\n"
                "Follow the ReAct loop with mandatory self-critique:\n\n"
                "1. **Thought:** Analyze beliefs, determine next action\n"
                "2. **Action:** Execute tool call or reasoning step\n"
                "3. **Observation:** Process the result\n"
                "4. **Critique:** Evaluate your own reasoning — identify "
                "gaps, contradictions, or missed alternatives\n"
                "5. **Revision:** Adjust approach based on self-critique\n\n"
                "The critique step is **mandatory** before advancing epistemic state."
            )
        elif strategy == "plan_and_execute":
            return (
                "\n## Strategy: Plan-and-Execute\n\n"
                "Two-phase deliberation:\n\n"
                "### Phase 1 — Planning\n"
                "Generate a complete action plan with numbered steps "
                "before executing. Each step needs a clear sub-goal "
                "and expected output.\n\n"
                "### Phase 2 — Execution\n"
                "Execute sequentially. After each step, verify success. "
                "If reality diverges from plan, re-plan from current state."
            )
        else:
            return (
                f"\n## Strategy: {strategy}\n\n"
                f"Execute using the `{strategy}` deliberation protocol. "
                f"Follow the body steps defined in the agent block."
            )

    # ═══════════════════════════════════════════════════════════════
    #  INTERNAL FORMATTING HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _format_probe(self, probe: IRProbe) -> str:
        """Format probe as Gemini-optimized markdown."""
        fields_str = ", ".join(probe.fields)
        return (
            f"**Extract** from `{probe.target}`: [{fields_str}]\n"
            f"Return structured results as JSON."
        )

    def _format_reason(self, reason: IRReason) -> str:
        """Format reason chain as Gemini text."""
        parts: list[str] = []
        if reason.about:
            parts.append(f"**Reason about:** {reason.about}")
        if reason.ask:
            parts.append(reason.ask)
        if reason.show_work:
            parts.append("Think step by step.")
        return "\n".join(parts)

    def _format_weave(self, weave: IRWeave) -> str:
        """Format weave as Gemini text."""
        sources_str = ", ".join(weave.sources)
        target = weave.target or "a unified result"
        text = f"**Synthesize** [{sources_str}] into {target}"
        if weave.priority:
            text += f" (priority: {', '.join(weave.priority)})"
        return text
