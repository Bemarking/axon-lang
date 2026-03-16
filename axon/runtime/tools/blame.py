"""
AXON Runtime — Blame Semantics for FFI Boundaries (v0.14.0)
=============================================================
Formal contract monitoring with Indy blame attribution for
the Python↔Axon tool boundary.

Theoretical foundation — Convergence Theorem 3:

    cross_ffi : τ_python → τ_axon<believe+tainted>

    -- Every datum crossing the FFI boundary suffers epistemic
    -- degradation. NEVER produces τ_axon<know> directly.
    -- Promotion requires shield + anchor validation.

This module implements three core concepts:

  1. **BlameLabel** — identifies WHO violated the contract:
     - CALLER (Axon side): sent invalid arguments
     - SERVER (Python side): returned invalid data

  2. **BlameFault** — a structured fault record with full context
     for debugging and tracing contract violations.

  3. **ContractMonitor** — wraps tool dispatch with pre/post-condition
     checking. Implements Findler & Felleisen higher-order contracts
     with Indy blame semantics (independent blame evaluation).

Architecture::

    Axon Flow
        → ContractMonitor.check_precondition(args)     # blame CALLER if fails
        → ToolDispatcher.dispatch(tool, args)           # actual execution
        → ContractMonitor.check_postcondition(result)   # blame SERVER if fails
        → Epistemic downgrade: result → believe+tainted
        → Flow continues with tainted data
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from axon.runtime.tools.tool_schema import ToolSchema


# ═══════════════════════════════════════════════════════════════════
#  BLAME LABELS — WHO violated the contract?
# ═══════════════════════════════════════════════════════════════════

class BlameLabel(Enum):
    """
    Identifies the responsible party in a contract violation.

    Findler & Felleisen (2002) blame semantics:
      - CALLER (blame⁻): the agent/flow sent bad arguments
      - SERVER (blame⁺): the tool/Python returned bad data

    Indy semantics: each side has its own contract evaluated
    independently. A CALLER violation does not excuse a SERVER
    violation and vice versa.
    """
    CALLER = "caller"    # Axon side — bad arguments
    SERVER = "server"    # Python side — bad return value
    UNKNOWN = "unknown"  # Cannot determine blame


# ═══════════════════════════════════════════════════════════════════
#  BLAME FAULT — structured contract violation record
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BlameFault:
    """
    A structured record of a contract violation at the FFI boundary.

    Contains full context for debugging:
      - Who is blamed (BlameLabel)
      - Which boundary was crossed (pre/post)
      - Expected vs actual types/values
      - Stack trace for the violation
      - Tool name and timestamp

    Usage::

        fault = BlameFault(
            label=BlameLabel.SERVER,
            boundary="postcondition",
            tool_name="WebSearch",
            expected_type="list[dict]",
            actual_type="str",
            actual_value="error: rate limited",
            message="Tool returned str instead of list[dict]",
        )
    """
    label: BlameLabel = BlameLabel.UNKNOWN
    boundary: str = ""            # "precondition" | "postcondition" | "effect"
    tool_name: str = ""
    expected_type: str = ""
    actual_type: str = ""
    actual_value: Any = None
    message: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict for tracing."""
        return {
            "blame": self.label.value,
            "boundary": self.boundary,
            "tool": self.tool_name,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "message": self.message,
            "timestamp": self.timestamp,
            "context": self.context,
        }


# ═══════════════════════════════════════════════════════════════════
#  CONTRACT MONITOR — pre/post-condition enforcement
# ═══════════════════════════════════════════════════════════════════

class ContractViolation(Exception):
    """Raised when a contract is violated at the FFI boundary."""

    def __init__(self, fault: BlameFault) -> None:
        self.fault = fault
        super().__init__(str(fault.message))


