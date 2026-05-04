"""
Hierarchical supervision tree (Fase 16.j).

Real OTP gives you nested supervisors: a platform supervisor manages
tenant supervisors, which in turn manage daemon supervisors. This
module provides that layering on top of axon-lang's flat
`DaemonSupervisor`.

Topology:

    PlatformSupervisor (ONE_FOR_ONE — tenant supervisors are independent)
    ├── TenantSupervisor("acme")     (REST_FOR_ONE — daemons share state)
    │   ├── OrderDaemon
    │   ├── BillingDaemon
    │   └── AnalyticsDaemon
    ├── TenantSupervisor("globex")   (ONE_FOR_ALL — daemons share session)
    │   ├── ChatDaemon
    │   └── HandoffDaemon
    └── ...

Failures escalate up: a child supervisor's intensity-exceeded event
fires the parent's child-failure handler, which decides whether to
restart the failing child supervisor (taking ALL its daemons down)
or continue running siblings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Union

from axon.runtime.supervisor import DaemonSupervisor


# Forward-declared union for the discriminated children:
SupervisionChild = Union["SupervisionNode", DaemonSupervisor]


@dataclass
class SupervisionNode:
    """A node in the supervision tree.

    Each node owns either:
      * `children: list[SupervisionNode]` — internal node, escalation
        target for child failures
      * `supervisor: DaemonSupervisor` — leaf node owning a flat
        supervisor that manages real daemons.

    Both ARE NOT set simultaneously. The `start_all` / `stop_all`
    semantics propagate down the tree.
    """

    name: str
    parent: "SupervisionNode | None" = None
    children: list[SupervisionChild] = field(default_factory=list)
    supervisor: DaemonSupervisor | None = None
    # Optional callback fired when a child reports failure:
    # `await on_child_failure(child_name)`. Default: no-op.
    on_child_failure: Callable[[str], Awaitable[None]] | None = None

    def add_child(self, child: SupervisionChild) -> None:
        if isinstance(child, SupervisionNode):
            child.parent = self
        self.children.append(child)

    async def start_all(self) -> None:
        """Recursively start every supervisor in the subtree rooted
        at this node."""
        if self.supervisor is not None:
            await self.supervisor.start_all()
        for child in self.children:
            if isinstance(child, SupervisionNode):
                await child.start_all()
            else:
                await child.start_all()

    async def stop_all(self) -> None:
        """Recursively stop in reverse order (leaves first, root
        last) for graceful shutdown."""
        for child in reversed(self.children):
            if isinstance(child, SupervisionNode):
                await child.stop_all()
            else:
                await child.stop_all()
        if self.supervisor is not None:
            await self.supervisor.stop_all()

    async def report_failure(self, child_name: str) -> None:
        """Called by a child supervisor's hooks when it gives up on
        a daemon (intensity exceeded). Bubbles up to the parent's
        on_child_failure callback if registered, then up to the
        grandparent, etc."""
        if self.on_child_failure is not None:
            try:
                await self.on_child_failure(child_name)
            except Exception:
                pass
        if self.parent is not None:
            await self.parent.report_failure(f"{self.name}/{child_name}")


class SupervisionTree:
    """Convenience wrapper around a tree rooted at a single
    `SupervisionNode`. Provides `start_all`, `stop_all`, and a
    factory for the common Platform → Tenant → DaemonSupervisor
    layout.
    """

    def __init__(self, root: SupervisionNode) -> None:
        self.root = root

    async def start_all(self) -> None:
        await self.root.start_all()

    async def stop_all(self) -> None:
        await self.root.stop_all()

    @classmethod
    def platform_tenant_layout(
        cls,
        *,
        platform_name: str = "platform",
        tenants: dict[str, DaemonSupervisor] | None = None,
    ) -> "SupervisionTree":
        """Build a 2-level tree: platform → per-tenant supervisor.

        `tenants` maps tenant_id → an already-constructed
        `DaemonSupervisor` (typically returned by
        `make_enterprise_supervisor` with the right tenant_resolver).
        """
        root = SupervisionNode(name=platform_name)
        for tenant_id, supervisor in (tenants or {}).items():
            child = SupervisionNode(
                name=tenant_id,
                supervisor=supervisor,
            )
            root.add_child(child)
        return cls(root)
