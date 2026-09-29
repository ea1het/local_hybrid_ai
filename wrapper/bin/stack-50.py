#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Stack 50 or explicitly start and stop Dockhand.

The wrapper invokes the Dockhand package's 01-prepare module, which may
create the external dockhand_data Docker volume when it is absent but never
replaces its existing contents. An existing regular .lock prevents further
preparation; it is never removed automatically. A fresh preparation must
return zero and create a regular lock. Start uses Compose up; stop preserves
the stopped container and external data volume instead of running down.
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
sys.path.insert(0, str(ROOT))
from wrapper.lib.stack_status import report_status
STACK_DIR = ROOT / "stack-50_-_dockhand"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-50_-_dockhand.01-prepare"


def show_start_instructions() -> None:
    """Explain how to start Dockhand manually without running Compose."""
    print("Stack 50 is PREPARED; Dockhand has not been started by this wrapper.")
    print("To start Dockhand manually, run:")
    print(f"  cd {shlex.quote(str(STACK_DIR))}")
    print("  docker compose --env-file .env -f docker-compose.yml up -d")


def install() -> int:
    """Respect .lock or run the package preparation module without stdin."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 50 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed and 01-prepare.py was not run.")
        print("Removing .lock manually would permit reconfiguration, which may overwrite")
        print("runtime configuration or disrupt a running service. Review first.")
        show_start_instructions()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 50 preparation requires root privileges.", file=sys.stderr)
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
        print("Stack 50 preparation failed; Dockhand was not started.", file=sys.stderr)
        return result.returncode
    if LOCK_FILE.is_symlink() or not LOCK_FILE.is_file():
        print("ERROR: preparation returned success without a regular .lock file.", file=sys.stderr)
        return 1

    show_start_instructions()
    return 0


def run_compose(action: str) -> int:
    """Run only this stack's requested Compose lifecycle action."""
    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: stack lifecycle operations require root privileges.", file=sys.stderr)
        return 1
    env_link = STACK_DIR / ".env"
    compose_file = STACK_DIR / "docker-compose.yml"
    if not env_link.is_symlink() or os.readlink(env_link) != "../.env" or not env_link.is_file():
        print(f"ERROR: missing or unexpected managed environment link: {env_link}", file=sys.stderr)
        return 1
    if compose_file.is_symlink() or not compose_file.is_file():
        print(f"ERROR: missing or unsafe Compose file: {compose_file}", file=sys.stderr)
        return 1
    if action == "up" and (LOCK_FILE.is_symlink() or not LOCK_FILE.is_file()):
        print(f"ERROR: stack is not prepared; missing regular lock: {LOCK_FILE}", file=sys.stderr)
        return 1

    command = ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml", action]
    if action == "up":
        command.append("-d")
    try:
        result = subprocess.run(
            command,
            cwd=STACK_DIR,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        print(f"ERROR: Docker Compose could not run: {error}", file=sys.stderr)
        return 1
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        print(f"Stack 50 Compose {action} failed.", file=sys.stderr)
        return result.returncode
    if action == "up":
        print("Stack 50 containers started; application readiness has not been verified.")
    else:
        print("Stack 50 container stopped but preserved; dockhand_data remains intact.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-50", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="Prepare without starting services").set_defaults(handler=install)
    commands.add_parser("start", help="Run Docker Compose up in detached mode").set_defaults(
        handler=lambda: run_compose("up")
    )
    commands.add_parser("stop", help="Run Docker Compose stop").set_defaults(
        handler=lambda: run_compose("stop")
    )
    status_parser = commands.add_parser("status", help="Report preparation and container health")
    status_parser.add_argument("--deep", action="store_true", help="Run additional read-only checks")
    options = parser.parse_args(argv)
    if options.command == "status":
        return report_status("50", STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
