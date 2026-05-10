"""§Fase 28.e — Smart-suggest "Did you mean X?" for unknown tokens.

When the parser encounters an identifier that isn't a valid keyword
in the current syntactic position, this module suggests the closest
matches from the in-scope keyword set using Levenshtein edit
distance.

Contract (D3 ratified 2026-05-10):
    * Maximum edit distance: ≤ 2.
    * Maximum candidates returned: 3.
    * Always on (D11) — every unknown-keyword error path can call
      `suggest_for(unknown, candidates)` and append the suggestion
      to the diagnostic message.

The module is pure and deterministic: same inputs → same output.
The Rust frontend has a byte-identical mirror at
`axon-frontend/src/smart_suggest.rs` so the cross-stack drift gate
(28.i) can compare suggestion lists input-for-input (D7).

Public API:

    levenshtein(a: str, b: str) -> int
        Standard iterative DP edit distance with a single rolling
        row of size len(b)+1. O(len(a) * len(b)) time, O(len(b))
        space.

    suggest(
        unknown: str,
        candidates: Iterable[str],
        *,
        max_distance: int = MAX_DISTANCE,
        max_results: int = MAX_RESULTS,
    ) -> list[str]
        Return up to `max_results` candidates sorted by (distance,
        candidate). Distance ≤ `max_distance` is required. Empty
        list when nothing close enough.

    format_suggestion_hint(suggestions: list[str]) -> str
        Format a list of suggestions into a human-readable hint
        suffix — `"Did you mean `flow`?"` for one match,
        `"Did you mean `flow`, `flow_v2`, or `flowery`?"` for many.
        Empty list → empty string.
"""
from __future__ import annotations

from typing import Iterable


MAX_DISTANCE: int = 2
"""§D3 — Levenshtein distance threshold. Identifiers further than
this from any candidate are treated as having no plausible match
and produce no suggestion (avoids "did you mean foo?" for an
adopter who actually wrote `flotsam` and meant something else
entirely)."""


MAX_RESULTS: int = 3
"""§D3 — Maximum number of candidates returned. Three is the
"helpful, not noisy" cutoff — adopters reading an error message
can scan three options at a glance; four+ becomes overwhelming."""


def levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein edit distance.

    Single-row rolling DP for O(len(b)) auxiliary space. Handles
    empty strings: ``levenshtein("", "abc") == 3``,
    ``levenshtein("abc", "") == 3``, ``levenshtein("", "") == 0``.

    The implementation is byte-identical in shape to the Rust
    mirror in `axon-frontend/src/smart_suggest.rs` — same loop
    bounds, same min(...) order — so both produce the same integer
    on every input pair (D7).
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Rolling-row DP. `prev[j]` holds the distance for `a[:i] →
    # b[:j]`; `curr[j]` is the row being built for `a[:i+1]`.
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, start=1):
        curr[0] = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev
    return prev[len(b)]


def suggest(
    unknown: str,
    candidates: Iterable[str],
    *,
    max_distance: int = MAX_DISTANCE,
    max_results: int = MAX_RESULTS,
) -> list[str]:
    """Return up to `max_results` candidates close enough to `unknown`.

    Candidates with Levenshtein distance ≤ `max_distance` are
    returned, sorted by ``(distance, candidate)`` ascending. Ties
    are broken alphabetically so the output is deterministic across
    runs (and across stacks — the Rust mirror sorts the same way).

    `unknown == ""` → empty list (no useful suggestion).
    Exact-match candidates (distance 0) are dropped — if the input
    already matches a candidate, the caller wouldn't be looking for
    a suggestion. Duplicate candidates in the input iterable are
    de-duplicated; insertion order is irrelevant.
    """
    if not unknown:
        return []
    seen: set[str] = set()
    scored: list[tuple[int, str]] = []
    for cand in candidates:
        if cand in seen or cand == unknown:
            continue
        seen.add(cand)
        d = levenshtein(unknown, cand)
        if d <= max_distance:
            scored.append((d, cand))
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [cand for _, cand in scored[:max_results]]


def format_suggestion_hint(suggestions: list[str]) -> str:
    """Format suggestion list into a sentence suffix.

    Empty list → empty string (caller appends nothing).
    Single match → ``"Did you mean `flow`?"``.
    Two+ matches → ``"Did you mean `flow`, `flow_v2`, or `flowery`?"``.

    Identical formatting to the Rust mirror so adopters get the
    same human-readable hint regardless of whether the diagnostic
    came from the Python parser or the Rust frontend (D7).
    """
    if not suggestions:
        return ""
    if len(suggestions) == 1:
        return f"Did you mean `{suggestions[0]}`?"
    if len(suggestions) == 2:
        return f"Did you mean `{suggestions[0]}` or `{suggestions[1]}`?"
    head = ", ".join(f"`{s}`" for s in suggestions[:-1])
    return f"Did you mean {head}, or `{suggestions[-1]}`?"


def suggest_for(unknown: str, candidates: Iterable[str]) -> str:
    """Convenience: ``suggest()`` + ``format_suggestion_hint()``.

    Returns the formatted hint directly (or empty string when no
    suggestion is close enough). Use this at the error-raising
    site to keep the call short:

        msg = "Unexpected token at top level"
        hint = suggest_for(tok.value, _TOP_LEVEL_KEYWORD_NAMES)
        if hint:
            msg = f"{msg}. {hint}"

    `unknown` and each candidate must be plain strings (no leading
    backticks etc. — those are added by the formatter).
    """
    return format_suggestion_hint(suggest(unknown, candidates))
