"""DR test package bootstrap.

DR implementation modules intentionally remain under ``bkp-dr``. Centralizing the
tests must not force production modules into the repository root, so discovery
adds that implementation directory to ``sys.path`` before importing test modules.
"""
from pathlib import Path
import sys

DR_ROOT = Path(__file__).resolve().parents[2] / "bkp-dr"
if str(DR_ROOT) not in sys.path:
    sys.path.insert(0, str(DR_ROOT))
