#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Validate Open WebUI prerequisites and mark Stack 70 prepared.

The script checks the platform dependency, required configuration, and
service files before writing its preparation lock. It does not mint
credentials; the separate bootstrap script handles missing values.
Importing the module does not inspect Docker or change runtime state."""


import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from datetime import datetime, timezone
from pathlib import Path


STACK_NAME = "stack-70_-_open-webui"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"
REQUIRED_KEYS = (
    "STACKS_ROOT", "BASE_PATH", "NETWORK_NAME", "OPENWEBUI_IMAGE",
    "OPENWEBUI_VERSION", "OPENWEBUI_LITELLM_BASE_URL",
    "OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY",
)


class PrepareError(Exception):
    """Report a failed Stack7 preparation prerequisite."""
    pass


def require(condition, message):
    """Raise ``PrepareError`` when a prerequisite is false."""
    if not condition:
        raise PrepareError(message)


def run(*command, env=None, quiet=False):
    """Run a command and return captured stdout when ``quiet`` is true."""
    try:
        result = subprocess.run(
            command, env=env, text=True, capture_output=quiet, check=False
        )
    except OSError as exc:
        raise PrepareError(f"could not execute {command[0]}: {exc}") from exc
    require(result.returncode == 0, f"command failed: {' '.join(command)}")
    return result.stdout.strip() if quiet else ""


def load_env():
    """Source the central environment with Bash and return exported values."""
    result = subprocess.run(
        ("bash", "-c", 'set -a; source "$1" || exit; env -0', "bash", str(ENV_FILE)),
        stdout=subprocess.PIPE, check=False,
    )
    require(result.returncode == 0, f"could not load {ENV_FILE}")
    return dict(entry.decode().split("=", 1) for entry in result.stdout.split(b"\0") if entry)


def main():
    """Check Stack0, LiteLLM, and runtime paths before writing the lock."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack already prepared. {LOCK_FILE} exists; no changes made.")
        return

    require(os.geteuid() == 0, "run this command as root")
    require(shutil.which("docker") is not None, "docker is not installed")
    require(subprocess.run(("docker", "compose", "version"), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False).returncode == 0,
            "Docker Compose v2 is not available")
    require(ENV_FILE.is_symlink(), f"missing managed symlink {ENV_FILE}")
    require(os.readlink(ENV_FILE) == "../.env", f"{ENV_FILE} must point exactly to ../.env")
    require(ENV_FILE.is_file(), "missing central .env")
    require(COMPOSE_FILE.is_file(), f"missing {COMPOSE_FILE}")

    env = load_env()
    for key in REQUIRED_KEYS:
        require(bool(env.get(key)), f"missing {key} in {ENV_FILE}")
    for key in ("OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY"):
        require(not env[key].startswith("PUT_YOUR_"), f"{key} still contains a placeholder")
    version = env["OPENWEBUI_VERSION"]
    require(version not in ("latest", "main", "dev"),
            f"OPENWEBUI_VERSION must be a pinned stable version, not {version}")
    stacks_root = env["STACKS_ROOT"]
    base_path = env["BASE_PATH"]
    require(stacks_root.startswith("/") and base_path.startswith("/"),
            "STACKS_ROOT and BASE_PATH must be absolute paths")
    require(str(STACK_DIR) == f"{stacks_root.rstrip('/')}/{STACK_NAME}",
            f"this stack must reside in {stacks_root.rstrip('/')}/{STACK_NAME}; current path: {STACK_DIR}")
    require(stacks_root.rstrip("/") != base_path.rstrip("/"),
            "STACKS_ROOT and BASE_PATH must differ")

    for stack, label in (("stack-00_-_platform", "Stack 00"), ("stack-30_-_litellm", "Stack 30")):
        lock = Path(stacks_root.rstrip("/")) / stack / ".lock"
        require(lock.is_file(), f"{label} is not prepared: missing {lock}")

    network = env["NETWORK_NAME"]
    print(f"\n== Shared Docker network {network}")
    require(subprocess.run(("docker", "network", "inspect", network),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False).returncode == 0,
            f"missing {network}; install or prepare Stack 00 first")
    driver = run("docker", "network", "inspect", "-f", "{{.Driver}}", network, quiet=True)
    require(driver == "bridge", f"{network} uses driver {driver}, not bridge")
    print("  Stack 00 network verified")

    print("\n== Gateway LiteLLM")
    require(subprocess.run(("docker", "inspect", "litellm"), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False).returncode == 0,
            "missing litellm container; deploy Stack 30 first")
    running = run("docker", "inspect", "-f", "{{.State.Running}}", "litellm", quiet=True)
    require(running == "true", "litellm is not running")
    print("  LiteLLM is available")

    print("\n== Persistent Open WebUI runtime")
    data_dir = Path(base_path.rstrip("/")) / "service_-_open-webui" / "data"
    for directory in (data_dir.parent, data_dir):
        require(directory.is_dir() and not directory.is_symlink(),
                f"missing {directory}; run Stack 00 bootstrap first")
    print(f"  persistent data: {data_dir}")

    print("\n== Docker Compose validation")
    run("docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
        "config", "--quiet", env=env)
    print("  Docker Compose configuration valid")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={timestamp}\n")
    LOCK_FILE.chmod(0o644)
    print(f"\n== Preparation complete\n  lock created: {LOCK_FILE}")
    print("  Open WebUI uses only the OpenAI-compatible gateway provided by Stack 30")


if __name__ == "__main__":
    try:
        main()
    except PrepareError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
