"""Centralized disaster-recovery tests.

Production DR modules remain under ``bkp-dr``.  The test package has a distinct
name (``disaster_recovery``), so it can safely prepend the implementation
directory to ``sys.path`` without shadowing the production ``dr.py`` module.
"""
from pathlib import Path
import sys

DR_ROOT = Path(__file__).resolve().parents[2] / "bkp-dr"
if str(DR_ROOT) not in sys.path:
    sys.path.insert(0, str(DR_ROOT))
