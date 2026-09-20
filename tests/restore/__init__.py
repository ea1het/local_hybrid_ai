#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Tests for the restore command package.

Production DR modules under ``src/local_ai_cli/restore`` import each other by
short flat name (e.g. ``import _restore_all``), relying on their own directory
being on ``sys.path``. Historical tests do the same, so the package root is
exposed for the duration of that migration. Restore no longer depends on
backup's internals (shared Gitea dump validation lives in
``local_ai_cli.common.gitea_archive``), so backup's directory is not exposed here.
"""
from pathlib import Path
import sys

_package_root = Path(__file__).resolve().parents[2] / "src" / "local_ai_cli" / "restore"
if str(_package_root) not in sys.path:
    sys.path.insert(0, str(_package_root))
