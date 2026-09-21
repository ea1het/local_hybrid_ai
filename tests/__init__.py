#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Repository test suite, mirroring the src/local_ai_cli package layout.

Top-level modules here test local_ai_cli/cli.py, the sole dispatcher; each
subdirectory tests the same-named local_ai_cli subpackage; tests/common/
tests the shared local_ai_cli.common primitives; tests/repository/ protects
repository-wide contracts (documentation, licensing, layout, OpenSpec,
stack-owned behaviour) that exercise no local_ai_cli code at all.

local_ai_cli is not pip-installed; it is imported straight from ``src/`` by
adding that directory to sys.path here, once, before any test module runs.
"""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
