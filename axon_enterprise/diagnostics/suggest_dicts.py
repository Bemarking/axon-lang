"""§Fase 29.d — Vertical-aware suggest dictionaries.

D3 + D7 + D8 ratificadas 2026-05-12.

## What this module ships

Loader + accessor surface for the per-vertical dictionaries that
extend the OSS Fase 28 Levenshtein suggest hints (`'Did you mean X?'`)
with vertical-specific glossary terms. Closed-catalog mapping from
:class:`TenantVertical` to a list of :class:`DictEntry` records.

The dictionaries themselves are version-controlled JSON files living
in ``axon_enterprise/diagnostics/dicts/``. Each entry carries:

- ``term`` — the dictionary token surfaced to the Levenshtein hint.
- ``provenance`` — explicit URL or canonical regulatory reference
  (D3 ratificada).
- ``category`` — coarse-grained grouping (``compliance``,
  ``security``, ``aml``, ``privilege``, etc.) for dashboard filtering.

D3 ratificada: every entry **MUST** carry a non-empty ``provenance``
tag. The loader rejects entries that violate this contract at
module-load time; PR reviews per D7 enforce sign-off from the
respective vertical's tech lead before a malformed entry can ship.

D7 ratificada: dictionary updates ship as separate PRs labeled
``vertical-dict:<vertical>``. CODEOWNERS in ``axon_enterprise/diagnostics/dicts/``
enforces the per-vertical reviewer sign-off.

D8 ratificada (multi-vertical safety): loading the HIPAA dictionary
MUST NEVER surface legal or fintech terms, and vice versa. The
loader's API is keyed on :class:`TenantVertical` so cross-vertical
contamination is statically prevented.

D9 ratificada (backwards-compat): the GENERIC vertical has NO
dictionary entries; generic tenants get the OSS Fase 28 suggest
surface verbatim.

## Integration with DiagnosticPolicy

The :class:`DiagnosticPolicy` from 29.b plumbed an ``extra_keywords``
tuple field for exactly this purpose. The
:func:`policy_with_suggest_dict` helper produces a new policy whose
``extra_keywords`` field contains the resolved vertical's term tuple,
ready to be passed to the parser invocation wrapper (29.f wires the
wrapper end-to-end).

## On-disk layout

::

    axon_enterprise/
      diagnostics/
        suggest_dicts.py     ← this file (loader + accessors)
        dicts/
          hipaa.json         ← ~50 terms, 45 CFR Parts 160/164 provenance
          legal.json         ← ~50 terms, FRE/FRCP/ABA Model Rules provenance
          fintech.json       ← ~50 terms, BSA/PCI DSS/FATF provenance

Generic vertical has NO file (and no entries).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from axon_enterprise.diagnostics.policy import (
    DiagnosticPolicy,
    TenantVertical,
)

# ──────────────────────────────────────────────────────────────────
#  Dictionary entry shape
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DictEntry:
    """One entry in a vertical-suggest dictionary.

    Frozen + slots — entries are loaded once at module import (or
    first-use lazy load) and reused for the process lifetime. The
    immutability makes the loaded dictionaries shareable across
    threads without locks.
    """

    term: str
    provenance: str
    category: str

    def __post_init__(self) -> None:
        # D3 ratificada — every entry MUST carry non-empty provenance.
        if not self.provenance or not self.provenance.strip():
            raise ValueError(
                f"DictEntry term={self.term!r} violates D3: provenance must be "
                "a non-empty URL / canonical reference"
            )
        if not self.term or not self.term.strip():
            raise ValueError(
                f"DictEntry provenance={self.provenance!r} has empty term — invalid"
            )
        if not self.category or not self.category.strip():
            raise ValueError(
                f"DictEntry term={self.term!r} has empty category — invalid"
            )


@dataclass(frozen=True, slots=True)
class VerticalDictionary:
    """Loaded vertical-specific suggest dictionary.

    Frozen + slots. ``entries`` is a tuple (not list) so the
    dictionary is hashable + safely shareable across threads.
    """

    vertical: TenantVertical
    version: str
    description: str
    entries: tuple[DictEntry, ...]

    @property
    def terms(self) -> tuple[str, ...]:
        """Flat tuple of every term — the shape `DiagnosticPolicy.extra_keywords`
        consumes."""
        return tuple(e.term for e in self.entries)

    def category_for(self, term: str) -> str | None:
        """Return the category for ``term`` or None when absent.
        Useful for the 29.e dashboard surface that groups by category.
        """
        for e in self.entries:
            if e.term == term:
                return e.category
        return None

    def provenance_for(self, term: str) -> str | None:
        """Return the provenance reference for ``term``. Audit /
        compliance dashboards cite this when surfacing the term.
        """
        for e in self.entries:
            if e.term == term:
                return e.provenance
        return None


# ──────────────────────────────────────────────────────────────────
#  Loader (lazy + cached per-vertical)
# ──────────────────────────────────────────────────────────────────


# Module-level cache of loaded dictionaries. Populated lazily on first
# request per vertical; subsequent requests return the cached
# instance. Cache is process-local (no cross-process invalidation).
_CACHE: dict[TenantVertical, VerticalDictionary] = {}
_CACHE_LOCK = threading.RLock()


# Verticals that ship a dictionary file. Generic deliberately
# does NOT — generic tenants get the OSS Fase 28 surface unchanged (D9).
_VERTICALS_WITH_DICT: frozenset[TenantVertical] = frozenset(
    {
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    }
)


def _dict_path(vertical: TenantVertical) -> Path:
    """Return the on-disk path to a vertical's dictionary file.
    Internal — callers use :func:`load_vertical_dictionary`.
    """
    # ``importlib.resources.files`` works whether the package is
    # imported from source tree or from an installed wheel.
    return Path(str(files("axon_enterprise.diagnostics.dicts").joinpath(f"{vertical.value}.json")))


def _empty_dictionary(vertical: TenantVertical) -> VerticalDictionary:
    """Construct an empty VerticalDictionary for verticals without
    a dict file (currently only GENERIC).
    """
    return VerticalDictionary(
        vertical=vertical,
        version="0.0.0",
        description=(
            f"No vertical-specific dictionary for {vertical.value}; tenants "
            "use the OSS Fase 28 suggest surface unchanged (D9)."
        ),
        entries=(),
    )


def _validate_payload(payload: dict[str, Any], vertical: TenantVertical) -> None:
    """Validate the JSON payload's shape + D3 + D8 invariants.

    D8 multi-vertical safety: the payload's ``vertical`` field MUST
    match the loader argument. A mismatch indicates either a
    misnamed file or a copy-paste error that would leak terms
    across verticals — fail loud rather than silently fan out.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"dict file for {vertical.value} must be a JSON object")
    payload_vertical = payload.get("vertical")
    if payload_vertical != vertical.value:
        raise ValueError(
            f"D8 violation: dict file for {vertical.value} declares "
            f"vertical={payload_vertical!r} (cross-vertical contamination)"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(
            f"dict file for {vertical.value} must carry an 'entries' list"
        )


def _parse_entries(raw_entries: list[Any], vertical: TenantVertical) -> tuple[DictEntry, ...]:
    """Build the DictEntry tuple from the raw JSON payload. Each
    DictEntry's `__post_init__` enforces D3 provenance + non-empty
    fields. Duplicate terms within a single vertical are rejected
    (D8 — adopters relying on the dict should see consistent terms).
    """
    seen: set[str] = set()
    entries: list[DictEntry] = []
    for idx, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ValueError(
                f"entry #{idx} in {vertical.value} dict must be a JSON object"
            )
        term = raw.get("term", "")
        if term in seen:
            raise ValueError(
                f"duplicate term {term!r} in {vertical.value} dict (entry #{idx})"
            )
        entry = DictEntry(
            term=term,
            provenance=raw.get("provenance", ""),
            category=raw.get("category", ""),
        )
        seen.add(entry.term)
        entries.append(entry)
    return tuple(entries)


def load_vertical_dictionary(vertical: TenantVertical) -> VerticalDictionary:
    """Load the dictionary for ``vertical``. Cached per-process after
    first call.

    Generic vertical returns an empty :class:`VerticalDictionary`
    (D9 — generic tenants get the OSS surface unchanged).

    Verticals with a dict file (HIPAA / legal / fintech) load the
    JSON, validate the D3 provenance + D8 vertical-match invariants,
    and cache the result.
    """
    with _CACHE_LOCK:
        cached = _CACHE.get(vertical)
        if cached is not None:
            return cached

        if vertical not in _VERTICALS_WITH_DICT:
            loaded = _empty_dictionary(vertical)
            _CACHE[vertical] = loaded
            return loaded

        path = _dict_path(vertical)
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        _validate_payload(payload, vertical)
        entries = _parse_entries(payload["entries"], vertical)

        loaded = VerticalDictionary(
            vertical=vertical,
            version=payload.get("version", "0.0.0"),
            description=payload.get("description", ""),
            entries=entries,
        )
        _CACHE[vertical] = loaded
        return loaded


def clear_dictionary_cache() -> None:
    """Drop every cached dictionary. Tests use this between cases;
    not intended for production code paths.
    """
    with _CACHE_LOCK:
        _CACHE.clear()


def terms_for_vertical(vertical: TenantVertical) -> tuple[str, ...]:
    """Flat term tuple for ``vertical``. Convenience over
    ``load_vertical_dictionary(vertical).terms``.
    """
    return load_vertical_dictionary(vertical).terms


# ──────────────────────────────────────────────────────────────────
#  Integration with DiagnosticPolicy
# ──────────────────────────────────────────────────────────────────


def policy_with_suggest_dict(policy: DiagnosticPolicy) -> DiagnosticPolicy:
    """Return a new :class:`DiagnosticPolicy` whose ``extra_keywords``
    field is populated with the resolved vertical's term tuple.

    Used by the parser-invocation wrapper (29.f integration):

        policy = resolve_policy_for_current_tenant()
        policy = policy_with_suggest_dict(policy)
        # `policy.extra_keywords` now carries the vertical-specific
        # glossary terms ready for the Levenshtein hint engine.

    Idempotent: calling this twice for the same policy keeps the same
    extra_keywords (cached dictionary is identical).
    """
    terms = terms_for_vertical(policy.vertical)
    return policy.with_override(extra_keywords=terms)


def resolve_policy_with_dict_for_vertical(
    vertical: TenantVertical,
) -> DiagnosticPolicy:
    """One-shot convenience: resolve the default policy for ``vertical``
    and immediately enrich it with the vertical's suggest dictionary.

    Equivalent to::

        policy_with_suggest_dict(resolve_policy_for_vertical(vertical))
    """
    from axon_enterprise.diagnostics.policy import resolve_policy_for_vertical

    return policy_with_suggest_dict(resolve_policy_for_vertical(vertical))


# ──────────────────────────────────────────────────────────────────
#  D8 cross-vertical leak detection helper
# ──────────────────────────────────────────────────────────────────


def assert_no_cross_vertical_contamination() -> dict[TenantVertical, frozenset[str]]:
    """Load every vertical's dictionary and assert no term appears
    in more than one vertical (D8 multi-vertical safety).

    Returns a snapshot of ``{vertical: frozenset(terms)}`` for
    introspection. Raises :class:`ValueError` on contamination so
    the 29.g CI lane can call this as a one-line gate.
    """
    snapshots: dict[TenantVertical, frozenset[str]] = {}
    for vertical in _VERTICALS_WITH_DICT:
        snapshots[vertical] = frozenset(terms_for_vertical(vertical))

    # Pairwise check — every pair of distinct verticals must have
    # disjoint term sets.
    verticals = sorted(snapshots.keys(), key=lambda v: v.value)
    for i in range(len(verticals)):
        for j in range(i + 1, len(verticals)):
            a, b = verticals[i], verticals[j]
            overlap = snapshots[a] & snapshots[b]
            if overlap:
                raise ValueError(
                    f"D8 violation: term(s) {sorted(overlap)} appear in BOTH "
                    f"{a.value} and {b.value} dictionaries — cross-vertical "
                    "contamination"
                )

    return snapshots


__all__ = [
    "DictEntry",
    "VerticalDictionary",
    "assert_no_cross_vertical_contamination",
    "clear_dictionary_cache",
    "load_vertical_dictionary",
    "policy_with_suggest_dict",
    "resolve_policy_with_dict_for_vertical",
    "terms_for_vertical",
]
