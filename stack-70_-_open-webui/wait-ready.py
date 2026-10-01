#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Wait until the Open WebUI container reports a healthy state.

This command probes the expected container and returns success only when
the runtime is ready, subject to its timeout. It is a post-deployment
gate rather than a repair step. Importing the module does not query Docker."""


import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import time


CONTAINER = "open-webui"


class WaitError(Exception):
    """Report a missing, failed, or overdue Open WebUI container."""
    pass


def inspect(template):
    """Return a Docker inspect template's stripped output for Open WebUI."""
    result = subprocess.run(("docker", "inspect", "-f", template, CONTAINER),
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise WaitError(f"docker inspect failed for {CONTAINER}")
    return result.stdout.strip()


def main():
    """Poll Docker health until ready, terminal failure, or timeout."""
    if os.geteuid() != 0:
        raise WaitError("run this command as root")
    timeout_text = os.environ.get("OPENWEBUI_READY_TIMEOUT", "240")
    if not re.fullmatch(r"[0-9]+", timeout_text):
        raise WaitError("invalid OPENWEBUI_READY_TIMEOUT")
    timeout = int(timeout_text)
    start = int(time.time())

    while True:
        try:
            present = subprocess.run(("docker", "inspect", CONTAINER),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     check=False).returncode == 0
        except OSError as exc:
            raise WaitError(f"docker inspect failed: {exc}") from exc
        if not present:
            raise WaitError(f"missing container {CONTAINER}")

        running = inspect("{{.State.Running}}")
        status = inspect("{{.State.Status}}")
        health = inspect("{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
        if running == "true" and health == "healthy":
            print(f"[stack7-ready] Open WebUI: READY ({status}/{health})")
            return
        if status in ("exited", "dead", "removing"):
            raise WaitError(f"{CONTAINER} entered terminal state {status}")
        if int(time.time()) - start >= timeout:
            raise WaitError(f"timed out waiting for Open WebUI ({status}/{health})")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except WaitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
