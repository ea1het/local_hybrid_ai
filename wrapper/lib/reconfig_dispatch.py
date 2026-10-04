"""Delegate reconfiguration to a stack-owned, directly runnable module."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from wrapper.lib.progress import run_with_progress


def run_reconfig(stack_dir: Path) -> int:
    """Relay the stack module's output and exit status without changing containers."""
    module = stack_dir / "reconfig.py"
    if module.is_symlink() or not module.is_file():
        print(f"ERROR: missing or unsafe stack reconfiguration module: {module}", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = run_with_progress(
        f"Reconfiguring {stack_dir.name}",
        [sys.executable, "-B", str(module)],
        cwd=stack_dir,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        sys.stdout.write(result.stdout.lstrip("\n"))
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode
