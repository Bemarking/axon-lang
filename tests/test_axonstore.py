"""
Test Suite — AxonStore Primitive
===================================
Validates the ``axonstore`` primitive across every compiler
and runtime layer:

  §1  Lexer            — 7 new token types
  §2  AST Nodes        — 8 dataclass nodes
  §3  Parser           — Definition + CRUD + transact
  §4  Type Checker     — Valid/invalid schemas & constraints
  §5  IR Generator     — Lowering to IR nodes
  §6  Backend          — CompiledStep metadata emission
  §7  Store Dispatcher — Full CRUD dispatch cycle
  §8  SQLite Backend   — Real SQL operations
  §9  Linear Logic     — Single-use transaction tokens
  §10 Integration      — End-to-end pipeline
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import pytest

from axon.compiler.tokens import TokenType
from axon.compiler.lexer import Lexer
from axon.compiler.ast_nodes import (
    AxonStoreDefinition,
    MutateNode,
    PersistNode,
    PurgeNode,
    RetrieveNode,
    StoreColumnNode,
    StoreSchemaNode,
    TransactNode,
)
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_nodes import (
    IRAxonStore,
    IRMutate,
    IRPersist,
    IRProgram,
    IRPurge,
    IRRetrieve,
    IRStoreColumn,
    IRStoreSchema,
    IRTransact,
)
from axon.compiler.ir_generator import IRGenerator
from axon.backends.base_backend import CompiledStep
from axon.runtime.store_backends import StoreResult, create_store_backend
from axon.runtime.store_backends.sqlite_backend import SQLiteStoreBackend
from axon.runtime.store_dispatcher import StoreDispatcher, StoreRegistryEntry


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _lex(source: str) -> list:
    return Lexer(source).tokenize()


def _parse(source: str):
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def _check(source: str) -> list:
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return TypeChecker(tree).check()


def _generate(source: str) -> IRProgram:
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return IRGenerator().generate(tree)


def _run_async(coro):
    """Run an async coroutine synchronously for tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
#  §1 — LEXER
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreLexer:
    """Verify that all 7 axonstore keywords produce correct tokens."""

    def test_axonstore_keyword_token(self):
        tokens = _lex("axonstore")
        kw = [t for t in tokens if t.type == TokenType.AXONSTORE]
        assert len(kw) == 1

    def test_schema_keyword_token(self):
        tokens = _lex("schema")
        kw = [t for t in tokens if t.type == TokenType.SCHEMA]
        assert len(kw) == 1

    def test_persist_keyword_token(self):
        tokens = _lex("persist")
        kw = [t for t in tokens if t.type == TokenType.PERSIST]
        assert len(kw) == 1

    def test_retrieve_keyword_token(self):
        tokens = _lex("retrieve")
        kw = [t for t in tokens if t.type == TokenType.RETRIEVE]
        assert len(kw) == 1

    def test_mutate_keyword_token(self):
        tokens = _lex("mutate")
        kw = [t for t in tokens if t.type == TokenType.MUTATE]
        assert len(kw) == 1

    def test_purge_keyword_token(self):
        tokens = _lex("purge")
        kw = [t for t in tokens if t.type == TokenType.PURGE]
        assert len(kw) == 1

    def test_transact_keyword_token(self):
        tokens = _lex("transact")
        kw = [t for t in tokens if t.type == TokenType.TRANSACT]
        assert len(kw) == 1

    def test_all_keywords_in_one_line(self):
        src = "axonstore schema persist retrieve mutate purge transact"
        tokens = _lex(src)
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert TokenType.AXONSTORE in types
        assert TokenType.SCHEMA in types
        assert TokenType.PERSIST in types
        assert TokenType.RETRIEVE in types
        assert TokenType.MUTATE in types
        assert TokenType.PURGE in types
        assert TokenType.TRANSACT in types

    def test_axonstore_not_identifier(self):
        tokens = _lex("axonstore")
        assert tokens[0].type != TokenType.IDENTIFIER


