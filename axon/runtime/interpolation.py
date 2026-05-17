"""§Fase 35.q — the AXON variable-interpolation contract.

axon is **one language** — and it has **one** interpolation syntax:
``${name}`` / ``$name``. This module is the Python runtime's
implementation of that contract; the canonical Rust runtime
(``axon-rs::exec_context::interpolate_vars``) implements byte-identical
semantics, and the shared corpus at
``tests/fixtures/interpolation_contract.json`` pins the two together so
a single ``.axon`` interpolates the same on either runtime.

``{{name}}`` is **not** part of the contract. It is a legacy dialect
of the Python runtime only, interpolated separately by the Executor and
kept working transitionally so flows written against the Python server
keep running until they convert to ``${name}``. It dies with the
Python runtime; the Rust runtime never accepted it.
"""

from __future__ import annotations

import re

# `${name}` — any run of non-`}` characters — OR `$name` — an
# identifier `[A-Za-z_][A-Za-z0-9_]*`. Mirrors the byte scan in
# axon-rs `interpolate_vars` exactly: `$` followed by `{` opens the
# braced form (name = up to the first `}`); `$` followed by an ASCII
# letter or `_` opens the bare form; any other `$` is literal.
_VAR_RE = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def interpolate_vars(text: str, variables: dict[str, str]) -> str:
    """Substitute ``${name}`` / ``$name`` references in *text*.

    A name found in *variables* is replaced by its value; an unknown
    name is left **literal** (``${missing}`` stays ``${missing}``,
    ``$missing`` stays ``$missing``). The substitution is a single
    pass — substituted values are never re-scanned — so the result is
    byte-identical with the Rust runtime's ``interpolate_vars``
    (§Fase 35.q contract; pinned by the shared corpus drift gate).
    """

    def _sub(m: "re.Match[str]") -> str:
        name = m.group(1) if m.group(1) is not None else m.group(2)
        if name in variables:
            return variables[name]
        # Unknown variable — keep the whole reference literal.
        return m.group(0)

    return _VAR_RE.sub(_sub, text)
