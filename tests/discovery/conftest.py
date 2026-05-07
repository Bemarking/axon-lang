"""Test fixtures local to tests/discovery/.

Ensures the compliance blob path is set to a platform-portable absolute
path BEFORE settings are loaded. The default ``/var/lib/axon/compliance``
is treated as relative on Windows and breaks even no-op settings access.
This setup runs at module-import time so it precedes any
``get_settings()`` call in the test files.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault(
    "AXON_COMPLIANCE_BLOB_LOCAL_PATH",
    os.path.join(tempfile.gettempdir(), "axon-test-compliance"),
)
