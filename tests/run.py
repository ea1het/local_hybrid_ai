#!/usr/bin/env python3
"""Run the repository test suite without writing Python bytecode or pytest cache."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")]))
