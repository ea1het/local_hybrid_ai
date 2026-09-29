#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Execute the repository's pytest suite without local cache artifacts.

This entrypoint adds the repository root to Python's import path, disables
bytecode writes, and invokes pytest with its cache provider disabled.
It is intended as the deterministic local validation command; importing
the module alone does not start a test run."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")]))
