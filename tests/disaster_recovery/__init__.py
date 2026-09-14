# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Centralized disaster-recovery tests.

Production DR modules live under ``commands/recovery``. The test package keeps a
distinct name so legacy module imports used inside the DR implementation can be
resolved without exposing those modules as public management entry points.
"""
from pathlib import Path
import sys

DR_ROOT = Path(__file__).resolve().parents[2] / "commands" / "recovery"
if str(DR_ROOT) not in sys.path:
    sys.path.insert(0, str(DR_ROOT))
