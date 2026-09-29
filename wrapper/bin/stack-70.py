#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bootstrap and prepare Stack 70 without deploying Open WebUI.

On a fresh installation, this entrypoint calls the stack package's
00-bootstrap and 01-prepare modules in order. Bootstrap backs up the root
.env before changes and obtains a LiteLLM key scoped to all currently visible
models if one is missing. An existing preparation lock skips both modules.
The wrapper reports manual startup instructions but never starts containers.
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
STACK_DIR = ROOT / "stack-70_-_open-webui"
LOCK_FILE = STACK_DIR / ".lock"
BOOTSTRAP_MODULE = "stack-70_-_open-webui.00-bootstrap"
PREPARE_MODULE = "stack-70_-_open-webui.01-prepare"


def show_next_steps() -> None:
    """Print the manual deployment command after preparation."""
    print("Stack 70 is PREPARED; Open WebUI has not been started.")
    print("To start the stack manually, run:")
    print(f"  cd {shlex.quote(str(STACK_DIR))}")
    print("  docker compose --env-file .env -f docker-compose.yml up -d --build")


def install() -> int:
    """Skip a locked stack or run bootstrap followed by preparation."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 70 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed; bootstrap and prepare were not run.")
        print("Removing .lock manually would permit reconfiguration, which may overwrite")
        print("runtime configuration or disrupt a running service. Review first.")
        show_next_steps()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 70 preparation requires root privileges.", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH", "")) if part
    )
    for module in (BOOTSTRAP_MODULE, PREPARE_MODULE):
        result = subprocess.run(
            [sys.executable, "-B", "-m", module],
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
            print(f"Stack 70 {module.rsplit('.', 1)[-1]} failed; deployment was not started.",
                  file=sys.stderr)
            return result.returncode

    if LOCK_FILE.is_symlink() or not LOCK_FILE.is_file():
        print("ERROR: preparation returned success without a regular .lock file.", file=sys.stderr)
        return 1

    show_next_steps()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="Bootstrap and prepare without starting services").set_defaults(handler=install)
    return parser.parse_args(argv).handler()


if __name__ == "__main__":
    raise SystemExit(main())
