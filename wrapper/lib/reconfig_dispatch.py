# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Delegate reconfiguration to a stack-owned, directly runnable module."""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from wrapper.lib.progress import run_with_progress


def add_reconfig_command(commands: argparse._SubParsersAction, stack_dir: Path) -> None:
    """Build CLI help from the stack module's docstring, not wrapper prose."""
    module = stack_dir / "reconfig.py"
    description = (ast.get_docstring(ast.parse(module.read_text()))
                   if module.is_file() and not module.is_symlink() else None) or "Reconfigure this stack."
    parser = commands.add_parser(
        "reconfig", help=description.splitlines()[0], description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    parser.set_defaults(handler=lambda apply=False: run_reconfig(stack_dir, apply=apply))


def run_reconfig(stack_dir: Path, apply: bool = False) -> int:
    """Relay the stack module's output and exit status without changing containers."""
    module = stack_dir / "reconfig.py"
    if module.is_symlink() or not module.is_file():
        print(f"ERROR: missing or unsafe stack reconfiguration module: {module}", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", str(module)]
    if apply:
        command.append("--apply")
    result = run_with_progress(
        f"Reconfiguring {stack_dir.name}",
        command,
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
