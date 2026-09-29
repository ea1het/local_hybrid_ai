#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Stack 10 unattended and explain how to start it manually.

The wrapper invokes the stack's Python package rather than duplicating its
preparation logic. A preexisting .lock is an informational stop: it is never
removed, and no preparation command is run. A missing lock permits one
noninteractive preparation attempt; success requires both a zero exit status
and a new regular .lock. The wrapper never starts or restarts containers.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
STACK_DIR = ROOT / "stack-10_-_haproxy_web"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-10_-_haproxy_web.01-prepare"


def show_start_instructions() -> None:
    """Print the manual deployment command without running Docker Compose."""
    print("Stack 10 is PREPARED, not deployed or verified as running.")
    print("To start HAProxy and the web service manually, run:")
    print(f"  cd {shlex.quote(str(STACK_DIR))}")
    print("  docker compose --env-file .env -f docker-compose.yml up -d")


def install() -> int:
    """Respect the preparation lock or invoke the package once without stdin."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 10 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed and 01-prepare.py was not run.")
        print("Removing .lock manually would permit reconfiguration, which may overwrite")
        print("runtime configuration or disrupt a running service. Review first.")
        show_start_instructions()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 10 preparation requires root privileges.", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [sys.executable, "-B", "-m", PREPARE_MODULE],
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
        print("Stack 10 preparation failed; containers were not started.", file=sys.stderr)
        return result.returncode
    if LOCK_FILE.is_symlink() or not LOCK_FILE.is_file():
        print("ERROR: preparation returned success without a regular .lock file.", file=sys.stderr)
        return 1

    show_start_instructions()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="Prepare without starting services").set_defaults(handler=install)
    return parser.parse_args(argv).handler()


if __name__ == "__main__":
    raise SystemExit(main())
