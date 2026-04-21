"""DB-specific fixtures.

All shared integration plumbing (Postgres container, Alembic runner,
``migrated_db`` engine, ``db_session``) now lives in the top-level
``tests/conftest.py`` so identity, audit, metering, etc. tests can use
the same fixtures without copy-paste.

Nothing extra is needed here at the moment; file kept for future
db-only helpers.
"""

from __future__ import annotations