# ═══════════════════════════════════════════════════════════════════
#  §2 — AST NODES
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreASTNodes:
    """Verify AST node dataclass construction."""

    def test_store_column_node(self):
        col = StoreColumnNode(
            col_name="id", col_type="integer",
            primary_key=True, auto_increment=True,
        )
        assert col.col_name == "id"
        assert col.primary_key is True

    def test_store_schema_node(self):
        col = StoreColumnNode(col_name="name", col_type="text")
        schema = StoreSchemaNode(columns=[col])
        assert len(schema.columns) == 1

    def test_axonstore_definition(self):
        defn = AxonStoreDefinition(
            name="Products",
            backend="sqlite",
            schema=StoreSchemaNode(columns=[]),
        )
        assert defn.name == "Products"
        assert defn.backend == "sqlite"

    def test_persist_node(self):
        node = PersistNode(store_name="Users", fields={"name": "Alice"})
        assert node.store_name == "Users"

    def test_retrieve_node(self):
        node = RetrieveNode(store_name="Users", where_expr="active = true")
        assert node.where_expr == "active = true"

    def test_mutate_node(self):
        node = MutateNode(
            store_name="Users",
            where_expr="id = 1",
            fields={"name": "Bob"},
        )
        assert node.fields["name"] == "Bob"

    def test_purge_node(self):
        node = PurgeNode(store_name="Users", where_expr="id = 1")
        assert node.store_name == "Users"

    def test_transact_node(self):
        inner = PersistNode(store_name="Users", fields={"name": "Eve"})
        node = TransactNode(body=[inner])
        assert len(node.body) == 1

    def test_axonstore_default_values(self):
        defn = AxonStoreDefinition(name="T", backend="sqlite")
        assert defn.confidence_floor == 0.9
        assert defn.isolation == "serializable"
        assert defn.on_breach == "rollback"


# ═══════════════════════════════════════════════════════════════════
#  §3 — PARSER
# ═══════════════════════════════════════════════════════════════════

_MINIMAL_STORE = """
axonstore Inventory {
  backend: sqlite
  schema {
    id: integer primary_key auto_increment
    name: text not_null
  }
}
"""

_FULL_STORE = """
axonstore Products {
  backend: postgresql
  connection: "postgresql://localhost/db"
  confidence_floor: 0.95
  isolation: serializable
  on_breach: rollback
  schema {
    id: integer primary_key auto_increment
    title: text not_null unique
    price: real
    stock: integer
  }
}
"""

_PERSIST_SRC = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    email: text
  }
}
persist into Users {
  email: "test@example.com"
}
"""

_RETRIEVE_SRC = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
retrieve from Users where "id > 0" as results
"""

_MUTATE_SRC = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    name: text
  }
}
mutate Users where "id = 1" {
  name: "Updated"
}
"""

_PURGE_SRC = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
purge from Users where "id = 999"
"""

_TRANSACT_SRC = """
axonstore Accounts {
  backend: sqlite
  schema {
    id: integer primary_key
    balance: real
  }
}
transact {
  persist into Accounts {
    balance: 100.0
  }
}
"""


class TestAxonStoreParser:
    """Parser tests for axonstore definitions and CRUD ops."""

    def test_minimal_store_parses(self):
        tree = _parse(_MINIMAL_STORE)
        stores = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)]
        assert len(stores) == 1
        assert stores[0].name == "Inventory"

    def test_minimal_store_schema_columns(self):
        tree = _parse(_MINIMAL_STORE)
        store = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)][0]
        assert len(store.schema.columns) == 2
        assert store.schema.columns[0].col_name == "id"
        assert store.schema.columns[0].primary_key is True
        assert store.schema.columns[1].col_name == "name"
        assert store.schema.columns[1].not_null is True

    def test_full_store_all_fields(self):
        tree = _parse(_FULL_STORE)
        store = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)][0]
        assert store.name == "Products"
        assert store.backend == "postgresql"
        assert store.confidence_floor == 0.95
        assert store.isolation == "serializable"
        assert store.on_breach == "rollback"
        assert len(store.schema.columns) == 4

    def test_full_store_connection_string(self):
        tree = _parse(_FULL_STORE)
        store = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)][0]
        assert store.connection == "postgresql://localhost/db"

    def test_persist_parses(self):
        tree = _parse(_PERSIST_SRC)
        persists = [d for d in tree.declarations if isinstance(d, PersistNode)]
        assert len(persists) == 1
        assert persists[0].store_name == "Users"

    def test_persist_fields(self):
        tree = _parse(_PERSIST_SRC)
        p = [d for d in tree.declarations if isinstance(d, PersistNode)][0]
        assert "email" in p.fields
        assert p.fields["email"] == "test@example.com"

    def test_retrieve_parses(self):
        tree = _parse(_RETRIEVE_SRC)
        retrieves = [d for d in tree.declarations if isinstance(d, RetrieveNode)]
        assert len(retrieves) == 1
        assert retrieves[0].store_name == "Users"
        assert retrieves[0].where_expr == "id > 0"
        assert retrieves[0].alias == "results"

    def test_mutate_parses(self):
        tree = _parse(_MUTATE_SRC)
        mutates = [d for d in tree.declarations if isinstance(d, MutateNode)]
        assert len(mutates) == 1
        assert mutates[0].store_name == "Users"
        assert mutates[0].where_expr == "id = 1"
        assert mutates[0].fields["name"] == "Updated"

    def test_purge_parses(self):
        tree = _parse(_PURGE_SRC)
        purges = [d for d in tree.declarations if isinstance(d, PurgeNode)]
        assert len(purges) == 1
        assert purges[0].store_name == "Users"
        assert purges[0].where_expr == "id = 999"

    def test_transact_parses(self):
        tree = _parse(_TRANSACT_SRC)
        tx = [d for d in tree.declarations if isinstance(d, TransactNode)]
        assert len(tx) == 1
        assert len(tx[0].body) >= 1
        assert isinstance(tx[0].body[0], PersistNode)

    def test_schema_column_unique(self):
        tree = _parse(_FULL_STORE)
        store = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)][0]
        title_col = store.schema.columns[1]
        assert title_col.unique is True

    def test_schema_column_auto_increment(self):
        tree = _parse(_MINIMAL_STORE)
        store = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)][0]
        id_col = store.schema.columns[0]
        assert id_col.auto_increment is True


