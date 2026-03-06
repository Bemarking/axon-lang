import asyncio
from axon.runtime.executor import Executor
from axon.runtime.tracer import Tracer
from axon.backends.base_backend import CompiledStep, CompiledExecutionUnit
from tests.test_self_healing import SelfHealingMockClient

async def main():
    tracer = Tracer()
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

    unit = CompiledExecutionUnit(
        flow_name="TestFlow",
        steps=[step],
        active_anchors=[{"name": "NoHallucination"}],
    )

    result = await executor._execute_unit(unit, tracer=tracer)
    print("Result error:", result.error)
    print("Call count:", mock_client.call_count)
    if "ExtractData" in result.step_results:
        print("Step result:", result.step_results["ExtractData"])

asyncio.run(main())
