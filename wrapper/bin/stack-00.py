#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reconcile and verify the platform foundation without deploying containers.

Stack 00 is special: its lock never suppresses the installation audit. The
stack-owned install module checks and repairs each platform prerequisite,
then verifies the complete result before creating or retaining the lock.
Certificate rotation remains an explicit operation, not a wrapper side effect.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wrapper.lib.stack_status import report_platform_status
STACK_DIR = ROOT / "stack-00_-_platform"
LOCK_FILE = STACK_DIR / ".lock"
INSTALL_MODULE = "stack-00_-_platform.install"


def install() -> int:
    """Run a noninteractive platform audit and relay its result."""
    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if LOCK_FILE.is_symlink() or (LOCK_FILE.exists() and not LOCK_FILE.is_file()):
        print(f"ERROR: unsafe preparation lock: {LOCK_FILE}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: Stack 00 reconciliation requires root privileges.", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [sys.executable, "-B", "-m", INSTALL_MODULE],
        cwd=STACK_DIR,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        print("Stack 00 reconciliation failed; inspect the audit and lock state.", file=sys.stderr)
        return result.returncode
    if LOCK_FILE.is_symlink() or not LOCK_FILE.is_file():
        print("ERROR: installation returned success without a regular .lock file.", file=sys.stderr)
        return 1
    print("Stack 00 is PREPARED; no application containers were started.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="Reconcile and verify platform prerequisites").set_defaults(handler=install)
    status_parser = commands.add_parser("status", help="Report preparation and container health")
    status_parser.add_argument("--deep", action="store_true", help="Run additional read-only checks")
    options = parser.parse_args(argv)
    if options.command == "status":
        return report_platform_status(STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
