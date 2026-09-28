#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply the temporary Hermes terminal timeout workaround."""

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
import time
from pathlib import Path

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
TIMEOUT_LINE = re.compile(r"^(?:export\s+)?TERMINAL_TIMEOUT=(.*)$")


def fail(message: str) -> None:
    """Report a timeout workaround error and exit."""
    print(f"[issue-74116] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*args: str, capture: bool = False) -> str:
    """Run a stack-local command and optionally return its trimmed stdout."""
    result = subprocess.run(args, cwd=STACK_DIR, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def timeout_values(path: Path) -> list[str]:
    """Extract exact TERMINAL_TIMEOUT assignments from a runtime env file."""
    return [match.group(1) for line in path.read_text().splitlines()
            if (match := TIMEOUT_LINE.fullmatch(line))]


def main() -> None:
    """Synchronize the runtime timeout with the container, restart, and verify health."""
    if os.geteuid() != 0:
        fail("Run this script as root.")
    if not ENV_FILE.is_file():
        fail(f"Missing {ENV_FILE}")
    env = load_env(ENV_FILE)
    for key in ("BASE_PATH", "HERMES_SERVICE", "HERMES_CONTAINER"):
        if not env.get(key):
            fail(f"{key} missing in .env")
    runtime_env = Path(env["BASE_PATH"].rstrip("/")) / env["HERMES_SERVICE"] / "data/.env"
    container = env["HERMES_CONTAINER"]
    if subprocess.run(["docker", "inspect", container], cwd=STACK_DIR,
                      capture_output=True, check=False).returncode:
        fail(f"Container '{container}' does not exist.")
    if run("docker", "inspect", "--format", "{{.State.Running}}", container, capture=True) != "true":
        fail(f"Container '{container}' is not running.")
    if not runtime_env.is_file():
        fail(f"Hermes runtime .env does not exist: {runtime_env}")
    target = run("docker", "exec", container, "sh", "-c", 'printf "%s" "$TERMINAL_TIMEOUT"', capture=True)
    if not re.fullmatch(r"[1-9][0-9]*", target):
        fail(f"Invalid TERMINAL_TIMEOUT from container: '{target}'")
    values = timeout_values(runtime_env)
    if len(values) != 1:
        fail(f"Expected exactly one TERMINAL_TIMEOUT in {runtime_env}; found {len(values)}")
    print(f"[issue-74116] Hermes runtime TERMINAL_TIMEOUT={values[0]}")
    if values[0] != target:
        metadata = runtime_env.stat()
        lines = runtime_env.read_text().splitlines(keepends=True)
        updated = [f"TERMINAL_TIMEOUT={target}" + ("\n" if line.endswith("\n") else "")
                   if TIMEOUT_LINE.fullmatch(line.rstrip("\n")) else line for line in lines]
        with tempfile.NamedTemporaryFile(mode="w", dir=runtime_env.parent, delete=False) as temporary:
            temporary.write("".join(updated))
            replacement = Path(temporary.name)
        try:
            os.chown(replacement, metadata.st_uid, metadata.st_gid)
            os.chmod(replacement, metadata.st_mode & 0o7777)
            os.replace(replacement, runtime_env)
        finally:
            replacement.unlink(missing_ok=True)
    if timeout_values(runtime_env)[0] != target:
        fail("Runtime .env verification failed before restart.")
    run("docker", "compose", "restart", "hermes")
    for _ in range(60):
        result = subprocess.run(["docker", "inspect", "--format",
                                 "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", container],
                                cwd=STACK_DIR, text=True, capture_output=True, check=False)
        if result.returncode == 0 and result.stdout.strip() == "healthy":
            break
        time.sleep(2)
    health = run("docker", "inspect", "--format",
                 "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", container, capture=True)
    if health != "healthy":
        fail(f"Hermes did not become healthy. Current health: {health}")
    if timeout_values(runtime_env)[0] != target:
        fail("Hermes rewrote TERMINAL_TIMEOUT after restart")
    print("[issue-74116] Temporary workaround applied successfully.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        fail(str(error))
