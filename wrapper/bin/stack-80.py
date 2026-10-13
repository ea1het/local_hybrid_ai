#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare, adopt, reconfigure, or control the self-hosted MCP stack."""

import sys
sys.dont_write_bytecode = True
import argparse
import importlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wrapper.lib.cli_output import spaced_output
from wrapper.lib.progress import run_with_progress
from wrapper.lib.reconfig_dispatch import add_reconfig_command
from wrapper.lib.stack_status import container_rows, report_status
from wrapper.stubs.bootstrap_env import assignments, missing, protected_text

STACK_DIR = ROOT / "stack-80_-_mcp"
LOCK_FILE = STACK_DIR / ".lock"


def helper():
    """Use the stack's configuration contract, rather than duplicate it."""
    return importlib.import_module("stack-80_-_mcp.stack_env")


def regular_lock(path):
    """Reject unsafe lock paths and return whether preparation is recorded."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"Invalid preparation lock: {path}")
    return path.is_file()


def central_preflight():
    """Reject missing central inputs before creating files or starting services."""
    values = assignments(protected_text(ROOT / ".env"))
    for key in ("BASE_PATH", "NETWORK_NAME", "GOOGLE_WORKSPACE_MCP_VERSION",
                "MCP_GOOGLE_OAUTH_CLIENT_ID", "MCP_GOOGLE_OAUTH_CLIENT_SECRET",
                "MCP_GOOGLE_EMAIL", "MCP_UID", "MCP_GID"):
        if missing(values.get(key)):
            raise RuntimeError(f"Configure {key} once in the central .env before using Stack 80.")
    if not values["BASE_PATH"].startswith("/") or values["BASE_PATH"].rstrip("/") == "":
        raise RuntimeError("BASE_PATH must be an absolute directory other than /.")
    if not values["MCP_GOOGLE_OAUTH_CLIENT_ID"].endswith(".apps.googleusercontent.com"):
        raise RuntimeError("MCP_GOOGLE_OAUTH_CLIENT_ID must be a Google OAuth Client ID.")
    email = values["MCP_GOOGLE_EMAIL"]
    if "@" not in email or email != email.strip():
        raise RuntimeError("MCP_GOOGLE_EMAIL must be the dedicated Google account email.")
    if values["GOOGLE_WORKSPACE_MCP_VERSION"] == "latest":
        raise RuntimeError("Select a numbered GOOGLE_WORKSPACE_MCP_VERSION; latest is not supported.")
    if not all(values[key].isdigit() for key in ("MCP_UID", "MCP_GID")):
        raise RuntimeError("MCP_UID and MCP_GID must be nonnegative integers.")


def run_phase(label, command, cwd=STACK_DIR):
    """Run a scoped operation without exposing captured secrets on failures."""
    result = run_with_progress(label, command, cwd=cwd, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, check=False)
    if result.returncode:
        print(f"ERROR: {label} failed (exit {result.returncode}); check prerequisites and configuration.",
              file=sys.stderr)
    elif result.stdout:
        print(result.stdout.strip())
    return result.returncode


def install():
    """Adopt compatible stores or prepare fresh ones; never start services."""
    try:
        if regular_lock(LOCK_FILE):
            print("Stack 80 already prepared; no changes made. Use reconfig to preview changes.")
            return 0
        if os.geteuid() != 0:
            raise RuntimeError("Stack 80 installation requires root privileges.")
        if not regular_lock(ROOT / "stack-00_-_platform" / ".lock"):
            raise RuntimeError("Stack 00 must be prepared before Stack 80.")
        central_preflight()
        state = container_rows(STACK_DIR)
        running = any(row["State"] in {"running", "restarting", "paused"} for row in state.values())
        api = helper()
        prepared = False
        try:
            config = api.configuration()
            api.validate_configuration(config)
            api.validate_network(config)
            api.runtime_directories(config)
            prepared = not api.settings_changes(api.SERVICES)
        except (OSError, ValueError, RuntimeError) as error:
            if running:
                raise RuntimeError(f"Cannot adopt running Stack 80: {error} "
                                   "Review the reported condition; stop Stack 80 before settings maintenance. "
                                   "Existing credentials and data were not changed.") from error
        if prepared:
            code = run_phase("Adopting Stack 80", [sys.executable, "-B",
                             str(STACK_DIR / "01-prepare.py"), "--adopt"])
        else:
            if running:
                raise RuntimeError("Running Stack 80 settings need maintenance; run stack-80 stop, then install.")
            phases = (
                ("directories", [sys.executable, "-B", str(ROOT / "stack-00_-_platform/00-bootstrap.py"), "--stack", "80"]),
                ("bootstrap", [sys.executable, "-B", str(STACK_DIR / "00-bootstrap.py")]),
                ("prepare", [sys.executable, "-B", str(STACK_DIR / "01-prepare.py")]),
            )
            for name, command in phases:
                code = run_phase(f"Preparing Stack 80 {name}", command)
                if code:
                    return code
        if code:
            return code
        if not regular_lock(LOCK_FILE):
            raise RuntimeError("Preparation did not create a regular .lock file.")
        print("Stack 80 PREPARED; container state and Google authorization were not changed.")
        print("Start when ready: ./local-ai stack-80 start")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def run_compose(action):
    """Start or remove only Stack 80 containers; preserve persistent stores."""
    try:
        if os.geteuid() != 0:
            raise RuntimeError("Stack lifecycle operations require root privileges.")
        api = helper()
        api.central_environment()
        api.safe_path(STACK_DIR / "docker-compose.yml")
        if action == "up":
            if not regular_lock(LOCK_FILE):
                raise RuntimeError("Stack is not prepared; missing regular lock. Run stack-80 install.")
            central_preflight()
            config = api.configuration()
            api.validate_configuration(config)
            api.validate_network(config)
            api.runtime_directories(config)
            if api.settings_changes(api.SERVICES):
                raise RuntimeError("Managed settings need reconfiguration; run stack-80 reconfig, then --apply.")
        command = api.compose_command(action)
        if action == "up":
            command.extend(["-d", "--build"])
        code = run_phase("Running Stack 80 Compose", command)
        if code == 0:
            print("Containers started; readiness and Google access have not been verified." if action == "up"
                  else "Containers stopped and removed; persistent data and .lock remain.")
        return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


@spaced_output
def main(argv=None):
    """Expose the same lifecycle verbs as other application stacks."""
    parser = argparse.ArgumentParser(prog="./local-ai stack-80", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_reconfig_command(commands, STACK_DIR)
    commands.add_parser("install", help="Prepare or adopt without starting services").set_defaults(handler=install)
    commands.add_parser("start", help="Run Docker Compose up in detached mode").set_defaults(handler=lambda: run_compose("up"))
    commands.add_parser("stop", help="Run Docker Compose down; preserve data").set_defaults(handler=lambda: run_compose("down"))
    status = commands.add_parser("status", help="Report preparation and Docker health")
    status.add_argument("--deep", action="store_true", help="Check MCP initialization and tool discovery without Google API calls")
    status.set_defaults(handler=lambda deep=False: report_status("80", STACK_DIR, LOCK_FILE, deep=deep))
    options = parser.parse_args(argv)
    if options.command == "reconfig":
        return options.handler(apply=options.apply)
    if options.command == "status":
        return options.handler(deep=options.deep)
    return options.handler()


if __name__ == "__main__":
    raise SystemExit(main())
