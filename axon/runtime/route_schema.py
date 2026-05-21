"""§Fase 32.c + 32.d — Schema validation (Python mirror).

Byte-identical sibling of `axon-rs/src/route_schema.rs`. The same input
program + the same JSON value produce the same `BodyValidationError`
fields (expected_type, field_path, expected, got, hint).

Consumed at TWO call sites in the runtime (same primitive, two
semantic boundaries):

  1. **Request side (D4, 32.c)** — before flow dispatch. On violation
     the HTTP layer returns 400 Bad Request with the full structured
     error so the adopter client can fix the request.
  2. **Response side (D5, 32.d)** — after flow dispatch, before
     returning to the client. On violation the HTTP layer returns
     **GENERIC 500** to the client (OWASP — schema details never leak)
     but records the full diagnostic in the audit log so the adopter
     fixes the FLOW.

The validator itself does not care which side it runs on — same pure
function, same drift gate.

Consumed by:

  * The drift-gate test pack `tests/test_fase32_body_schema.py`, which
    parametrizes over the shared corpus at
    `tests/fixtures/fase32_body_schema/corpus.json` and asserts that
    both stacks produce byte-identical validation results.

  * Future Python `AxonServer` integration (FastAPI request validation
    wiring) when the Python runtime catches up on the dynamic-route
    fallback handler shape Rust ships in 32.b/c/d.

Pillar trace per D12:

  - MATHEMATICS — `validate_body` is pure + total over the declared
                   type system. Same input → same Result.
  - LOGIC       — every accepted body matches the declared schema.
                   No widening, no coercion. `Integer` rejects `"42"`.
  - PHILOSOPHY  — the source declaration IS the contract — both for
                   accepted requests (D4) and produced responses (D5).
  - COMPUTING   — D9 backwards-compat: empty type name skips
                   validation entirely. Adopters opt in by declaring.
                   OWASP-aligned on the response side: client never
                   sees schema details on D5 violations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ast_nodes import TypeDefinition


# §Fase 32.c — Built-in primitive type names recognised by the validator.
# Mirrors `BUILTIN_PRIMITIVES` in `axon-rs/src/route_schema.rs`.
BUILTIN_PRIMITIVES: frozenset[str] = frozenset({
    "String", "Integer", "Float", "Boolean", "Duration", "Any",
})


def builtin_range(name: str) -> tuple[float, float] | None:
    """Mirror of `builtin_range` in route_schema.rs. Closed numeric
    range for the three semantic types declared in
    `axon/compiler/type_checker.py::RANGED_TYPES`."""
    if name in ("RiskScore", "ConfidenceScore"):
        return (0.0, 1.0)
    if name == "SentimentScore":
        return (-1.0, 1.0)
    return None


@dataclass
class FieldSchema:
    """One field inside a structured type. `optional == True` if the
    source declared the field as `name: T?`. Mirror of Rust struct."""
    name: str = ""
    type_name: str = ""
    generic_param: str = ""
    optional: bool = False


@dataclass
class TypeSchema:
    """Snapshot of a `type T { … }` declaration relevant to body
    validation. Mirror of Rust struct — same field order, same names."""
    name: str = ""
    fields: list[FieldSchema] = field(default_factory=list)
    range: tuple[float, float] | None = None


@dataclass
class BodyValidationError(Exception):
    """Structured body-validation error. The HTTP layer projects this
    into a 400 Bad Request with the field/expected/got triple so
    adopter clients can correct their request without server log diving.

    Mirror of Rust struct — same field names + same projection into the
    response body shape under the shared drift gate.
    """
    expected_type: str = ""
    field_path: str = ""
    expected: str = ""
    got: str = ""
    hint: str = ""

    def __str__(self) -> str:
        return self.hint


def collect_type_table(program: "Program") -> dict[str, TypeSchema]:
    """Walk every `type T { … }` declaration in the deployed program
    and produce a `name → TypeSchema` lookup table.

    Last-wins on collision is the same semantics as Python `dict`
    overwrite — cross-deploy name collision is out of scope for 32.c
    (deferred to a future type-registry fase).
    """
    table: dict[str, TypeSchema] = {}
    for decl in program.declarations:
        if isinstance(decl, TypeDefinition):
            table[decl.name] = _type_schema_from(decl)
    return table


def _type_schema_from(td: TypeDefinition) -> TypeSchema:
    fields: list[FieldSchema] = []
    for f in td.fields:
        type_expr = f.type_expr
        if type_expr is None:
            # Defensive: parser should always populate type_expr; skip
            # malformed entries rather than crash.
            continue
        fields.append(FieldSchema(
            name=f.name,
            type_name=type_expr.name,
            generic_param=type_expr.generic_param,
            optional=type_expr.optional,
        ))
    rc = td.range_constraint
    rng: tuple[float, float] | None = None
    if rc is not None:
        rng = (rc.min_value, rc.max_value)
    return TypeSchema(name=td.name, fields=fields, range=rng)


# §32.c — Display sentinel for top-level body violations (field_path
# is empty at top level). Shared across every error-message branch.
_BODY_PATH_DISPLAY = "<body>"


def fmt_f64(n: float) -> str:
    """Format a float the same way Rust's `route_schema::fmt_f64`
    renders bounds + `got` values inside validation errors. Whole-
    valued floats render as integers (`"0"`, `"1"`, `"-1"`); fractional
    values render via Python `str(float)` (`"1.5"`, `"-1.5"`). Locks
    the cross-stack drift gate against Display-vs-str divergence.
    """
    import math
    if math.isfinite(n) and n == int(n) and abs(n) < 1e16:
        return str(int(n))
    return str(n)


def _json_tag(v: Any) -> str:
    """Tag a JSON value with the lowercase string the validator reports
    as `got`. Numbers split into `"integer"` vs `"number"` so adopters
    declaring `Integer` get a precise diagnostic when they sent a float.

    Mirror of `json_tag` in route_schema.rs — same exact strings on
    every JSON kind.
    """
    if v is None:
        return "null"
    # `bool` is a subclass of `int` in Python; check it first.
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def validate_body(
    body: Any,
    type_name: str,
    table: dict[str, TypeSchema],
) -> BodyValidationError | None:
    """Validate `body` against the type named `type_name`, returning
    `None` on success or a `BodyValidationError` on failure.

    Backwards-compat (D9): empty `type_name` is a no-op — returns
    `None`. Adopters who don't declare `body:` keep free-form behavior.

    Mirror of `validate_body` in route_schema.rs — same depth-first
    field-declaration-order traversal, same error projection.
    """
    if not type_name:
        return None
    return _validate_value(body, type_name, "", "", table, type_name)


def _validate_value(
    v: Any,
    type_name: str,
    generic_param: str,
    field_path: str,
    table: dict[str, TypeSchema],
    body_type: str,
) -> BodyValidationError | None:
    # §0 — §Fase 38.x.f.10 (POST-CLOSE HOTFIX 2026-05-21) — generic-
    # aware parsing. Python mirror of the Rust §0 preamble in
    # axon-rs/src/route_schema.rs::validate_value (shipped in v1.40.2
    # as 38.x.f.9). v1.40.2 closed the Rust path; this v1.40.3
    # closes the Python path. Founder principle: "axon es un lenguaje,
    # no varios, sino uno solo" — cross-runtime semantic parity on
    # the same .axon source.
    #
    # When the caller passes the raw type string with an embedded
    # generic param (e.g. "List<TenantRecord>" from validate_body or
    # from _validate_struct's field-type recursion) AND generic_param
    # is empty, strip the <Inner> and recurse with the head + inner
    # as separate args. This closes the T9XX-to-D5 dead-end the
    # 38.x.f cardinality cycle left open: the compile-time gate
    # suggests output: List<T> as remedy, the adopter applies it,
    # and the runtime D5 then recognizes "List" + generic_param "T"
    # properly (§3 below) — pre-hotfix the unsplit "List<T>" string
    # fell through to §5 unknown_type.
    #
    # Recursive — handles nested List<List<T>> because the inner
    # recursion lands here again with type_name = "List<T>" and
    # strips ANOTHER layer.
    #
    # Closed grammar today: List<Inner> + Stream<Inner>. Other
    # future generics (Map<K,V>, Optional<T>, etc.) extend this §0
    # additively without touching §1–§5.
    if not generic_param:
        if type_name.startswith("List<") and type_name.endswith(">"):
            inner = type_name[len("List<"):-1].strip()
            return _validate_value(v, "List", inner, field_path, table, body_type)
        if type_name.startswith("Stream<") and type_name.endswith(">"):
            # §Fase 38.x.f.10 — Stream<T> body validation is
            # structurally unreachable from the production path
            # (SSE responses route through the streaming wire
            # which validates chunks, not the full body). When
            # we DO observe it at the body validator layer
            # (defensive), return None (Ok) early — the runtime
            # SSE path is the canonical validation surface for
            # temporal cardinality.
            return None
    # §1 — primitives
    if type_name in BUILTIN_PRIMITIVES:
        return _validate_primitive(v, type_name, field_path, body_type)
    # §2 — range-constrained built-ins (RiskScore, ConfidenceScore, ...)
    rng = builtin_range(type_name)
    if rng is not None:
        return _validate_ranged_number(v, type_name, rng[0], rng[1], field_path, body_type)
    # §3 — generic List<T>
    if type_name == "List":
        return _validate_list(v, generic_param, field_path, table, body_type)
    # §4 — structured types declared in the program
    schema = table.get(type_name)
    if schema is not None:
        if schema.range is not None:
            return _validate_ranged_number(
                v, type_name, schema.range[0], schema.range[1], field_path, body_type,
            )
        return _validate_struct(v, schema, field_path, table, body_type)
    # §5 — unknown type. Adopter misspell or undeclared. We surface
    # rather than silently pass so the diagnostic is actionable.
    return BodyValidationError(
        expected_type=body_type,
        field_path=field_path,
        expected=type_name,
        got=_json_tag(v),
        hint=(
            f"axonendpoint declared an unknown body type `{type_name}` for "
            f"field `{field_path}` — neither a built-in primitive nor a "
            f"declared `type` in the deployed source. Add `type {type_name} "
            f"{{ … }}` to the source or correct the spelling."
        ),
    )


def _validate_primitive(
    v: Any,
    type_name: str,
    field_path: str,
    body_type: str,
) -> BodyValidationError | None:
    ok = False
    if type_name == "String":
        ok = isinstance(v, str)
    elif type_name == "Integer":
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif type_name == "Float":
        # Float accepts JSON numbers (integer or fractional).
        ok = (isinstance(v, (int, float)) and not isinstance(v, bool))
    elif type_name == "Boolean":
        ok = isinstance(v, bool)
    elif type_name == "Duration":
        ok = isinstance(v, str)
    elif type_name == "Any":
        ok = True
    if ok:
        return None
    path_disp = field_path if field_path else _BODY_PATH_DISPLAY
    return BodyValidationError(
        expected_type=body_type,
        field_path=field_path,
        expected=type_name,
        got=_json_tag(v),
        hint=(
            f"Body field `{path_disp}` must be a `{type_name}` but received "
            f"a {_json_tag(v)}. Adjust the request body or the axonendpoint's "
            f"`body:` declaration."
        ),
    )


def _validate_ranged_number(
    v: Any,
    type_name: str,
    lo: float,
    hi: float,
    field_path: str,
    body_type: str,
) -> BodyValidationError | None:
    lo_s = fmt_f64(lo)
    hi_s = fmt_f64(hi)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        path_disp = field_path if field_path else _BODY_PATH_DISPLAY
        return BodyValidationError(
            expected_type=body_type,
            field_path=field_path,
            expected=type_name,
            got=_json_tag(v),
            hint=(
                f"Body field `{path_disp}` must be a `{type_name}` (numeric in "
                f"[{lo_s}, {hi_s}]) but received a {_json_tag(v)}."
            ),
        )
    n = float(v)
    if n < lo or n > hi:
        path_disp = field_path if field_path else _BODY_PATH_DISPLAY
        n_s = fmt_f64(n)
        return BodyValidationError(
            expected_type=body_type,
            field_path=field_path,
            expected=f"{type_name} ∈ [{lo_s}, {hi_s}]",
            got=n_s,
            hint=(
                f"Body field `{path_disp}` must satisfy `{type_name} ∈ "
                f"[{lo_s}, {hi_s}]` but received `{n_s}`."
            ),
        )
    return None


def _validate_list(
    v: Any,
    element_type: str,
    field_path: str,
    table: dict[str, TypeSchema],
    body_type: str,
) -> BodyValidationError | None:
    if not isinstance(v, list):
        path_disp = field_path if field_path else _BODY_PATH_DISPLAY
        return BodyValidationError(
            expected_type=body_type,
            field_path=field_path,
            expected=f"List<{element_type}>",
            got=_json_tag(v),
            hint=(
                f"Body field `{path_disp}` must be a `List<{element_type}>` "
                f"(JSON array) but received a {_json_tag(v)}."
            ),
        )
    if not element_type:
        # Degenerate `List` declaration with no generic param — accept
        # any element. Mirror of Rust behaviour.
        return None
    for idx, elem in enumerate(v):
        elem_path = f"[{idx}]" if not field_path else f"{field_path}[{idx}]"
        err = _validate_value(elem, element_type, "", elem_path, table, body_type)
        if err is not None:
            return err
    return None


def _validate_struct_field(
    fld: FieldSchema,
    obj: dict[str, Any],
    struct_name: str,
    field_path: str,
    table: dict[str, TypeSchema],
    body_type: str,
) -> BodyValidationError | None:
    """Validate one declared field on a structured-type body. Returns
    `None` on pass, `BodyValidationError` on the first violation."""
    child_path = fld.name if not field_path else f"{field_path}.{fld.name}"
    if fld.name not in obj:
        if fld.optional:
            return None
        return BodyValidationError(
            expected_type=body_type,
            field_path=child_path,
            expected=fld.type_name,
            got="missing",
            hint=(
                f"Body field `{child_path}` is required (declared as "
                f"`{fld.type_name}` on `{struct_name}`) but is absent "
                f"from the request body."
            ),
        )
    child = obj[fld.name]
    # Optional `T?` fields with explicit JSON null are accepted.
    if fld.optional and child is None:
        return None
    return _validate_value(
        child, fld.type_name, fld.generic_param, child_path, table, body_type,
    )


def _validate_struct(
    v: Any,
    schema: TypeSchema,
    field_path: str,
    table: dict[str, TypeSchema],
    body_type: str,
) -> BodyValidationError | None:
    if not isinstance(v, dict):
        path_disp = field_path if field_path else _BODY_PATH_DISPLAY
        return BodyValidationError(
            expected_type=body_type,
            field_path=field_path,
            expected=schema.name,
            got=_json_tag(v),
            hint=(
                f"Body field `{path_disp}` must be a `{schema.name}` (JSON "
                f"object) but received a {_json_tag(v)}."
            ),
        )
    for fld in schema.fields:
        err = _validate_struct_field(fld, v, schema.name, field_path, table, body_type)
        if err is not None:
            return err
    # Unknown extra fields are NOT rejected — adopters can pass extra
    # payload the flow ignores ("be liberal in what you accept" for
    # forwards-compat with client-side additions). Strict mode is a
    # future opt-in if vertical compliance demands.
    return None


def error_as_corpus_dict(err: BodyValidationError | None) -> dict[str, Any] | None:
    """Project a `BodyValidationError` into the dict the drift gate
    asserts byte-identically across stacks. `None` projects to `None`
    (the success sentinel)."""
    if err is None:
        return None
    return {
        "expected_type": err.expected_type,
        "field_path": err.field_path,
        "expected": err.expected,
        "got": err.got,
        # `hint` is excluded from the byte-identical drift assertion
        # (free-form prose, formatting tolerated to drift across stacks);
        # the structured (expected_type, field_path, expected, got)
        # tuple is the locked invariant.
    }