# ═══════════════════════════════════════════════════════════════════
#  §4 — TYPE CHECKER
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreTypeCheckerValid:
    """Valid axonstore declarations should produce zero errors."""

    def test_minimal_store_valid(self):
        errors = _check(_MINIMAL_STORE)
        store_errors = [e for e in errors if "axonstore" in str(e).lower() or "store" in str(e).lower()]
        assert len(store_errors) == 0

    def test_full_store_valid(self):
        errors = _check(_FULL_STORE)
        store_errors = [e for e in errors if "axonstore" in str(e).lower() or "store" in str(e).lower()]
        assert len(store_errors) == 0

    def test_persist_valid(self):
        errors = _check(_PERSIST_SRC)
        persist_errors = [e for e in errors if "persist" in str(e).lower()]
        assert len(persist_errors) == 0


class TestAxonStoreTypeCheckerInvalid:
    """Invalid configurations should trigger type-check errors."""

    def test_invalid_backend_type(self):
        src = """
axonstore Bad {
  backend: mongodb
  schema {
    id: integer primary_key
  }
}
"""
        errors = _check(src)
        backend_errors = [e for e in errors if "backend" in str(e).lower()]
        assert len(backend_errors) >= 1

    def test_invalid_isolation_level(self):
        src = """
axonstore Bad {
  backend: sqlite
  isolation: eventual
  schema {
    id: integer primary_key
  }
}
"""
        errors = _check(src)
        iso_errors = [e for e in errors if "isolation" in str(e).lower()]
        assert len(iso_errors) >= 1

    def test_invalid_on_breach(self):
        src = """
axonstore Bad {
  backend: sqlite
  on_breach: ignore
  schema {
    id: integer primary_key
  }
}
"""
        errors = _check(src)
        breach_errors = [e for e in errors if "on_breach" in str(e).lower()]
        assert len(breach_errors) >= 1

    def test_empty_schema(self):
        src = """
axonstore Bad {
  backend: sqlite
  schema {
  }
}
"""
        errors = _check(src)
        schema_errors = [e for e in errors if "schema" in str(e).lower() or "column" in str(e).lower()]
        assert len(schema_errors) >= 1

    def test_confidence_floor_out_of_range(self):
        src = """
axonstore Bad {
  backend: sqlite
  confidence_floor: 1.5
  schema {
    id: integer primary_key
  }
}
"""
        errors = _check(src)
        cf_errors = [e for e in errors if "confidence" in str(e).lower()]
        assert len(cf_errors) >= 1


