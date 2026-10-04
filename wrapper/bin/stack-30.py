#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install Stack 30, including PostgreSQL and minimal LiteLLM access.

Install creates Stack 30's service directories, prepares configuration,
provisions the database and editable oMLX models, issues three
least-privilege consumer keys in a disposable LiteLLM container, and writes
.lock only after every phase succeeds. It stops PostgreSQL if install started
it. Start and stop remain explicit; install never tests model inference.
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
STACK_DIR = ROOT / "stack-30_-_litellm"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-30_-_litellm.01-prepare"
PROVISION_MODULE = "stack-30_-_litellm.provision-postgres"
KEYS_MODULE = "stack-30_-_litellm.issue-consumer-keys"


def show_next_steps() -> None:
    """Explain how to start the installed stack without claiming readiness."""
    print()
    print("Stack 30 is INSTALLED; no services were started for ongoing operation.")
    print("Start with: ./local-ai stack-30 start")
    print("Model inference and oMLX reachability remain for a later verify phase.")


def install() -> int:
    """Complete preparation, provisioning, and key setup before locking."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 30 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed.")
        print("Removing .lock manually would permit reconfiguration, which may overwrite")
        print("runtime configuration or disrupt a running service. Review first.")
        show_next_steps()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 30 preparation requires root privileges.", file=sys.stderr)
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
    bootstrap = run_with_progress("Preparing Stack 30 directories",
        [sys.executable, "-B", str(ROOT / "stack-00_-_platform" / "00-bootstrap.py"), "--stack", "30"],
        cwd=STACK_DIR, env=environment, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False,
    )
    if bootstrap.stdout:
        sys.stdout.write(bootstrap.stdout.lstrip("\n"))
    if bootstrap.stderr:
        sys.stderr.write(bootstrap.stderr)
    if bootstrap.returncode:
        print("Stack 30 directory preparation failed; no containers were started.", file=sys.stderr)
        return bootstrap.returncode
    print()
    running = run_with_progress("Checking Stack 30 PostgreSQL", ["docker", "inspect", "-f", "{{.State.Running}}", "litellm-postgres"],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    postgres_was_running = running.returncode == 0 and running.stdout.strip() == "true"
    provision_attempted = False
    phase_exit = 0
    stop_failed = False
    try:
        for module in (PREPARE_MODULE, PROVISION_MODULE, KEYS_MODULE):
            if module == PROVISION_MODULE:
                provision_attempted = True
            if module != PREPARE_MODULE:
                print()
            result = run_with_progress(f"Running {module.rsplit('.', 1)[-1]}", [sys.executable, "-B", "-m", module], cwd=STACK_DIR,
                                    env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, check=False)
            if result.stdout:
                sys.stdout.write(result.stdout.lstrip("\n"))
            if result.stderr:
                sys.stderr.write(result.stderr)
            if result.returncode:
                print(f"Stack 30 {module.rsplit('.', 1)[-1]} failed; no install lock was written.",
                      file=sys.stderr)
                phase_exit = result.returncode
                break
    finally:
        if provision_attempted and not postgres_was_running:
            stopped = run_with_progress("Stopping temporary Stack 30 PostgreSQL", ["docker", "compose", "--env-file", ".env", "-f",
                                      "docker-compose.yml", "stop", "litellm-postgres"],
                                     cwd=STACK_DIR, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, check=False)
            if stopped.returncode:
                print("ERROR: could not stop installation-only PostgreSQL container.", file=sys.stderr)
                stop_failed = True
    if phase_exit or stop_failed:
        return phase_exit or 1
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    descriptor = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "w") as output:
        output.write(f"stack=stack-30_-_litellm\nprepared_at_utc={timestamp}\n")

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
        result = run_with_progress("Running Stack 30 Compose",
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
        print(f"Stack 30 Compose {action} failed.", file=sys.stderr)
        return result.returncode
    print()
    if action == "up":
        print("Stack 30 containers started; application readiness has not been verified.")
    else:
        print("Stack 30 containers stopped and removed; persistent data and .lock remain.")
    return 0


@spaced_output
def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-30", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add_reconfig_command(commands, STACK_DIR)
    commands.add_parser("install", help="Provision PostgreSQL and minimal LiteLLM access").set_defaults(handler=install)
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
        return report_status("30", STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
