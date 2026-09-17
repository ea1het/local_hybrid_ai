#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Restore-owned compatibility adapter for the DR planner.

The implementation is intentionally duplicated from the recovery domain while
packages are being closed.  This adapter fixes repository-relative paths for
the copy living under commands/restore.
"""
from commands.recovery.dr import *

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
