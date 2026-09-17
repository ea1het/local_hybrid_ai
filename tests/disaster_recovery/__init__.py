# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Centralized disaster-recovery tests for package-owned Backup and Restore.

Production DR implementation is split between ``commands/backup`` and
``commands/restore``. Historical tests import the implementation modules by their
short names, so expose both package roots for the duration of the migration while
keeping ``commands/recovery`` completely out of the test bootstrap.
"""
from pathlib import Path
import sys

COMMANDS_ROOT = Path(__file__).resolve().parents[2] / "commands"
for package in ("restore", "backup"):
    package_root = COMMANDS_ROOT / package
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
