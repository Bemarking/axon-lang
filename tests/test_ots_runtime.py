"""
AXON Ontological Tool Synthesis (OTS) Primitive — Runtime Tests
===============================================================
Verifies the execution of compiled OTS steps by the runtime Executor.
"""

import pytest

from axon.backends.base_backend import CompiledStep
from axon.runtime.executor import Executor
from tests.test_executor import MockModelClient, make_program, make_unit


# ═══════════════════════════════════════════════════════════════════
#  OTS RUNTIME EXECUTION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOtsRuntime:
    """Tests the execution of OTS capabilities."""

    @pytest.mark.asyncio
    async def test_ots_synthesis_execution(self):
        # We configure a MockModelClient that will respond to the synthesized prompt.
        # The prompt will contain teleology, constraints, and the target value.
        client = MockModelClient()
        executor = Executor(client=client)

        # Create a mock compiled step for OTS
        ots_metadata = {
            "ots_apply": {
                "ots_name": "EmailSummarizer",
                "target": "Raw Email Text",
                "ots_definition": {
                    "teleology": "Summarize briefly",
                    "linear_constraints": [("length", "stricly_once")],
                    "homotopy_search": "deep",
                    "loss_function": "L2",
                    "output_type": "string"
                }
            }
        }
        
        step = CompiledStep(
            step_name="summarize_email",
            system_prompt="",
            user_prompt="", # ots uses the metadata to derive the prompt
            metadata=ots_metadata
        )

        program = make_program([
            make_unit("main_flow", [step])
        ])

        result = await executor.execute(program)
        
        # Verify it succeeds
        assert result.success is True
        assert len(result.unit_results) == 1
        
        step_result = result.unit_results[0].step_results[0]
        assert step_result.step_name == "summarize_email"
        
        # Verify the prompt sent to the model via the mock client
        assert client.call_count == 1
        call_info = client.calls[0]
        
        # The system prompt should declare it's an OTS Synthesizer
        assert "Ontological Tool Synthesizer" in call_info["system_prompt"]
        
        # The user prompt should contain the teleology, constraints, and target
        p = call_info["user_prompt"]
        assert "EmailSummarizer" in p
        assert "Summarize briefly" in p
        assert "- length: stricly_once" in p
        assert "Raw Email Text" in p
        assert "formatted as string" in p
