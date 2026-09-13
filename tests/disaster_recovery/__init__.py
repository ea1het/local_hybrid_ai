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
