"""§Fase 35.q — the interpolation-contract drift gate (Python side).

axon has ONE interpolation syntax — ``${name}`` / ``$name``. This test
reads the SAME corpus the Rust runtime's contract test reads
(``tests/fixtures/interpolation_contract.json``) and asserts the Python
runtime's ``interpolate_vars`` produces the documented output. The Rust
test (``axon-rs/tests/fase35q_interpolation_contract.rs``) reads the
identical corpus — together they pin the two runtimes byte-identical so
a single ``.axon`` interpolates the same on either one.
"""

from __future__ import annotations

import json
from pathlib import Path

from axon.runtime.interpolation import interpolate_vars

_CORPUS = Path(__file__).parent / "fixtures" / "interpolation_contract.json"


def test_interpolation_contract_corpus():
    cases = json.loads(_CORPUS.read_text(encoding="utf-8"))
    assert cases, "interpolation contract corpus is empty"
    for case in cases:
        got = interpolate_vars(case["input"], case["vars"])
        assert got == case["expected"], (
            f"case {case['name']!r}: "
            f"interpolate_vars({case['input']!r}, {case['vars']!r}) "
            f"= {got!r}, expected {case['expected']!r}"
        )


def test_unknown_variables_are_left_literal():
    # The conservative rule — an unknown name is never blanked, it
    # stays verbatim so a mistyped reference is visible, not silent.
    assert interpolate_vars("${a} $b", {}) == "${a} $b"


def test_double_brace_is_not_the_contract():
    # `{{name}}` is the legacy Python-runtime dialect, handled
    # separately by the Executor — `interpolate_vars` leaves it alone.
    assert interpolate_vars("{{name}}", {"name": "x"}) == "{{name}}"
