# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Tests for the restore command package.

Production DR modules under ``src/local_ai_cli/restore`` and ``src/local_ai_cli/backup`` import
each other by short flat name (e.g. ``import dr_stack4_backup``), relying on
their own directory being on ``sys.path``. Historical tests do the same, so both
package roots are exposed for the duration of that migration.
"""
from pathlib import Path
import sys

_PACKAGES_ROOT = Path(__file__).resolve().parents[2] / "src" / "local_ai_cli"
for _package in ("restore", "backup"):
    _package_root = _PACKAGES_ROOT / _package
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))
# backup is inserted last so its dr_stack4_backup.py (which restore's own
# dr_stack4_inspect.py depends on for GITEA_RESOURCE_ID) wins the ambiguous name.
