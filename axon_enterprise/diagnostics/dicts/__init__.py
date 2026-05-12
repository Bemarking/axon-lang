"""§Fase 29.d — Vertical-suggest dictionary data files.

Per-vertical JSON dictionaries with D3-mandated provenance per entry.
Loaded by :mod:`axon_enterprise.diagnostics.suggest_dicts`.

Each file's on-disk shape::

    {
      "vertical": "<slug>",
      "version": "<semver>",
      "description": "<one-line summary + provenance class>",
      "license_note": "<licensing posture for the terminology corpus>",
      "entries": [
        {"term": "...", "category": "...", "provenance": "<URL or citation>"},
        ...
      ]
    }

Updates ship as PRs labeled ``vertical-dict:<vertical>`` with
CODEOWNERS sign-off from the respective vertical reviewer (D7
ratificada).
"""
