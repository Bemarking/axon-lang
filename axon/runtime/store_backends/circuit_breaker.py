"""
AXON Runtime — Circuit Breaker & Retry
========================================
Production-grade resilience patterns for store backend operations.

Implements:
  - Exponential backoff retry with jitter
  - Circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - Configurable failure thresholds and recovery timeouts
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal — requests pass through
    OPEN = auto()        # Tripped — requests rejected immediately
    HALF_OPEN = auto()   # Testing — one probe request allowed


@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker."""
    failure_threshold: int = 5        # failures before opening
    recovery_timeout: float = 30.0    # seconds before half-open
    half_open_max_calls: int = 1      # probes allowed in half-open
    success_threshold: int = 2        # successes to close from half-open


class CircuitBreaker:
    """Circuit breaker for store backend calls.

    State transitions:
      CLOSED  →(failure_threshold exceeded)→  OPEN
      OPEN    →(recovery_timeout elapsed)→    HALF_OPEN
      HALF_OPEN →(success_threshold met)→     CLOSED
      HALF_OPEN →(any failure)→               OPEN
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state (may transition OPEN → HALF_OPEN)."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info("Circuit breaker → HALF_OPEN (recovery timeout)")
        return self._state

    def record_success(self) -> None:
        """Record a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker → CLOSED (recovered)")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker → OPEN (half-open probe failed)")
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker → OPEN "
                    f"({self._failure_count} failures)"
                )

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state  # may trigger OPEN → HALF_OPEN
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self._config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0


# ═══════════════════════════════════════════════════════════════════
#  RETRY WITH EXPONENTIAL BACKOFF
# ═══════════════════════════════════════════════════════════════════


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 0.1       # seconds
    max_delay: float = 5.0        # seconds cap
    exponential_base: float = 2.0
    jitter: bool = True           # add random jitter


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""
    pass


async def retry_with_backoff(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    config: RetryConfig | None = None,
    circuit: CircuitBreaker | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with retry + circuit breaker.

    Args:
        func:    The async callable to execute.
        config:  Retry configuration.
        circuit: Optional circuit breaker.
        *args, **kwargs: Arguments forwarded to ``func``.

    Returns:
        The return value of ``func``.

    Raises:
        CircuitOpenError: If the circuit breaker is open.
        Exception: The last exception after all retries exhausted.
    """
    cfg = config or RetryConfig()
    last_exc: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        # Circuit breaker check
        if circuit and not circuit.allow_request():
            raise CircuitOpenError(
                f"Circuit breaker is {circuit.state.name} — "
                f"request rejected"
            )

        try:
            result = await func(*args, **kwargs)
            if circuit:
                circuit.record_success()
            return result

        except Exception as exc:
            last_exc = exc
            if circuit:
                circuit.record_failure()

            if attempt >= cfg.max_retries:
                break

            # Calculate delay with exponential backoff
            delay = min(
                cfg.base_delay * (cfg.exponential_base ** attempt),
                cfg.max_delay,
            )
            if cfg.jitter:
                delay *= (0.5 + random.random())

            logger.warning(
                f"Retry {attempt + 1}/{cfg.max_retries} "
                f"after {delay:.2f}s: {exc}"
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
