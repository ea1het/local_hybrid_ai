#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Wait for required Hermes service containers to become ready.

This deployment-time probe reads the stack environment and checks the
expected containers until they report a usable state or time out.
It neither prepares the stack nor starts containers. Importing the
module does not perform readiness checks."""

import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import time
from pathlib import Path

if __package__:
    from .stack_env import load_env
else:
    from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"


def fail(message: str) -> None:
    """Report a readiness error and exit unsuccessfully."""
    print(f"[stack6-ready] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def container_state(name: str) -> str:
    """Return Docker's status and health fields, or an absent sentinel."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", name],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "absent|"


def main() -> None:
    """Wait until every required container is running and healthy, or fail on exit or timeout."""
    if not ENV_FILE.is_file():
        fail(f"missing {ENV_FILE}")
    if shutil.which("docker") is None:
        fail("docker is required")
    env = load_env(ENV_FILE)
    containers = []
    for key in ("HERMES_CONTAINER", "SANDBOX_CONTAINER", "SANDBOX_CLEANUP_CONTAINER"):
        if not env.get(key):
            fail(f"missing {key} in .env")
        containers.append(env[key])
    timeout = int(os.environ.get("HERMES_READY_TIMEOUT_SECONDS", "240"))
    start = time.time()
    while True:
        ready = True
        summary = []
        for container in containers:
            state = container_state(container)
            summary.append(f"{container}={state.replace('|', '/')}")
            status, _, health = state.partition("|")
            if status in {"exited", "dead", "removing", "absent"}:
                fail(f"required runtime failed before READY: {' '.join(summary)}")
            if status != "running" or health not in {"", "healthy"}:
                ready = False
        if ready:
            print(f"[stack6-ready] READY ({' '.join(summary)})")
            return
        if time.time() - start >= timeout:
            fail(f"required runtime did not become READY within {timeout}s: {' '.join(summary)}")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        fail(str(error))
