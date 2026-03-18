import pytest
import asyncio
from axon.runtime.effects import EmitEvent, perform
from axon.runtime.streaming import sse_event_stream

@pytest.mark.asyncio
async def test_sse_event_stream_yields_events():
    """Test that the SSE boundary handles pure algebraic effects and formats them correctly."""
    
    async def mock_agent_execution():
        # Simulate pure agent deliberation
        perform(EmitEvent(event_type="AgentCycleStart", data={"iteration": 0}))
        await asyncio.sleep(0.01)
        
        perform(EmitEvent(event_type="ModelReasoning", data={"phase": "deliberate"}))
        await asyncio.sleep(0.01)
        
        return "Final Agent Result"

    # Consuming the SSE stream boundary
    sse_events = []
    async for packet in sse_event_stream(mock_agent_execution()):
        sse_events.append(packet)

    assert len(sse_events) == 2
    
    # Check SSE format
    assert sse_events[0].startswith("data: {")
    assert "AgentCycleStart" in sse_events[0]
    assert sse_events[0].endswith("\\n\\n") or sse_events[0].endswith("\n\n")
    
    assert sse_events[1].startswith("data: {")
    assert "ModelReasoning" in sse_events[1]
    assert sse_events[1].endswith("\\n\\n") or sse_events[1].endswith("\n\n")

@pytest.mark.asyncio
async def test_sse_event_stream_handles_exceptions():
    """Test that the SSE boundary cleanly handles exceptions inside the execution coroutine."""
    
    async def failing_execution():
        perform(EmitEvent(event_type="AgentCycleStart", data={"iteration": 0}))
        raise ValueError("Simulated failure")

    sse_events = []
    with pytest.raises(ValueError, match="Simulated failure"):
        async for packet in sse_event_stream(failing_execution()):
            sse_events.append(packet)
            
    # Should still yield the events emitted before the exception
    assert len(sse_events) == 1
    assert "AgentCycleStart" in sse_events[0]
