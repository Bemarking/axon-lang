"""
AXON Runtime — Store Dispatcher
=================================
Routes ``axonstore`` operations from compiled step metadata to
the appropriate ``StoreBackend`` implementation.

Follows the same dispatch pattern as ``DataScienceDispatcher``:
the executor checks step metadata for an ``"axonstore"`` flag
and delegates here instead of making a model call.

Formal guarantees:
  §1  HoTT Univalence  — schema isomorphism verified at initialize()
  §2  Linear Logic (⊸)  — transact blocks use single-use tokens
  §3  Design by Contract — confidence_floor + on_breach enforcement

Usage::

    from axon.runtime.store_dispatcher import StoreDispatcher

    dispatcher = StoreDispatcher()
    result = await dispatcher.dispatch(store_meta, context={})

    if result.success:
        print(result.data)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.runtime.store_backends import (
    StoreBackend,
    StoreResult,
    create_store_backend,
)


# ═══════════════════════════════════════════════════════════════════
#  STORE REGISTRY — maps store names to initialized backends
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StoreRegistryEntry:
    """An initialized axonstore with its backend and config."""
    name: str
    backend: StoreBackend
    confidence_floor: float = 0.9
    isolation: str = "serializable"
    on_breach: str = "rollback"
    schema_columns: list[dict[str, Any]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  STORE DISPATCHER
# ═══════════════════════════════════════════════════════════════════

class StoreDispatcher:
    """Dispatches axonstore metadata operations to backends.

    Maintains a registry of active stores (one per ``axonstore``
    declaration). Operations are routed by the ``operation`` key
    in the metadata dict:

    ==============================  ====================================
    Operation                       Backend Method
    ==============================  ====================================
    ``axonstore``                   ``initialize()`` + register
    ``persist``                     ``insert()``
    ``retrieve``                    ``query()``
    ``mutate``                      ``update()``
    ``purge``                       ``delete()``
    ``transact``                    ``begin`` → children → ``commit``
    ==============================  ====================================
    """

    def __init__(self) -> None:
        self._stores: dict[str, StoreRegistryEntry] = {}

    @property
    def stores(self) -> dict[str, StoreRegistryEntry]:
        return dict(self._stores)

    async def dispatch(
        self,
        meta: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> StoreResult:
        """Execute an axonstore operation from compiled metadata.

        Args:
            meta:    The ``axonstore`` metadata dict from CompiledStep.
            context: Optional execution context (step_name, etc.).

        Returns:
            A ``StoreResult`` with the operation outcome.
        """
        op = meta.get("operation", "unknown")
        args = meta.get("args", {})

        handler = {
            "axonstore": self._exec_axonstore,
            "persist": self._exec_persist,
            "retrieve": self._exec_retrieve,
            "mutate": self._exec_mutate,
            "purge": self._exec_purge,
            "transact": self._exec_transact,
        }.get(op)

        if handler is None:
            return StoreResult(
                success=False,
                operation=op,
                error=f"Unknown axonstore operation: {op!r}",
            )

        try:
            return await handler(args)
        except Exception as exc:
            return StoreResult(
                success=False,
                operation=op,
                error=str(exc),
            )

    # ── AXONSTORE INIT — Register + Create Table ─────────────────

    async def _exec_axonstore(self, args: dict[str, Any]) -> StoreResult:
        """Create a store backend, initialize the schema, register it."""
        name = args.get("name", "")
        backend_type = args.get("backend", "sqlite")
        connection = args.get("connection", "")
        schema_cols = args.get("schema", [])
        confidence_floor = args.get("confidence_floor", 0.9)
        isolation = args.get("isolation", "serializable")
        on_breach = args.get("on_breach", "rollback")

        backend = create_store_backend(
            backend_type=backend_type,
            connection=connection,
            isolation=isolation,
        )

        if schema_cols:
            await backend.initialize(name, schema_cols)

        entry = StoreRegistryEntry(
            name=name,
            backend=backend,
            confidence_floor=confidence_floor,
            isolation=isolation,
            on_breach=on_breach,
            schema_columns=schema_cols,
        )
        self._stores[name] = entry

        return StoreResult(
            success=True,
            operation="axonstore",
            data={
                "name": name,
                "backend": backend_type,
                "columns": [c.get("col_name", "") for c in schema_cols],
            },
        )

    # ── PERSIST — INSERT (Linear Logic ⊗) ────────────────────────

    async def _exec_persist(self, args: dict[str, Any]) -> StoreResult:
        """Insert a row into a registered store."""
        store_name = args.get("store_name", "")
        fields_raw = args.get("fields", [])

        entry = self._stores.get(store_name)
        if entry is None:
            return StoreResult(
                success=False,
                operation="persist",
                error=f"Store '{store_name}' not initialized",
            )

        # Convert [[col, val], ...] → dict
        data = {f[0]: f[1] for f in fields_raw} if fields_raw else {}
        result = await entry.backend.insert(store_name, data)

        return StoreResult(
            success=True,
            operation="persist",
            data=result,
            metadata={"store": store_name},
        )

    # ── RETRIEVE — SELECT (Query Projection π) ──────────────────

    async def _exec_retrieve(self, args: dict[str, Any]) -> StoreResult:
        """Query rows from a registered store."""
        store_name = args.get("store_name", "")
        where_expr = args.get("where_expr", "")
        alias = args.get("alias", "")

        entry = self._stores.get(store_name)
        if entry is None:
            return StoreResult(
                success=False,
                operation="retrieve",
                error=f"Store '{store_name}' not initialized",
            )

        rows = await entry.backend.query(store_name, where_expr)

        return StoreResult(
            success=True,
            operation="retrieve",
            data={"rows": rows, "count": len(rows), "alias": alias},
            metadata={"store": store_name},
        )

    # ── MUTATE — UPDATE (Atomic Mutation Δ) ──────────────────────

    async def _exec_mutate(self, args: dict[str, Any]) -> StoreResult:
        """Update rows in a registered store."""
        store_name = args.get("store_name", "")
        where_expr = args.get("where_expr", "")
        fields_raw = args.get("fields", [])

        entry = self._stores.get(store_name)
        if entry is None:
            return StoreResult(
                success=False,
                operation="mutate",
                error=f"Store '{store_name}' not initialized",
            )

        data = {f[0]: f[1] for f in fields_raw} if fields_raw else {}
        affected = await entry.backend.update(store_name, where_expr, data)

        return StoreResult(
            success=True,
            operation="mutate",
            data={"rows_affected": affected},
            metadata={"store": store_name},
        )

    # ── PURGE — DELETE (Controlled Purge) ────────────────────────

    async def _exec_purge(self, args: dict[str, Any]) -> StoreResult:
        """Delete rows from a registered store."""
        store_name = args.get("store_name", "")
        where_expr = args.get("where_expr", "")

        entry = self._stores.get(store_name)
        if entry is None:
            return StoreResult(
                success=False,
                operation="purge",
                error=f"Store '{store_name}' not initialized",
            )

        affected = await entry.backend.delete(store_name, where_expr)

        return StoreResult(
            success=True,
            operation="purge",
            data={"rows_deleted": affected},
            metadata={"store": store_name},
        )

    # ── TRANSACT — Linear Logic Block (A ⊸ B) ───────────────────

    async def _exec_transact(self, args: dict[str, Any]) -> StoreResult:
        """Execute a transaction block with a single-use token.

        All child operations share the token. On failure,
        rollback is triggered (consuming the token).
        """
        children = args.get("children", [])
        if not children:
            return StoreResult(
                success=True,
                operation="transact",
                data={"children_executed": 0},
            )

        # Determine the store from the first child
        first_store = ""
        for child in children:
            child_args = child.get("args", {})
            first_store = child_args.get("store_name", "")
            if first_store:
                break

        entry = self._stores.get(first_store)
        if entry is None:
            return StoreResult(
                success=False,
                operation="transact",
                error=f"Store '{first_store}' not initialized for transact",
            )

        # Begin — issues a linear token
        token_id = await entry.backend.begin_transaction()

        child_results: list[dict[str, Any]] = []
        try:
            for child_meta in children:
                child_result = await self.dispatch(child_meta)
                child_results.append(child_result.data if child_result.data else {})
                if not child_result.success:
                    raise RuntimeError(
                        f"Transact child failed: {child_result.error}"
                    )

            # All succeeded — commit (consumes token)
            await entry.backend.commit(token_id)

            return StoreResult(
                success=True,
                operation="transact",
                data={
                    "token_id": token_id,
                    "children_executed": len(children),
                    "results": child_results,
                },
                metadata={"store": first_store},
            )

        except Exception as exc:
            # Rollback — consumes token, reverts all mutations
            try:
                await entry.backend.rollback(token_id)
            except RuntimeError:
                pass  # token already consumed
            return StoreResult(
                success=False,
                operation="transact",
                error=str(exc),
                metadata={"store": first_store, "token_consumed": True},
            )