class ContractMonitor:
    """
    Monitors tool dispatch contracts with Indy blame attribution.

    Wraps every tool invocation with:
      1. **Precondition check** (blame CALLER if fails):
         Validates input arguments against the ToolSchema.
      2. **Postcondition check** (blame SERVER if fails):
         Validates return value against expected output type.
      3. **Epistemic downgrade** (always applies):
         Any data crossing the FFI boundary is downgraded to
         ``believe+tainted``. NEVER ``know``.

    The monitor is stateful: it accumulates all faults for a
    session, enabling aggregate blame analysis.

    Usage::

        monitor = ContractMonitor()
        
        # Before dispatch
        fault = monitor.check_precondition(schema, args)
        if fault:
            handle_blame(fault)  # CALLER blamed
        
        # After dispatch
        fault = monitor.check_postcondition(schema, result)
        if fault:
            handle_blame(fault)  # SERVER blamed
        
        # Always
        result = monitor.apply_epistemic_downgrade(result)
    """

    __slots__ = ("_faults", "_tool_invocations")

    def __init__(self) -> None:
        self._faults: list[BlameFault] = []
        self._tool_invocations: int = 0

    @property
    def faults(self) -> list[BlameFault]:
        """All accumulated contract faults."""
        return list(self._faults)

    @property
    def has_faults(self) -> bool:
        """Whether any contract violations have occurred."""
        return len(self._faults) > 0

    @property
    def total_invocations(self) -> int:
        """Total number of tool invocations monitored."""
        return self._tool_invocations

    def check_precondition(
        self,
        schema: ToolSchema,
        args: dict[str, Any],
    ) -> BlameFault | None:
        """
        Check input arguments against the tool's schema.

        If validation fails, creates a BlameFault with label=CALLER.
        The caller (Axon flow) sent invalid arguments.

        Returns None if precondition holds, BlameFault otherwise.
        """
        self._tool_invocations += 1

        valid, errors = schema.validate_input(args)
        if valid:
            return None

        fault = BlameFault(
            label=BlameLabel.CALLER,
            boundary="precondition",
            tool_name=schema.name,
            expected_type=str(
                [(p.name, p.type_name) for p in schema.input_params]
            ),
            actual_type=str({k: type(v).__name__ for k, v in args.items()}),
            actual_value=args,
            message=f"Precondition violated: {'; '.join(errors)}",
            context={"errors": errors},
        )
        self._faults.append(fault)
        return fault

    def check_postcondition(
        self,
        schema: ToolSchema,
        result: Any,
    ) -> BlameFault | None:
        """
        Check tool output against the schema's declared output type.

        If the result doesn't match, creates a BlameFault with
        label=SERVER. The tool (Python function) returned bad data.

        Returns None if postcondition holds, BlameFault otherwise.
        """
        # Basic type checking against declared output
        if not schema.output_type:
            return None

        actual_type = type(result).__name__
        expected = schema.output_type

        # Simple validation: check if the result is the declared type
        type_ok = self._validate_output_type(result, expected)
        if type_ok:
            return None

        fault = BlameFault(
            label=BlameLabel.SERVER,
            boundary="postcondition",
            tool_name=schema.name,
            expected_type=expected,
            actual_type=actual_type,
            actual_value=repr(result)[:200],  # truncate for safety
            message=(
                f"Postcondition violated: expected {expected}, "
                f"got {actual_type}"
            ),
        )
        self._faults.append(fault)
        return fault

    def apply_epistemic_downgrade(
        self,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply mandatory epistemic downgrade to FFI-crossing data.

        Convergence Theorem 3:
            cross_ffi : τ_python → τ_axon<believe+tainted>

        ANY data that crosses the Python→Axon boundary is:
          - Marked as tainted (trust lattice: Untrusted)
          - Downgraded to epistemic level ``believe`` (never ``know``)
          - Must pass through shield + anchor for promotion

        This is NOT optional. It's a forced type-system coercion.
        """
        result["_tainted"] = True
        result["_epistemic_level"] = "believe"
        result["_ffi_boundary"] = True
        return result

    @staticmethod
    def _validate_output_type(value: Any, expected: str) -> bool:
        """Simple type validation against schema string types."""
        type_map: dict[str, type | tuple[type, ...]] = {
            "str": str,
            "int": int,
            "float": (int, float),
            "bool": bool,
            "list": list,
            "dict": dict,
            "list[str]": list,
            "list[int]": list,
            "list[dict]": list,
            "dict[str,str]": dict,
            "dict[str,Any]": dict,
            "Any": object,
        }
        expected_type = type_map.get(expected)
        if expected_type is None:
            return True  # Unknown type — pass (could be custom type)
        return isinstance(value, expected_type)

    def summary(self) -> dict[str, Any]:
        """Generate a summary of all contract monitoring activity."""
        caller_faults = [f for f in self._faults if f.label == BlameLabel.CALLER]
        server_faults = [f for f in self._faults if f.label == BlameLabel.SERVER]
        return {
            "total_invocations": self._tool_invocations,
            "total_faults": len(self._faults),
            "caller_faults": len(caller_faults),
            "server_faults": len(server_faults),
            "verdict": "clean" if not self._faults else "violations_detected",
            "faults": [f.to_dict() for f in self._faults],
        }
