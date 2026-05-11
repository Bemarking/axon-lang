"""§Fase 32.c — Cross-stack drift gate for body schema validation.

D4 + D9 + D11 ratificadas 2026-05-11. Verifies:

  * `validate_body` produces the expected `(expected_type, field_path,
    expected, got)` tuple for every corpus entry — `None` on success,
    structured `BodyValidationError` on failure.
  * D9 backwards-compat: empty `body_type` accepts any body.
  * Primitive types: String / Integer / Float / Boolean / Any honour
    JSON-tag distinctions (integer vs number, bool vs string, etc.).
  * Structured types: required field missing → 400; optional field
    absent / null → 200; extra fields silently accepted (Postel's Law).
  * Generic `List<T>`: element-wise validation, indexed dotted path
    on first violation.
  * Range types: built-in `RiskScore`/`ConfidenceScore` ∈ [0,1] and
    `SentimentScore` ∈ [-1,1] rejected out-of-bounds.
  * Unknown declared types: misspell surfaces as actionable diagnostic
    rather than silent pass.
  * 4-pillar vertical X-ray (banking + medicine): `LoanApplication` +
    `ClinicalDecisionRequest` round-trip + a representative violation
    on each.

The same corpus JSON is read by the Rust integration test
`axon-rs/tests/fase32_body_schema_drift.rs`; if Python and Rust ever
disagree on the validation tuple for any corpus entry, exactly one of
the two test packs fails — drift caught at PR-time per D11.

Pillar trace per D12:
  - MATHEMATICS — `validate_body` is pure + total over declared types.
  - LOGIC       — every accepted body matches declared schema, no
                   coercion, no widening.
  - PHILOSOPHY  — declaration IS the contract; auditors read source
                   + know accepted shapes.
  - COMPUTING   — cross-stack contract anchored on shared corpus JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.ast_nodes import (
    RangeConstraint,
    TypeDefinition,
    TypeExprNode,
    TypeFieldNode,
)
from axon.runtime.route_schema import (
    BUILTIN_PRIMITIVES,
    BodyValidationError,
    FieldSchema,
    TypeSchema,
    builtin_range,
    collect_type_table,
    error_as_corpus_dict,
    fmt_f64,
    validate_body,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "fase32_body_schema" / "corpus.json"
)


# ── Helpers ──────────────────────────────────────────────────────────


def _build_table(declarations: list[dict]) -> dict[str, TypeSchema]:
    """Build a `name → TypeSchema` table directly from a corpus entry's
    declarations list. Bypasses the parser so the corpus can express
    arbitrary type shapes without source-syntax drift surfacing here."""
    table: dict[str, TypeSchema] = {}
    for decl in declarations:
        fields: list[FieldSchema] = []
        for f in decl.get("fields", []):
            fields.append(FieldSchema(
                name=f["name"],
                type_name=f["type"],
                generic_param=f.get("generic_param", ""),
                optional=f.get("optional", False),
            ))
        table[decl["name"]] = TypeSchema(name=decl["name"], fields=fields)
    return table


# ── Corpus integrity ─────────────────────────────────────────────────


def test_corpus_exists_and_has_required_shape():
    """Sanity: corpus is valid JSON with the expected schema."""
    assert CORPUS_PATH.exists(), f"Corpus missing at {CORPUS_PATH}"
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert "entries" in data, "corpus.json missing 'entries' key"
    assert data.get("d_letter_anchor", "").startswith("D4"), \
        "corpus.json must anchor D4 (+ D11)"
    for entry in data["entries"]:
        assert "name" in entry
        assert "body_type" in entry
        assert "body" in entry
        assert "expected_validation" in entry  # None or dict
        if entry["expected_validation"] is not None:
            for k in ("expected_type", "field_path", "expected", "got"):
                assert k in entry["expected_validation"], \
                    f"entry '{entry['name']}' validation missing {k}"


def test_corpus_has_at_least_25_entries():
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert len(data["entries"]) >= 25, \
        f"corpus shrank: {len(data['entries'])} entries, expected ≥ 25"


# ── Drift-gate parametrized ──────────────────────────────────────────


def _load_corpus():
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return [
        pytest.param(entry, id=entry["name"]) for entry in data["entries"]
    ]


@pytest.mark.parametrize("entry", _load_corpus())
def test_python_validation_matches_corpus(entry):
    """For every corpus entry, Python's `validate_body` produces the
    declared expected (expected_type, field_path, expected, got) tuple
    — `None` on success, structured error on failure. Asserts on the
    locked-shape fields only; the prose `hint` field tolerates drift.
    """
    table = _build_table(entry["type_declarations"])
    err = validate_body(entry["body"], entry["body_type"], table)
    actual = error_as_corpus_dict(err)
    expected = entry["expected_validation"]
    assert actual == expected, (
        f"corpus entry '{entry['name']}' drift:\n"
        f"  python actual:   {actual!r}\n"
        f"  corpus expected: {expected!r}"
    )


# ── Canonical D4 + primitive coverage ────────────────────────────────


def test_d9_empty_body_type_passes_any_body():
    """D9 backwards-compat: empty `body_type` accepts any JSON."""
    assert validate_body({"any": "shape"}, "", {}) is None
    assert validate_body([1, 2, 3], "", {}) is None
    assert validate_body("string", "", {}) is None
    assert validate_body(None, "", {}) is None


def test_primitive_string():
    assert validate_body("hello", "String", {}) is None
    err = validate_body(42, "String", {})
    assert err is not None
    assert err.expected == "String"
    assert err.got == "integer"


def test_primitive_integer_rejects_float():
    """LOGIC: no implicit numeric widening. 3.14 is NOT an Integer."""
    err = validate_body(3.14, "Integer", {})
    assert err is not None
    assert err.got == "number"


def test_primitive_integer_accepts_integer():
    assert validate_body(42, "Integer", {}) is None
    assert validate_body(-1, "Integer", {}) is None
    assert validate_body(0, "Integer", {}) is None


def test_primitive_float_accepts_integer_json():
    """Float type accepts both JSON integers and decimals — broader
    than Integer which strictly requires non-fractional numbers."""
    assert validate_body(42, "Float", {}) is None
    assert validate_body(3.14, "Float", {}) is None


def test_primitive_boolean_does_not_accept_truthy_string():
    err = validate_body("true", "Boolean", {})
    assert err is not None
    assert err.expected == "Boolean"


def test_primitive_boolean_is_not_integer():
    """In Python `bool` is a subclass of `int` — the validator must
    NOT accept `True` for Integer body type. Drift-protected."""
    err = validate_body(True, "Integer", {})
    assert err is not None
    assert err.got == "boolean"


def test_any_accepts_anything():
    assert validate_body([1, "two", {"three": 3}], "Any", {}) is None
    assert validate_body(None, "Any", {}) is None


def test_duration_accepts_string():
    """Duration is a String at the wire layer (semantic parsing of
    `5s`/`15s` is the runtime's concern, not the validator)."""
    assert validate_body("15s", "Duration", {}) is None
    err = validate_body(15, "Duration", {})
    assert err is not None


# ── Structured types ─────────────────────────────────────────────────


def _person_table() -> dict[str, TypeSchema]:
    return {
        "Person": TypeSchema(
            name="Person",
            fields=[
                FieldSchema(name="name", type_name="String"),
                FieldSchema(name="age", type_name="Integer", optional=True),
            ],
        ),
    }


def test_structured_well_formed():
    assert validate_body(
        {"name": "alice", "age": 30}, "Person", _person_table()
    ) is None


def test_structured_missing_required_field():
    err = validate_body({"age": 30}, "Person", _person_table())
    assert err is not None
    assert err.field_path == "name"
    assert err.got == "missing"
    assert err.expected == "String"


def test_structured_optional_field_absent_ok():
    assert validate_body({"name": "alice"}, "Person", _person_table()) is None


def test_structured_optional_field_null_ok():
    assert validate_body(
        {"name": "alice", "age": None}, "Person", _person_table()
    ) is None


def test_structured_extra_fields_silently_accepted():
    """Postel's Law: be liberal in what you accept. Adopters can pass
    extra payload the flow ignores. Strict mode is a future opt-in."""
    assert validate_body(
        {"name": "alice", "extra": "data", "age": 30},
        "Person",
        _person_table(),
    ) is None


def test_structured_rejects_non_object():
    err = validate_body("not an object", "Person", _person_table())
    assert err is not None
    assert err.got == "string"
    assert err.expected == "Person"


def test_nested_struct_field_path_is_dotted():
    """LOGIC: the field_path locks the path-of-violation invariant for
    the audit chain — auditors trace failures to the exact field."""
    table = {
        **_person_table(),
        "Loan": TypeSchema(
            name="Loan",
            fields=[FieldSchema(name="applicant", type_name="Person")],
        ),
    }
    err = validate_body({"applicant": {"age": 30}}, "Loan", table)
    assert err is not None
    assert err.field_path == "applicant.name"
    assert err.expected_type == "Loan"


# ── List<T> ──────────────────────────────────────────────────────────


def test_list_of_strings_well_formed():
    table = {
        "Tags": TypeSchema(
            name="Tags",
            fields=[FieldSchema(
                name="values", type_name="List", generic_param="String",
            )],
        ),
    }
    assert validate_body({"values": ["a", "b", "c"]}, "Tags", table) is None


def test_list_indexed_violation_uses_bracket_notation():
    table = {
        "Tags": TypeSchema(
            name="Tags",
            fields=[FieldSchema(
                name="values", type_name="List", generic_param="String",
            )],
        ),
    }
    err = validate_body({"values": ["a", 42, "c"]}, "Tags", table)
    assert err is not None
    assert err.field_path == "values[1]"
    assert err.got == "integer"


def test_list_rejects_non_array():
    table = {
        "Tags": TypeSchema(
            name="Tags",
            fields=[FieldSchema(
                name="values", type_name="List", generic_param="String",
            )],
        ),
    }
    err = validate_body({"values": "scalar"}, "Tags", table)
    assert err is not None
    assert err.expected == "List<String>"


# ── Range types ──────────────────────────────────────────────────────


def test_risk_score_in_bounds():
    assert validate_body(0.5, "RiskScore", {}) is None
    assert validate_body(0.0, "RiskScore", {}) is None
    assert validate_body(1.0, "RiskScore", {}) is None


def test_risk_score_out_of_bounds():
    err = validate_body(1.5, "RiskScore", {})
    assert err is not None
    assert "RiskScore" in err.expected


def test_sentiment_score_negative_bound():
    """SentimentScore ∈ [-1, 1] — accepts negatives, rejects below."""
    assert validate_body(-0.7, "SentimentScore", {}) is None
    err = validate_body(-1.5, "SentimentScore", {})
    assert err is not None


def test_builtin_range_table():
    assert builtin_range("RiskScore") == (0.0, 1.0)
    assert builtin_range("ConfidenceScore") == (0.0, 1.0)
    assert builtin_range("SentimentScore") == (-1.0, 1.0)
    assert builtin_range("NotRanged") is None


# ── Unknown type ─────────────────────────────────────────────────────


def test_unknown_type_surfaces_diagnostic():
    """Adopter misspelled — fail loudly. Silent pass would lose the
    auditable contract guarantee."""
    err = validate_body({"any": "shape"}, "NotDeclared", {})
    assert err is not None
    assert err.expected == "NotDeclared"
    assert "NotDeclared" in err.hint


# ── collect_type_table ───────────────────────────────────────────────


def test_collect_type_table_walks_program_types():
    """`collect_type_table` produces a usable schema lookup from a
    program containing `type T { … }` declarations. Integration with
    the AST nodes layer."""

    class _Prog:
        declarations: list = []

    prog = _Prog()
    person_def = TypeDefinition(
        name="Person",
        fields=[
            TypeFieldNode(name="name", type_expr=TypeExprNode(name="String")),
            TypeFieldNode(name="age", type_expr=TypeExprNode(name="Integer", optional=True)),
        ],
    )
    prog.declarations = [person_def]
    table = collect_type_table(prog)
    assert "Person" in table
    person = table["Person"]
    assert len(person.fields) == 2
    assert person.fields[0].name == "name"
    assert person.fields[0].type_name == "String"
    assert person.fields[1].optional is True


def test_collect_type_table_captures_range_constraint():
    """`type R(0.0..1.0)` round-trips into the TypeSchema range."""

    class _Prog:
        declarations: list = []

    prog = _Prog()
    ranged = TypeDefinition(
        name="MyScore",
        range_constraint=RangeConstraint(min_value=0.0, max_value=1.0),
    )
    prog.declarations = [ranged]
    table = collect_type_table(prog)
    assert table["MyScore"].range == (0.0, 1.0)


def test_user_declared_range_type_validation():
    """A user `type Pct(0..100)` is validated as a ranged numeric."""
    table = {
        "Pct": TypeSchema(name="Pct", range=(0.0, 100.0)),
    }
    assert validate_body(50, "Pct", table) is None
    err = validate_body(150, "Pct", table)
    assert err is not None


# ── fmt_f64 + cross-stack format ─────────────────────────────────────


def test_fmt_f64_whole_numbers_no_decimal():
    """Mirror Rust `fmt_f64`: 0.0 → "0", 1.0 → "1", -1.0 → "-1"."""
    assert fmt_f64(0.0) == "0"
    assert fmt_f64(1.0) == "1"
    assert fmt_f64(-1.0) == "-1"
    assert fmt_f64(100.0) == "100"


def test_fmt_f64_fractional_keeps_decimal():
    assert fmt_f64(1.5) == "1.5"
    assert fmt_f64(-1.5) == "-1.5"
    assert fmt_f64(0.1) == "0.1"


def test_builtin_primitives_const_anchor():
    """Anchor: BUILTIN_PRIMITIVES is the closed enum that Rust + Python
    BOTH consult. Adding a primitive requires updating both sides."""
    assert "String" in BUILTIN_PRIMITIVES
    assert "Integer" in BUILTIN_PRIMITIVES
    assert "Float" in BUILTIN_PRIMITIVES
    assert "Boolean" in BUILTIN_PRIMITIVES
    assert "Duration" in BUILTIN_PRIMITIVES
    assert "Any" in BUILTIN_PRIMITIVES
    # Reserved for future: must NOT be in the set today.
    assert "Object" not in BUILTIN_PRIMITIVES
    assert "Number" not in BUILTIN_PRIMITIVES


# ── BodyValidationError exception shape ──────────────────────────────


def test_body_validation_error_is_dataclass_with_expected_fields():
    err = BodyValidationError(
        expected_type="X",
        field_path="a.b",
        expected="Y",
        got="string",
        hint="Body field `a.b` …",
    )
    assert err.expected_type == "X"
    assert err.field_path == "a.b"
    assert err.expected == "Y"
    assert err.got == "string"
    assert str(err).startswith("Body field")


def test_error_as_corpus_dict_strips_hint():
    """`hint` is intentionally excluded from drift-gate assertions
    (prose tolerated to drift across stacks)."""
    err = BodyValidationError(
        expected_type="X", field_path="a", expected="Y", got="z", hint="h",
    )
    d = error_as_corpus_dict(err)
    assert d == {
        "expected_type": "X", "field_path": "a", "expected": "Y", "got": "z",
    }
    assert "hint" not in d
    assert error_as_corpus_dict(None) is None
