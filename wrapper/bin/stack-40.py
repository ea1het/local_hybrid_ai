#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install Stack 40 without starting long-lived containers.

Install creates only Stack 40's service directories, prepares Gitea
configuration, and initializes the administrator in a
disposable container. Only then is .lock written. Start invokes Compose to
launch Gitea and its runner; it does not create the administrator.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wrapper.lib.cli_output import spaced_output
from wrapper.lib.progress import run_with_progress
from wrapper.lib.reconfig_dispatch import add_reconfig_command
from wrapper.lib.stack_status import report_status
STACK_DIR = ROOT / "stack-40_-_gitea"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-40_-_gitea.01-prepare"
INITIALIZE_MODULE = "stack-40_-_gitea.deploy-gitea"


def show_next_steps() -> None:
    """Show the explicit start operation after initialization."""
    print()
    print("Stack 40 is INSTALLED; Gitea and its runner are not running.")
    print("Start with: ./local-ai stack-40 start")


def install() -> int:
    """Prepare and initialize the administrator before writing .lock."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 40 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed.")
        print("Use ./local-ai stack-40 reconfig to update managed configuration safely.")
        show_next_steps()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 40 preparation requires root privileges.", file=sys.stderr)
        return 1
    platform_lock = ROOT / "stack-00_-_platform" / ".lock"
    if platform_lock.is_symlink() or not platform_lock.is_file():
        print(f"ERROR: Stack 00 is not prepared: {platform_lock}", file=sys.stderr)
        return 1

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH", "")) if part
    )
    bootstrap = run_with_progress("Preparing Stack 40 directories",
        [sys.executable, "-B", str(ROOT / "stack-00_-_platform" / "00-bootstrap.py"), "--stack", "40"],
        cwd=STACK_DIR, env=environment, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False,
    )
    if bootstrap.stdout:
        sys.stdout.write(bootstrap.stdout.lstrip("\n"))
    if bootstrap.stderr:
        sys.stderr.write(bootstrap.stderr)
    if bootstrap.returncode:
        print("Stack 40 directory preparation failed; no containers were started.", file=sys.stderr)
        return bootstrap.returncode
    print()
    for module in (PREPARE_MODULE, INITIALIZE_MODULE):
        if module == INITIALIZE_MODULE:
            print()
        result = run_with_progress(f"Running {module.rsplit('.', 1)[-1]}", [sys.executable, "-B", "-m", module], cwd=STACK_DIR,
                                env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False)
        if result.stdout:
            sys.stdout.write(result.stdout.lstrip("\n"))
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode:
            print(f"Stack 40 {module.rsplit('.', 1)[-1]} failed; no install lock was written.",
                  file=sys.stderr)
            return result.returncode
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    descriptor = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "w") as output:
        output.write(f"stack=stack-40_-_gitea\nprepared_at_utc={timestamp}\n")

    show_next_steps()
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
        result = run_with_progress("Running Stack 40 Compose",
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
        print(f"Stack 40 Compose {action} failed.", file=sys.stderr)
        return result.returncode
    print()
    if action == "up":
        print("Stack 40 containers started; application readiness has not been verified.")
    else:
        print("Stack 40 containers stopped and removed; persistent data and .lock remain.")
    return 0


@spaced_output
def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-40", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add_reconfig_command(commands, STACK_DIR)
    commands.add_parser("install", help="Prepare Gitea and initialize its administrator").set_defaults(handler=install)
    commands.add_parser("start", help="Run Docker Compose up in detached mode").set_defaults(
        handler=lambda: run_compose("up")
    )
    commands.add_parser("stop", help="Run Docker Compose down").set_defaults(
        handler=lambda: run_compose("down")
    )
    status_parser = commands.add_parser("status", help="Report preparation and container health")
    status_parser.add_argument("--deep", action="store_true", help="Run additional read-only checks")
    options = parser.parse_args(argv)
    if options.command == "status":
        return report_status("40", STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
