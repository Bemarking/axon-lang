"""
AXON Engine — PID Controller for Mandate Enforcement
======================================================
§4 — Vía A: Closed-Loop PID Control with Lyapunov Stability.

Implements the discrete PID controller from the Cybernetic Refinement
Calculus (CRC) paper. At each correction step k, the controller
computes the control signal:

    u(k) = Kp·e(k) + Ki·Σe(j) + Kd·[e(k)−e(k−1)]

where:
    e(k) = 1 − M(x_k)    — the error between ideal and current output
    M(x_k) ∈ [0, 1]      — semantic constraint satisfaction score
    Kp, Ki, Kd            — proportional, integral, derivative gains

Convergence criterion (Theorem 2 from the paper):
    The system converges when |e(k)| ≤ ε (tolerance).

Lyapunov stability guarantee (Proposition 3):
    V(k) = e(k)²
    ΔV(k) = V(k+1) − V(k) < 0   ∀ k where |e(k)| > ε

    This is guaranteed when Kp > 0 and Ki, Kd ≥ 0 with
    appropriate gain tuning. The type checker enforces these
    constraints statically.

Implementation notes:
    - Pure Python, no external dependencies
    - Immutable state history for tracer integration
    - Anti-windup: integral term clamped to [-100, 100]
    - Thread-safe (stateless between calls)

Author: Ricardo Velit (theoretical framework)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  PID CORRECTION STEP — one iteration of the control loop
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PIDStep:
    """A single PID correction step record.

    Attributes:
        step:          The step index k.
        error:         e(k) = 1 − M(x_k).
        proportional:  Kp · e(k).
        integral:      Ki · Σ e(j), j=0..k.
        derivative:    Kd · [e(k) − e(k−1)].
        control:       u(k) = P + I + D.
        satisfaction:  M(x_k) — the constraint satisfaction score.
        converged:     Whether |e(k)| ≤ ε.
    """

    step: int
    error: float
    proportional: float
    integral: float
    derivative: float
    control: float
    satisfaction: float
    converged: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "step": self.step,
            "error": round(self.error, 6),
            "proportional": round(self.proportional, 6),
            "integral": round(self.integral, 6),
            "derivative": round(self.derivative, 6),
            "control": round(self.control, 6),
            "satisfaction": round(self.satisfaction, 6),
            "converged": self.converged,
        }


# ═══════════════════════════════════════════════════════════════════
#  PID RESULT — outcome of the entire control loop
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PIDResult:
    """Outcome of the PID enforcement loop.

    Attributes:
        converged:       Whether the loop reached convergence.
        steps_taken:     Number of correction steps executed.
        max_steps:       Maximum steps allowed (N).
        final_error:     e(k) at the last step.
        final_satisfaction:  M(x_k) at the last step.
        history:         Complete sequence of PIDStep records.
        lyapunov_stable: Whether ΔV < 0 held throughout.
    """

    converged: bool = False
    steps_taken: int = 0
    max_steps: int = 0
    final_error: float = 1.0
    final_satisfaction: float = 0.0
    history: tuple[PIDStep, ...] = ()
    lyapunov_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "converged": self.converged,
            "steps_taken": self.steps_taken,
            "max_steps": self.max_steps,
            "final_error": round(self.final_error, 6),
            "final_satisfaction": round(self.final_satisfaction, 6),
            "lyapunov_stable": self.lyapunov_stable,
            "history": [s.to_dict() for s in self.history],
        }


# ═══════════════════════════════════════════════════════════════════
#  PID CONTROLLER — the CRC enforcement engine
# ═══════════════════════════════════════════════════════════════════


# Anti-windup clamp bound for the integral term
_INTEGRAL_CLAMP = 100.0


class PIDController:
    """Discrete PID controller for mandate enforcement.

    Given a constraint satisfaction function M(x) → [0, 1], the
    controller iteratively adjusts the error signal to drive
    the system toward convergence (|e(k)| ≤ ε).

    The controller does NOT modify the LLM output directly. Instead,
    it computes the control signal u(k) which the executor uses to:
      - Adjust temperature (Vía B: thermodynamic logit bias)
      - Inject corrective prompt context
      - Request re-generation with modified parameters

    Usage::

        controller = PIDController(kp=10.0, ki=0.1, kd=0.05)
        result = controller.run(
            satisfaction_fn=lambda x: score_json(x),
            initial_output=model_output,
            tolerance=0.01,
            max_steps=50,
        )
        if not result.converged:
            # on_violation policy kicks in
            ...
    """

    def __init__(
        self,
        kp: float = 10.0,
        ki: float = 0.1,
        kd: float = 0.05,
    ) -> None:
        """Initialize PID gains.

        Args:
            kp:  Proportional gain (Kp > 0).
            ki:  Integral gain (Ki ≥ 0).
            kd:  Derivative gain (Kd ≥ 0).
        """
        self._kp = kp
        self._ki = ki
        self._kd = kd

    @property
    def kp(self) -> float:
        return self._kp

    @property
    def ki(self) -> float:
        return self._ki

    @property
    def kd(self) -> float:
        return self._kd

    def compute_step(
        self,
        *,
        satisfaction: float,
        step_index: int,
        integral_sum: float,
        previous_error: float,
        tolerance: float,
    ) -> tuple[PIDStep, float]:
        """Compute a single PID correction step.

        Args:
            satisfaction:    M(x_k) ∈ [0, 1] — current constraint score.
            step_index:      k — the current step index.
            integral_sum:    Running integral accumulator Σ e(j).
            previous_error:  e(k−1) from the previous step.
            tolerance:       ε — convergence threshold.

        Returns:
            A tuple of (PIDStep record, updated integral_sum).
        """
        # Error: e(k) = 1 − M(x_k)
        error = 1.0 - satisfaction

        # P term: Kp · e(k)
        p_term = self._kp * error

        # I term: Ki · Σ e(j) with anti-windup
        integral_sum += error
        integral_sum = max(-_INTEGRAL_CLAMP, min(_INTEGRAL_CLAMP, integral_sum))
        i_term = self._ki * integral_sum

        # D term: Kd · [e(k) − e(k−1)]
        d_term = self._kd * (error - previous_error)

        # Control signal: u(k) = P + I + D
        control = p_term + i_term + d_term

        # Convergence check: |e(k)| ≤ ε
        converged = abs(error) <= tolerance

        pid_step = PIDStep(
            step=step_index,
            error=error,
            proportional=p_term,
            integral=i_term,
            derivative=d_term,
            control=control,
            satisfaction=satisfaction,
            converged=converged,
        )

        return pid_step, integral_sum

    def run(
        self,
        *,
        satisfaction_scores: list[float],
        tolerance: float = 0.01,
        max_steps: int = 50,
    ) -> PIDResult:
        """Run the PID control loop over a sequence of satisfaction scores.

        This is the batch mode: given a pre-computed sequence of M(x_k)
        scores (one per retry/correction attempt), compute the full PID
        trajectory and determine convergence.

        In the runtime executor, scores are generated lazily via model
        re-calls; this method provides the mathematical core.

        Args:
            satisfaction_scores:  Sequence of M(x_k) ∈ [0, 1].
            tolerance:            ε — convergence threshold.
            max_steps:            N — maximum correction steps.

        Returns:
            A PIDResult with the full trajectory.
        """
        history: list[PIDStep] = []
        integral_sum = 0.0
        previous_error = 0.0
        lyapunov_stable = True

        effective_scores = satisfaction_scores[:max_steps]

        for k, score in enumerate(effective_scores):
            pid_step, integral_sum = self.compute_step(
                satisfaction=score,
                step_index=k,
                integral_sum=integral_sum,
                previous_error=previous_error,
                tolerance=tolerance,
            )
            history.append(pid_step)

            # Lyapunov stability check: V(k) = e(k)²
            # ΔV < 0 iff |e(k)| < |e(k-1)|
            if k > 0 and abs(pid_step.error) > abs(previous_error):
                lyapunov_stable = False

            previous_error = pid_step.error

            if pid_step.converged:
                break

        final = history[-1] if history else None

        return PIDResult(
            converged=final.converged if final else False,
            steps_taken=len(history),
            max_steps=max_steps,
            final_error=final.error if final else 1.0,
            final_satisfaction=final.satisfaction if final else 0.0,
            history=tuple(history),
            lyapunov_stable=lyapunov_stable,
        )
