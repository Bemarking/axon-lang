"""Visual debugger for Axon flows."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4


@dataclass
class DebugBreakpoint:
    """A debugger breakpoint."""

    id: UUID = field(default_factory=uuid4)
    flow_id: UUID = uuid4()
    line_number: int = 0
    condition: str = ""  # optional breakpoint condition
    enabled: bool = True


@dataclass
class DebugSnapshot:
    """A snapshot of execution state."""

    id: UUID = field(default_factory=uuid4)
    flow_id: UUID = uuid4()
    execution_id: UUID = uuid4()
    timestamp: datetime = field(default_factory=datetime.utcnow)
    line_number: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    stack_trace: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)


class FlowDebugger:
    """Visual debugger for Axon flows."""

    def __init__(self):
        """Initialize debugger."""
        self.breakpoints: dict[UUID, DebugBreakpoint] = {}
        self.snapshots: list[DebugSnapshot] = []
        self.is_debugging = False

    def set_breakpoint(self, flow_id: UUID, line_number: int, condition: str = "") -> DebugBreakpoint:
        """Set a breakpoint in a flow."""
        bp = DebugBreakpoint(
            flow_id=flow_id,
            line_number=line_number,
            condition=condition,
            enabled=True,
        )
        self.breakpoints[bp.id] = bp
        return bp

    def remove_breakpoint(self, breakpoint_id: UUID) -> bool:
        """Remove a breakpoint."""
        if breakpoint_id in self.breakpoints:
            del self.breakpoints[breakpoint_id]
            return True
        return False

    def disable_breakpoint(self, breakpoint_id: UUID) -> bool:
        """Disable a breakpoint."""
        bp = self.breakpoints.get(breakpoint_id)
        if bp:
            bp.enabled = False
            return True
        return False

    def capture_snapshot(
        self,
        flow_id: UUID,
        execution_id: UUID,
        line_number: int,
        variables: dict[str, Any],
        stack_trace: list[str],
    ) -> DebugSnapshot:
        """Capture an execution snapshot at a breakpoint."""
        snapshot = DebugSnapshot(
            flow_id=flow_id,
            execution_id=execution_id,
            line_number=line_number,
            variables=variables,
            stack_trace=stack_trace,
        )
        # TODO: Store snapshot in database
        self.snapshots.append(snapshot)
        return snapshot

    def get_snapshots(self, execution_id: UUID) -> list[DebugSnapshot]:
        """Get all snapshots for an execution."""
        return [s for s in self.snapshots if s.execution_id == execution_id]

    async def step_into(self) -> Optional[DebugSnapshot]:
        """Step into the next instruction."""
        # TODO: Implement step-into logic
        return None

    async def step_over(self) -> Optional[DebugSnapshot]:
        """Step over the next instruction."""
        # TODO: Implement step-over logic
        return None

    async def continue_execution(self) -> Optional[DebugSnapshot]:
        """Continue execution until next breakpoint."""
        # TODO: Implement continue logic
        return None
