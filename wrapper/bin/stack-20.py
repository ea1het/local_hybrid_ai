#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Stack 20 or control its Compose containers explicitly.

The wrapper creates only Stack 20's platform-owned directories, then calls
the SearXNG/Firecrawl package's preparation module and
relays its output to the operator. An existing regular .lock prevents any
preparation attempt; removing it for reconfiguration is an explicit manual
decision. A successful run must create a regular lock. The wrapper only
prints the subsequent Docker Compose start command without running it; the
separate start and stop verbs operate on containers without checking readiness.
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
from wrapper.lib.cli_output import spaced_output
from wrapper.lib.progress import run_with_progress
from wrapper.lib.reconfig_dispatch import add_reconfig_command
from wrapper.lib.stack_status import report_status
from wrapper.stubs.bootstrap_env import BootstrapError, assignments, protected_text
STACK_DIR = ROOT / "stack-20_-_searxng_firecrawl"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-20_-_searxng_firecrawl.01-prepare"


def configuration_error() -> str | None:
    """Detect missing or replaced files that the preparation lock certifies."""
    try:
        values = assignments(protected_text((STACK_DIR / ".env").resolve()))
        base_path = values.get("BASE_PATH", "")
        if not base_path.startswith("/"):
            return "BASE_PATH is missing or not absolute in .env"
        config_dir = Path(base_path) / "service_-_searxng/config"
        for name in ("settings.yml", "limiter.toml", "favicons.toml"):
            source = STACK_DIR / "config/searxng" / name
            target = config_dir / name
            if (not source.is_file() or source.is_symlink() or not target.is_file()
                    or target.is_symlink() or source.read_bytes() != target.read_bytes()):
                return f"missing or changed managed SearXNG configuration: {target}"
    except (BootstrapError, OSError, ValueError) as error:
        return f"cannot verify SearXNG configuration: {error}"
    return None


def show_start_instructions() -> None:
    """Describe the wrapper start command without starting search services."""
    print()
    print("Stack 20 is PREPARED, not deployed or verified as ready.")
    print("To start SearXNG and Firecrawl, run from the repository root:")
    print("  ./local-ai stack-20 start")


def install() -> int:
    """Respect .lock or run one noninteractive package preparation attempt."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        error = configuration_error()
        if error:
            print(f"ERROR: {error}; .lock alone does not certify the current runtime.", file=sys.stderr)
            return 1
        print(f"Stack 20 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed and 01-prepare.py was not run.")
        print("Use ./local-ai stack-20 reconfig to stage managed configuration safely.")
        show_start_instructions()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 20 preparation requires root privileges.", file=sys.stderr)
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
    commands = (
        [sys.executable, "-B", str(ROOT / "stack-00_-_platform" / "00-bootstrap.py"), "--stack", "20"],
        [sys.executable, "-B", "-m", PREPARE_MODULE],
    )
    for command in commands:
        result = run_with_progress("Preparing Stack 20",
            command,
            cwd=STACK_DIR,
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
        if result.returncode:
            print("Stack 20 preparation failed; containers were not started.", file=sys.stderr)
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
    if action == "up":
        error = configuration_error()
        if error:
            print(f"ERROR: {error}; run ./local-ai stack-20 reconfig before starting Stack 20.",
                  file=sys.stderr)
            return 1

    command = ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml", action]
    if action == "up":
        command.append("-d")
    try:
        result = run_with_progress("Running Stack 20 Compose",
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
        print(f"Stack 20 Compose {action} failed.", file=sys.stderr)
        return result.returncode
    print()
    if action == "up":
        print("Stack 20 containers started; application readiness has not been verified.")
    else:
        print("Stack 20 containers stopped and removed; persistent data and .lock remain.")
    return 0


@spaced_output
def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-20", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add_reconfig_command(commands, STACK_DIR)
    commands.add_parser("install", help="Prepare without starting services").set_defaults(handler=install)
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
        return report_status("20", STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
