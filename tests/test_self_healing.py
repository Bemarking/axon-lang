"""
AXON Runtime — Self Healing Tests
=================================
Verifies that L3 semantic errors trigger feedback re-injection
and prompt the model to self-correct using CPS and RetryEngine.
"""

import asyncio
from typing import Any
import pytest

from axon.backends.base_backend import CompiledExecutionUnit, CompiledStep
from axon.compiler.ast_nodes import AnchorConstraint
from axon.compiler.ir_nodes import IRAnchor
from axon.runtime.executor import Executor, ModelClient, ModelResponse
from axon.runtime.retry_engine import RefineConfig
from axon.runtime.tracer import Tracer


class SelfHealingMockClient(ModelClient):
    """
    Mock client that simulates a self-healing interaction.
    It returns a failing response first, but yields a successful
    response when provided with the failure_context.
    """

    def __init__(self, initial_response: str, corrected_response: str):
        self.call_count = 0
        self.failure_contexts = []
        self.initial_response = initial_response
        self.corrected_response = corrected_response

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        effort: str = "",
        failure_context: str = "",
    ) -> ModelResponse:
        self.call_count += 1
        self.failure_contexts.append(failure_context)
        
        if failure_context:
            content = self.corrected_response
        else:
            content = self.initial_response

        await asyncio.sleep(0.01)
        return ModelResponse(content=content, raw=content)


@pytest.mark.asyncio
async def test_self_healing_anchor_breach():
    tracer = Tracer()

    # The step uses the NoHallucination anchor.
    # We simulate an initial hallucinated response, which fails the
    # anchor check. The engine should retry the step with the 
    # AnchorBreachError passed in failure_context, yielding the correct response.
    
    mock_client = SelfHealingMockClient(
        initial_response="I think I am hallucinating facts that are not grounded.",
        corrected_response="Based on the source: The sky is blue.",
    )
    executor = Executor(mock_client)

    step = CompiledStep(
        step_name="ExtractData",
        user_prompt="Extract data",
        system_prompt="Be accurate",
        output_schema={"type": "string"},
        metadata={"refine": {"max_attempts": 3, "backoff": "none"}},
    )

    # Note: NoHallucination anchor uses regular expressions to check for
    # phrases like "Based on the source: ...". 
    unit = CompiledExecutionUnit(
        flow_name="TestFlow",
        steps=(step,),
        active_anchors=[{"name": "NoHallucination"}],
    )

    result = await executor._execute_unit(unit, tracer=tracer)
    
    assert not result.error, f"Execution failed: {result.error}"
    # We expect 2 model calls: 1 initial + 1 retry
    assert mock_client.call_count == 2
    
    # The first call should have no failure context
    assert mock_client.failure_contexts[0] == ""
    
    # The second call should contain the failure context of the anchor breach
    assert "Anchor breach detected" in mock_client.failure_contexts[1]

    # The final step result should reflect the successful corrected response
    step_result = result.step_results[0]
    assert step_result.response.content == "Based on the source: The sky is blue."
    
    # Retry info should be captured
    assert step_result.retry_info is not None
    assert step_result.retry_info.success is True
    assert len(step_result.retry_info.attempts) == 2


@pytest.mark.asyncio
async def test_self_healing_validation_error():
    tracer = Tracer()

    # The step expects a RiskScore containing a score.
    # The initial response gives string, which fails validation.
    
    mock_client = SelfHealingMockClient(
        initial_response="Not an integer",
        corrected_response={"score": 0.8},
    )
    executor = Executor(mock_client)

    step = CompiledStep(
        step_name="GetNumber",
        user_prompt="Give me a score",
        system_prompt="Just the score",
        output_schema={"type": "object", "properties": {"score": {"type": "number"}}},
        metadata={"refine": {"max_attempts": 3, "backoff": "none"}, "required_fields": ["score"]},
    )

    unit = CompiledExecutionUnit(
        flow_name="TestFlow",
        steps=(step,),
        active_anchors=[],
    )

    result = await executor._execute_unit(unit, tracer=tracer)
    
    assert not result.error, f"Execution failed: {result.error}"
    assert mock_client.call_count == 2
    assert mock_client.failure_contexts[0] == ""
    assert "Expected structured output" in mock_client.failure_contexts[1]

    step_result = result.step_results[0]
    # At this point, the corrected_response {"score": 0.8} should have passed validation
    assert step_result.response.content == {"score": 0.8}
    assert step_result.validation is not None
    assert step_result.validation.is_valid is True
    
    assert step_result.retry_info is not None
    assert step_result.retry_info.success is True
    assert len(step_result.retry_info.attempts) == 2
