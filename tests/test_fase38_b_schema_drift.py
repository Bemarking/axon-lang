"""§Fase 38.b (D9) — Cross-stack drift gate for the `schema:` declaration.

Per D9 the Rust frontend is the authoritative type-checker, but the
Python frontend must structurally agree on the AST/IR shape produced
for a given source. This pack walks a shared corpus and asserts the
Python frontend's IR matches the per-entry `expected` block. The Rust
pack ``axon-frontend/tests/fase38_b_schema_drift_gate.rs`` reads the
same corpus and runs identical assertions; if Python and Rust ever
diverge, exactly one of the two packs fails — drift caught at PR
review.

Corpus path: ``<repo-root>/tests/fixtures/fase38_b_schema_drift/corpus.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRStoreSchema,
    IRStoreSchemaEnvVar,
    IRStoreSchemaRef,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


CORPUS_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "fase38_b_schema_drift"
    / "corpus.json"
)


def _lower_first_axonstore(src: str) -> Any:
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    ir = IRGenerator().generate(program)
    assert len(ir.axonstore_specs) == 1, (
        "corpus entry must declare exactly one axonstore"
    )
    store = ir.axonstore_specs[0]
    schema = store.schema
    if schema is None:
        return None
    if isinstance(schema, IRStoreSchema):
        return {
            "form": "inline",
            "columns": [
                {
                    "name": col.col_name,
                    "type": col.col_type,
                    "primary_key": col.primary_key,
                    "auto_increment": col.auto_increment,
                    "not_null": col.not_null,
                    "unique": col.unique,
                    "default_value": col.default_value,
                }
                for col in schema.columns
            ],
        }
    if isinstance(schema, IRStoreSchemaRef):
        return {"form": "manifest_ref", "qualified_name": schema.qualified_name}
    if isinstance(schema, IRStoreSchemaEnvVar):
        return {"form": "env_var", "var_name": schema.var_name}
    raise AssertionError(f"unexpected schema variant: {type(schema).__name__}")


def _load_corpus() -> list[dict[str, Any]]:
    text = CORPUS_PATH.read_text(encoding="utf-8")
    parsed = json.loads(text)
    entries = parsed["entries"]
    assert entries, "corpus must carry at least one entry"
    return entries


@pytest.mark.parametrize("entry", _load_corpus(), ids=lambda e: e["name"])
def test_fase38_b_schema_drift_gate_python_matches_corpus(entry: dict[str, Any]) -> None:
    """Each corpus entry: Python's lowered IR must match `expected`."""
    observed = _lower_first_axonstore(entry["source"])
    expected = entry["expected"]
    assert observed == expected, (
        f"drift on entry `{entry['name']}` — Python observed {observed} "
        f"but corpus expected {expected}"
    )