# ═══════════════════════════════════════════════════════════════════
#  §5 — IR GENERATOR
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreIRGenerator:
    """IR generation from axonstore AST."""

    def test_ir_axonstore_spec(self):
        ir = _generate(_MINIMAL_STORE)
        assert len(ir.axonstore_specs) >= 1
        spec = ir.axonstore_specs[0]
        assert isinstance(spec, IRAxonStore)
        assert spec.name == "Inventory"

    def test_ir_schema_columns(self):
        ir = _generate(_MINIMAL_STORE)
        spec = ir.axonstore_specs[0]
        assert isinstance(spec.schema, IRStoreSchema)
        assert len(spec.schema.columns) == 2

    def test_ir_column_details(self):
        ir = _generate(_MINIMAL_STORE)
        col = ir.axonstore_specs[0].schema.columns[0]
        assert isinstance(col, IRStoreColumn)
        assert col.col_name == "id"
        assert col.col_type == "integer"
        assert col.primary_key is True

    def test_ir_persist_generated(self):
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    email: text
  }
}
flow TestFlow() -> Text {
    persist into Users {
      email: "test@example.com"
    }
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        persist_steps = [s for s in flow.steps if isinstance(s, IRPersist)]
        assert len(persist_steps) == 1
        assert persist_steps[0].store_name == "Users"

    def test_ir_persist_fields(self):
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    email: text
  }
}
flow TestFlow() -> Text {
    persist into Users {
      email: "test@example.com"
    }
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        p = [s for s in flow.steps if isinstance(s, IRPersist)][0]
        fields = dict(p.fields)
        assert "email" in fields

    def test_ir_retrieve_generated(self):
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
flow TestFlow() -> Text {
    retrieve from Users where "id > 0" as results
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        rets = [s for s in flow.steps if isinstance(s, IRRetrieve)]
        assert len(rets) == 1
        assert rets[0].where_expr == "id > 0"
        assert rets[0].alias == "results"

    def test_ir_mutate_generated(self):
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    name: text
  }
}
flow TestFlow() -> Text {
    mutate Users where "id = 1" {
      name: "Updated"
    }
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        muts = [s for s in flow.steps if isinstance(s, IRMutate)]
        assert len(muts) == 1
        assert muts[0].where_expr == "id = 1"

    def test_ir_purge_generated(self):
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
flow TestFlow() -> Text {
    purge from Users where "id = 999"
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        purges = [s for s in flow.steps if isinstance(s, IRPurge)]
        assert len(purges) == 1
        assert purges[0].where_expr == "id = 999"

    def test_ir_transact_generated(self):
        src = '''
axonstore Accounts {
  backend: sqlite
  schema {
    id: integer primary_key
    balance: real
  }
}
flow TestFlow() -> Text {
    transact {
      persist into Accounts {
        balance: 100.0
      }
    }
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        flow = ir.flows[0]
        txs = [s for s in flow.steps if isinstance(s, IRTransact)]
        assert len(txs) == 1
        assert len(txs[0].children) >= 1

    def test_ir_full_store_fields(self):
        ir = _generate(_FULL_STORE)
        spec = ir.axonstore_specs[0]
        assert spec.backend == "postgresql"
        assert spec.confidence_floor == 0.95
        assert spec.isolation == "serializable"


# ═══════════════════════════════════════════════════════════════════
#  §6 — BACKEND COMPILATION
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreBackend:
    """Verify backend compiles axonstore IR to CompiledStep metadata."""

    _BACKEND_PREFIX = """
persona StoreAgent { role: "store agent" }
context StoreCtx { domain: "persistence" }
"""
    _BACKEND_SUFFIX = """
run TestFlow() as StoreAgent within StoreCtx
"""

    def _compile(self, source: str):
        from axon.backends.anthropic_backend import AnthropicBackend
        full_src = self._BACKEND_PREFIX + source + self._BACKEND_SUFFIX
        ir = _generate(full_src)
        backend = AnthropicBackend()
        return backend.compile_program(ir)

    def test_axonstore_metadata(self):
        src = _MINIMAL_STORE + """
flow TestFlow() -> Text {
    step done {
        ask: "done"
        output: Text
    }
}
"""
        compiled = self._compile(src)
        all_steps = []
        for unit in compiled.execution_units:
            all_steps.extend(unit.steps)
        store_steps = [s for s in all_steps if s.metadata.get("axonstore")]
        assert len(store_steps) >= 1
        meta = store_steps[0].metadata["axonstore"]
        assert meta["operation"] == "axonstore"

    def test_persist_metadata(self):
        src = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    email: text
  }
}
flow TestFlow() -> Text {
    persist into Users {
      email: "test@example.com"
    }
    step done {
        ask: "done"
        output: Text
    }
}
"""
        compiled = self._compile(src)
        all_steps = []
        for unit in compiled.execution_units:
            all_steps.extend(unit.steps)
        persist_steps = [
            s for s in all_steps
            if s.metadata.get("axonstore", {}).get("operation") == "persist"
        ]
        assert len(persist_steps) >= 1

    def test_retrieve_metadata(self):
        src = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
flow TestFlow() -> Text {
    retrieve from Users where "id > 0" as results
    step done {
        ask: "done"
        output: Text
    }
}
"""
        compiled = self._compile(src)
        all_steps = []
        for unit in compiled.execution_units:
            all_steps.extend(unit.steps)
        ret_steps = [
            s for s in all_steps
            if s.metadata.get("axonstore", {}).get("operation") == "retrieve"
        ]
        assert len(ret_steps) >= 1

    def test_mutate_metadata(self):
        src = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    name: text
  }
}
flow TestFlow() -> Text {
    mutate Users where "id = 1" {
      name: "Updated"
    }
    step done {
        ask: "done"
        output: Text
    }
}
"""
        compiled = self._compile(src)
        all_steps = []
        for unit in compiled.execution_units:
            all_steps.extend(unit.steps)
        mut_steps = [
            s for s in all_steps
            if s.metadata.get("axonstore", {}).get("operation") == "mutate"
        ]
        assert len(mut_steps) >= 1

    def test_purge_metadata(self):
        src = """
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
  }
}
flow TestFlow() -> Text {
    purge from Users where "id = 999"
    step done {
        ask: "done"
        output: Text
    }
}
"""
        compiled = self._compile(src)
        all_steps = []
        for unit in compiled.execution_units:
            all_steps.extend(unit.steps)
        purge_steps = [
            s for s in all_steps
            if s.metadata.get("axonstore", {}).get("operation") == "purge"
        ]
        assert len(purge_steps) >= 1


# ═══════════════════════════════════════════════════════════════════
#  §7 — STORE DISPATCHER
# ═══════════════════════════════════════════════════════════════════

class TestStoreDispatcher:
    """Test the central StoreDispatcher."""

    def _make_dispatcher_with_store(self) -> StoreDispatcher:
        """Creates a dispatcher with a registered in-memory SQLite store."""
        dispatcher = StoreDispatcher()
        meta = {
            "operation": "axonstore",
            "args": {
                "name": "TestStore",
                "backend": "sqlite",
                "connection": ":memory:",
                "schema": [
                    {"col_name": "id", "col_type": "integer", "primary_key": True},
                    {"col_name": "name", "col_type": "text", "not_null": True},
                    {"col_name": "score", "col_type": "real"},
                ],
            },
        }
        result = _run_async(dispatcher.dispatch(meta))
        assert result.success, f"Store init failed: {result.error}"
        return dispatcher

    def test_dispatch_unknown_operation(self):
        d = StoreDispatcher()
        result = _run_async(d.dispatch({"operation": "unknown", "args": {}}))
        assert not result.success
        assert "Unknown" in result.error

    def test_init_store(self):
        d = self._make_dispatcher_with_store()
        assert "TestStore" in d.stores

    def test_init_store_result(self):
        d = StoreDispatcher()
        meta = {
            "operation": "axonstore",
            "args": {
                "name": "Demo",
                "backend": "sqlite",
                "connection": ":memory:",
                "schema": [
                    {"col_name": "id", "col_type": "integer", "primary_key": True},
                ],
            },
        }
        result = _run_async(d.dispatch(meta))
        assert result.success
        assert result.data["name"] == "Demo"
        assert result.data["backend"] == "sqlite"

    def test_persist_dispatch(self):
        d = self._make_dispatcher_with_store()
        meta = {
            "operation": "persist",
            "args": {
                "store_name": "TestStore",
                "fields": [["name", "Alice"], ["score", 95.5]],
            },
        }
        result = _run_async(d.dispatch(meta))
        assert result.success
        assert result.operation == "persist"

    def test_retrieve_dispatch(self):
        d = self._make_dispatcher_with_store()
        # Insert first
        _run_async(d.dispatch({
            "operation": "persist",
            "args": {"store_name": "TestStore", "fields": [["name", "Bob"], ["score", 80.0]]},
        }))
        # Retrieve
        result = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "TestStore", "where_expr": "", "alias": "all"},
        }))
        assert result.success
        assert result.data["count"] >= 1

    def test_mutate_dispatch(self):
        d = self._make_dispatcher_with_store()
        _run_async(d.dispatch({
            "operation": "persist",
            "args": {"store_name": "TestStore", "fields": [["name", "Charlie"], ["score", 70.0]]},
        }))
        result = _run_async(d.dispatch({
            "operation": "mutate",
            "args": {
                "store_name": "TestStore",
                "where_expr": "name = 'Charlie'",
                "fields": [["score", 99.0]],
            },
        }))
        assert result.success
        assert result.data["rows_affected"] >= 1

    def test_purge_dispatch(self):
        d = self._make_dispatcher_with_store()
        _run_async(d.dispatch({
            "operation": "persist",
            "args": {"store_name": "TestStore", "fields": [["name", "ToDelete"], ["score", 0]]},
        }))
        result = _run_async(d.dispatch({
            "operation": "purge",
            "args": {"store_name": "TestStore", "where_expr": "name = 'ToDelete'"},
        }))
        assert result.success
        assert result.data["rows_deleted"] >= 1

    def test_persist_into_nonexistent_store(self):
        d = StoreDispatcher()
        result = _run_async(d.dispatch({
            "operation": "persist",
            "args": {"store_name": "NoSuchStore", "fields": []},
        }))
        assert not result.success
        assert "not initialized" in result.error

    def test_retrieve_from_nonexistent_store(self):
        d = StoreDispatcher()
        result = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "NoSuchStore"},
        }))
        assert not result.success

    def test_mutate_nonexistent_store(self):
        d = StoreDispatcher()
        result = _run_async(d.dispatch({
            "operation": "mutate",
            "args": {"store_name": "NoSuchStore", "fields": []},
        }))
        assert not result.success

    def test_purge_nonexistent_store(self):
        d = StoreDispatcher()
        result = _run_async(d.dispatch({
            "operation": "purge",
            "args": {"store_name": "NoSuchStore"},
        }))
        assert not result.success


# ═══════════════════════════════════════════════════════════════════
#  §8 — SQLITE BACKEND (Real SQL)
# ═══════════════════════════════════════════════════════════════════

class TestSQLiteBackend:
    """Real SQLite CRUD operations."""

    def _make_backend(self) -> SQLiteStoreBackend:
        b = SQLiteStoreBackend(connection=":memory:")
        _run_async(b.initialize("Items", [
            {"col_name": "id", "col_type": "integer", "primary_key": True, "auto_increment": True},
            {"col_name": "title", "col_type": "text", "not_null": True},
            {"col_name": "price", "col_type": "real"},
        ]))
        return b

    def test_initialize_creates_table(self):
        b = self._make_backend()
        # If we get here without exception, table was created
        assert b is not None

    def test_insert_and_query(self):
        b = self._make_backend()
        _run_async(b.insert("Items", {"title": "Widget", "price": 9.99}))
        rows = _run_async(b.query("Items", ""))
        assert len(rows) == 1
        assert rows[0]["title"] == "Widget"

    def test_insert_multiple_rows(self):
        b = self._make_backend()
        _run_async(b.insert("Items", {"title": "A", "price": 1.0}))
        _run_async(b.insert("Items", {"title": "B", "price": 2.0}))
        _run_async(b.insert("Items", {"title": "C", "price": 3.0}))
        rows = _run_async(b.query("Items", ""))
        assert len(rows) == 3

    def test_query_with_where(self):
        b = self._make_backend()
        _run_async(b.insert("Items", {"title": "Cheap", "price": 1.0}))
        _run_async(b.insert("Items", {"title": "Expensive", "price": 100.0}))
        rows = _run_async(b.query("Items", "price > 50"))
        assert len(rows) == 1
        assert rows[0]["title"] == "Expensive"

    def test_update_row(self):
        b = self._make_backend()
        _run_async(b.insert("Items", {"title": "Old", "price": 5.0}))
        affected = _run_async(b.update("Items", "title = 'Old'", {"title": "New"}))
        assert affected == 1
        rows = _run_async(b.query("Items", "title = 'New'"))
        assert len(rows) == 1

    def test_delete_row(self):
        b = self._make_backend()
        _run_async(b.insert("Items", {"title": "Gone", "price": 0.0}))
        deleted = _run_async(b.delete("Items", "title = 'Gone'"))
        assert deleted == 1
        rows = _run_async(b.query("Items", ""))
        assert len(rows) == 0

    def test_delete_no_match(self):
        b = self._make_backend()
        deleted = _run_async(b.delete("Items", "title = 'Nothing'"))
        assert deleted == 0

    def test_update_no_match(self):
        b = self._make_backend()
        affected = _run_async(b.update("Items", "id = 999", {"title": "Nope"}))
        assert affected == 0

    def test_close_backend(self):
        b = self._make_backend()
        _run_async(b.close())
        # After close, connection should be None
        assert b._conn is None


# ═══════════════════════════════════════════════════════════════════
#  §9 — LINEAR LOGIC TRANSACTIONS
# ═══════════════════════════════════════════════════════════════════

class TestLinearLogicTokens:
    """Transaction tokens must be single-use (A ⊸ B)."""

    def _make_backend(self) -> SQLiteStoreBackend:
        b = SQLiteStoreBackend(connection=":memory:")
        _run_async(b.initialize("Ledger", [
            {"col_name": "id", "col_type": "integer", "primary_key": True, "auto_increment": True},
            {"col_name": "amount", "col_type": "real"},
        ]))
        return b

    def test_begin_returns_token(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        assert isinstance(token, str)
        assert len(token) > 0

    def test_commit_consumes_token(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.commit(token))
        # Second commit with same token must fail
        with pytest.raises(RuntimeError, match="consumed|Invalid"):
            _run_async(b.commit(token))

    def test_rollback_consumes_token(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.rollback(token))
        with pytest.raises(RuntimeError, match="consumed|Invalid"):
            _run_async(b.rollback(token))

    def test_commit_then_rollback_fails(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.commit(token))
        with pytest.raises(RuntimeError):
            _run_async(b.rollback(token))

    def test_rollback_then_commit_fails(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.rollback(token))
        with pytest.raises(RuntimeError):
            _run_async(b.commit(token))

    def test_invalid_token_commit(self):
        b = self._make_backend()
        with pytest.raises(RuntimeError):
            _run_async(b.commit("fake-token-12345"))

    def test_invalid_token_rollback(self):
        b = self._make_backend()
        with pytest.raises(RuntimeError):
            _run_async(b.rollback("fake-token-12345"))

    def test_transaction_insert_commit(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.insert("Ledger", {"amount": 50.0}))
        _run_async(b.commit(token))
        rows = _run_async(b.query("Ledger", ""))
        assert len(rows) == 1

    def test_transaction_insert_rollback(self):
        b = self._make_backend()
        token = _run_async(b.begin_transaction())
        _run_async(b.insert("Ledger", {"amount": 50.0}))
        _run_async(b.rollback(token))
        rows = _run_async(b.query("Ledger", ""))
        # After rollback, row should be gone
        assert len(rows) == 0


# ═══════════════════════════════════════════════════════════════════
#  §10 — TRANSACT DISPATCH (Dispatcher level)
# ═══════════════════════════════════════════════════════════════════

class TestTransactDispatch:
    """Test transact blocks through the StoreDispatcher."""

    def _make_dispatcher(self) -> StoreDispatcher:
        d = StoreDispatcher()
        _run_async(d.dispatch({
            "operation": "axonstore",
            "args": {
                "name": "Bank",
                "backend": "sqlite",
                "connection": ":memory:",
                "schema": [
                    {"col_name": "id", "col_type": "integer", "primary_key": True, "auto_increment": True},
                    {"col_name": "owner", "col_type": "text"},
                    {"col_name": "balance", "col_type": "real"},
                ],
            },
        }))
        return d

    def test_transact_success(self):
        d = self._make_dispatcher()
        result = _run_async(d.dispatch({
            "operation": "transact",
            "args": {
                "children": [
                    {
                        "operation": "persist",
                        "args": {
                            "store_name": "Bank",
                            "fields": [["owner", "Alice"], ["balance", 1000.0]],
                        },
                    },
                    {
                        "operation": "persist",
                        "args": {
                            "store_name": "Bank",
                            "fields": [["owner", "Bob"], ["balance", 500.0]],
                        },
                    },
                ],
            },
        }))
        assert result.success
        assert result.data["children_executed"] == 2

    def test_transact_empty_children(self):
        d = self._make_dispatcher()
        result = _run_async(d.dispatch({
            "operation": "transact",
            "args": {"children": []},
        }))
        assert result.success
        assert result.data["children_executed"] == 0

    def test_transact_verify_data(self):
        d = self._make_dispatcher()
        _run_async(d.dispatch({
            "operation": "transact",
            "args": {
                "children": [
                    {
                        "operation": "persist",
                        "args": {
                            "store_name": "Bank",
                            "fields": [["owner", "Carol"], ["balance", 2000.0]],
                        },
                    },
                ],
            },
        }))
        # Verify the data was actually committed
        result = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "Bank", "where_expr": "owner = 'Carol'"},
        }))
        assert result.success
        assert result.data["count"] == 1


# ═══════════════════════════════════════════════════════════════════
#  §11 — INTEGRATION — End-to-end pipeline
# ═══════════════════════════════════════════════════════════════════

class TestAxonStoreIntegration:
    """Full pipeline: source → tokens → AST → IR → backend → dispatch."""

    def test_full_pipeline_definition(self):
        src = """
axonstore Metrics {
  backend: sqlite
  confidence_floor: 0.85
  isolation: repeatable_read
  schema {
    id: integer primary_key auto_increment
    metric_name: text not_null
    value: real
  }
}
"""
        # 1. Lex
        tokens = _lex(src)
        assert any(t.type == TokenType.AXONSTORE for t in tokens)

        # 2. Parse
        tree = _parse(src)
        stores = [d for d in tree.declarations if isinstance(d, AxonStoreDefinition)]
        assert len(stores) == 1
        assert stores[0].name == "Metrics"

        # 3. Type check
        errors = _check(src)
        store_errors = [e for e in errors if "axonstore" in str(e).lower() or "metric" in str(e).lower()]
        assert len(store_errors) == 0

        # 4. IR generate
        ir = _generate(src)
        assert len(ir.axonstore_specs) == 1
        spec = ir.axonstore_specs[0]
        assert spec.name == "Metrics"
        assert spec.confidence_floor == 0.85

    def test_full_pipeline_crud(self):
        """Source with store + CRUD in flow → IR has spec + flow steps."""
        src = '''
axonstore Users {
  backend: sqlite
  schema {
    id: integer primary_key
    email: text
  }
}
flow TestFlow() -> Text {
    persist into Users {
      email: "test@example.com"
    }
    step done {
        ask: "done"
        output: Text
    }
}
'''
        ir = _generate(src)
        assert len(ir.axonstore_specs) >= 1
        assert any(isinstance(s, IRPersist) for s in ir.flows[0].steps)

    def test_full_dispatcher_crud_cycle(self):
        """Init → persist → retrieve → mutate → retrieve → purge → retrieve."""
        d = StoreDispatcher()

        # Init
        _run_async(d.dispatch({
            "operation": "axonstore",
            "args": {
                "name": "Cycle",
                "backend": "sqlite",
                "connection": ":memory:",
                "schema": [
                    {"col_name": "id", "col_type": "integer", "primary_key": True, "auto_increment": True},
                    {"col_name": "val", "col_type": "text"},
                ],
            },
        }))

        # Persist
        r = _run_async(d.dispatch({
            "operation": "persist",
            "args": {"store_name": "Cycle", "fields": [["val", "original"]]},
        }))
        assert r.success

        # Retrieve
        r = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "Cycle", "where_expr": ""},
        }))
        assert r.data["count"] == 1

        # Mutate
        r = _run_async(d.dispatch({
            "operation": "mutate",
            "args": {"store_name": "Cycle", "where_expr": "val = 'original'", "fields": [["val", "updated"]]},
        }))
        assert r.data["rows_affected"] == 1

        # Verify mutation
        r = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "Cycle", "where_expr": "val = 'updated'"},
        }))
        assert r.data["count"] == 1

        # Purge
        r = _run_async(d.dispatch({
            "operation": "purge",
            "args": {"store_name": "Cycle", "where_expr": "val = 'updated'"},
        }))
        assert r.data["rows_deleted"] == 1

        # Verify empty
        r = _run_async(d.dispatch({
            "operation": "retrieve",
            "args": {"store_name": "Cycle", "where_expr": ""},
        }))
        assert r.data["count"] == 0


# ═══════════════════════════════════════════════════════════════════
#  §12 — STORE RESULT & FACTORY
# ═══════════════════════════════════════════════════════════════════

class TestStoreResult:
    """Test StoreResult dataclass and backend factory."""

    def test_store_result_defaults(self):
        r = StoreResult(success=True, operation="test")
        assert r.data is None
        assert r.error == ""
        assert r.metadata == {}

    def test_store_result_with_data(self):
        r = StoreResult(success=True, operation="query", data={"rows": []})
        assert r.data == {"rows": []}

    def test_factory_sqlite(self):
        b = create_store_backend("sqlite", ":memory:")
        assert isinstance(b, SQLiteStoreBackend)

    def test_factory_unknown_raises(self):
        with pytest.raises(ValueError, match="Unsupported|Unknown"):
            create_store_backend("redis", "")

    def test_store_registry_entry(self):
        entry = StoreRegistryEntry(
            name="Test",
            backend=SQLiteStoreBackend(connection=":memory:"),
        )
        assert entry.confidence_floor == 0.9
        assert entry.isolation == "serializable"
