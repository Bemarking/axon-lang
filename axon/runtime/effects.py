"""
AXON Runtime — Algebraic Effects
================================
Implements the formal separation of pure deliberation and phenomenology (I/O)
using Delimited Continuations via Python ContextVars.

This fulfills the theoretical necessity of abstracting the BDI reasoning
loop away from the temporal constraints of streaming (SSE).
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional


@dataclass
class Effect:
    """Base class for all algebraic effects in Axon."""
    pass


@dataclass
class EmitEvent(Effect):
    """An effect representing an intermediate event in the BDI execution cycle."""
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)


# The ContextVar acts as our Delimited Continuation boundary
_current_handler: ContextVar[Optional[asyncio.Queue[Optional[Effect]]]] = ContextVar(
    "_current_handler", default=None
)


def perform(effect: Effect) -> None:
    """
    Perform an algebraic effect. If a handler is present in the current
    evaluation context, the effect is dispatched to it. Otherwise, it is
    silently ignored (preserving the purity of isolated execution).
    """
    handler_queue = _current_handler.get()
    if handler_queue is not None:
        # We use put_nowait because we assume the effect is merely logged
        # or streamed, and should not block the pure deliberation logic.
        try:
            handler_queue.put_nowait(effect)
        except asyncio.QueueFull:
            pass


async def handle_stream_effects(
    coro: Awaitable[Any]
) -> AsyncGenerator[Effect, None]:
    """
    An Algebraic Effect Handler. It intercepts `EmitEvent` (and other) effects
    thrown by the isolated execution coroutine and yields them as a stream.

    Args:
        coro: The isolated agent execution coroutine to run.

    Yields:
        Effect objects as they are performed in the pure logic.
    """
    # Unbounded queue for synchronous `put_nowait` from `perform`
    queue: asyncio.Queue[Optional[Effect]] = asyncio.Queue()
    token = _current_handler.set(queue)

    async def _runner() -> None:
        try:
            await coro
        finally:
            # Signal the end of the generator
            await queue.put(None)

    # Spawn the isolated execution in a background task
    task = asyncio.create_task(_runner())

    try:
        while True:
            # Await the next effect intercepted by the context var
            effect = await queue.get()
            if effect is None:
                break
            yield effect
    finally:
        # Cleanup boundary
        _current_handler.reset(token)
        if not task.done():
            task.cancel()
        
        # Await the task to propagate any exceptions
        try:
            await task
        except asyncio.CancelledError:
            pass
