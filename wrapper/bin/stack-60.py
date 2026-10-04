#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Stack 60 or control its Compose containers explicitly.

Install first creates Stack 60's service directories with the scoped platform
bootstrap, then invokes the Hermes package's 01-prepare module. It relays the
preparation audit output, stops without changes when a regular .lock already
exists, and requires a new regular lock after successful execution.
Install never starts containers. Start and stop change only Compose state;
neither installs Buzz, adopts Git memory, prepares sidecars, reconciles
capabilities, applies workarounds, or cleans up state.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wrapper.lib.cli_output import spaced_output
from wrapper.lib.hermes_runtime_env import (RuntimeEnvironmentError, config_needs_update,
                                            needs_update, reconcile, reconcile_config)
from wrapper.lib.progress import run_with_progress
from wrapper.lib.reconfig_dispatch import run_reconfig
from wrapper.lib.stack_status import report_status
from wrapper.stubs.bootstrap_env import BootstrapError, assignments, protected_text
STACK_DIR = ROOT / "stack-60_-_hermes"
LOCK_FILE = STACK_DIR / ".lock"
PREPARE_MODULE = "stack-60_-_hermes.01-prepare"


def show_next_steps() -> None:
    """Identify the wrapper start command without triggering optional capabilities."""
    print()
    print("Stack 60 is PREPARED; Hermes and its sandbox are not verified as running.")
    print("To start the default stack, run from the repository root:")
    print("  ./local-ai stack-60 start")
    print("Buzz, Git memory, sidecars, reconciliation, and cleanup are separate operations.")


def install() -> int:
    """Respect .lock or bootstrap directories and prepare Hermes noninteractively."""
    if LOCK_FILE.is_symlink():
        print(f"ERROR: {LOCK_FILE} is a symbolic link; review it manually.", file=sys.stderr)
        return 1
    if LOCK_FILE.exists():
        if not LOCK_FILE.is_file():
            print(f"ERROR: {LOCK_FILE} is not a regular file.", file=sys.stderr)
            return 1
        print(f"Stack 60 already has a preparation lock: {LOCK_FILE}")
        print("No configuration was changed; bootstrap and prepare were not run.")
        print("Use ./local-ai stack-60 reconfig to stage managed configuration safely.")
        show_next_steps()
        return 0

    if not STACK_DIR.is_dir():
        print(f"ERROR: missing stack directory: {STACK_DIR}", file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: initial Stack 60 preparation requires root privileges.", file=sys.stderr)
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
    bootstrap = run_with_progress("Preparing Stack 60 directories",
        [sys.executable, "-B", str(ROOT / "stack-00_-_platform" / "00-bootstrap.py"), "--stack", "60"],
        cwd=STACK_DIR,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.stdout:
        sys.stdout.write(bootstrap.stdout.lstrip("\n"))
    if bootstrap.stderr:
        sys.stderr.write(bootstrap.stderr)
    if bootstrap.returncode:
        print("Stack 60 directory preparation failed; no containers were started.", file=sys.stderr)
        return bootstrap.returncode
    print()
    result = run_with_progress("Preparing Stack 60 Hermes runtime",
        [sys.executable, "-B", "-m", PREPARE_MODULE],
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
        print("Stack 60 preparation failed; no optional operation was started.", file=sys.stderr)
        return result.returncode
    if LOCK_FILE.is_symlink() or not LOCK_FILE.is_file():
        print("ERROR: preparation returned success without a regular .lock file.", file=sys.stderr)
        return 1

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

    command = ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml"]
    gateway_changed = False
    if action == "up":
        try:
            values = assignments(protected_text(env_link.resolve()))
            if values.get("TELEGRAM_BOT_TOKEN"):
                if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", values["TELEGRAM_BOT_TOKEN"]):
                    raise RuntimeEnvironmentError("TELEGRAM_BOT_TOKEN does not match the expected BotFather format")
                if not re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)*", values.get("TELEGRAM_ALLOWED_USERS", "")):
                    raise RuntimeEnvironmentError("TELEGRAM_ALLOWED_USERS must list numeric user IDs when Telegram is enabled")
            base_path = values.get("BASE_PATH", "")
            service = values.get("HERMES_SERVICE", "")
            if (not base_path.startswith("/") or not service.startswith("service_-_")
                    or Path(service).name != service):
                raise RuntimeEnvironmentError("invalid Hermes runtime location in .env")
            runtime_env = Path(base_path) / service / "data/.env"
            managed_config = Path(base_path) / service / "config/config.yaml"
            managed_keys = frozenset(values)
            if needs_update(runtime_env, managed_keys) or config_needs_update(managed_config):
                state = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}} {{.State}}"],
                                       stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
                if state.returncode:
                    raise RuntimeEnvironmentError("cannot inspect Docker before updating Hermes")
                container = values.get("HERMES_CONTAINER", "hermes")
                running = any(line == f"{container} running" for line in state.stdout.splitlines())
                if running:
                    stopped = subprocess.run([*command, "stop", "hermes"], cwd=STACK_DIR,
                                             stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
                    if stopped.returncode:
                        raise RuntimeEnvironmentError("could not stop Hermes before updating its runtime environment")
                if reconcile(runtime_env, managed_keys):
                    print("Hermes runtime overrides removed; Compose will supply central .env values.")
                    gateway_changed = True
                if reconcile_config(managed_config):
                    print("Hermes managed gateway configuration restored to .env references.")
                    gateway_changed = True
        except (BootstrapError, RuntimeEnvironmentError, OSError, ValueError, UnicodeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
    if action == "down":
        command.extend(["--profile", "git-memory"])
    command.append(action)
    if action == "up":
        command.append("-d")
    if action == "up":
        command.append("--build")
        if gateway_changed:
            command.append("--force-recreate")
    try:
        result = run_with_progress("Running Stack 60 Compose",
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
        print(f"Stack 60 Compose {action} failed.", file=sys.stderr)
        return result.returncode
    print()
    if action == "up":
        print("Stack 60 containers started; application readiness has not been verified.")
    else:
        print("Stack 60 containers stopped and removed; persistent data and .lock remain.")
    return 0


@spaced_output
def main(argv: list[str] | None = None) -> int:
    """Dispatch the required stack operation."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-60", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reconfig", help="Apply configuration without changing container state").set_defaults(
        handler=lambda: run_reconfig(STACK_DIR)
    )
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
        return report_status("60", STACK_DIR, LOCK_FILE, deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
