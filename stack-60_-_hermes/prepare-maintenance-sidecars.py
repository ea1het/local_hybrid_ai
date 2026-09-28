#!/usr/bin/env python3
"""Prepare the optional Hermes maintenance sidecars."""

import os
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"


def fail(message: str) -> None:
    print(f"[maintenance-prepare] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if os.geteuid() != 0:
        fail("run as root")
    if not ENV_FILE.is_file():
        fail(f"missing {ENV_FILE}")
    if not LOCK_FILE.is_file():
        fail("Stack6 is not prepared; run 01-prepare.py first")
    env = load_env(ENV_FILE)
    for key in ("BASE_PATH", "HERMES_UID", "HERMES_GID", "MEMORY_SYNC_SERVICE", "SANDBOX_SERVICE"):
        if not env.get(key):
            fail(f"missing {key} in .env")
    owner = env["HERMES_UID"]
    group = env["HERMES_GID"]
    memory_root = Path(env["BASE_PATH"]) / env["MEMORY_SYNC_SERVICE"]
    memory_ssh = memory_root / "ssh"
    sandbox_state = Path(env["BASE_PATH"]) / env["SANDBOX_SERVICE"] / "data/state"
    for mode, uid, gid, path in (
        ("0750", owner, group, memory_root),
        ("0700", owner, group, memory_ssh),
        ("0700", "0", "0", sandbox_state),
    ):
        subprocess.run(["install", "-d", "-m", mode, "-o", uid, "-g", gid, str(path)], check=True)
    for name in ("ssh_config", "id_ed25519", "known_hosts"):
        path = memory_ssh / name
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"missing dedicated memory-sync SSH material: {path}")
    print(f"[maintenance-prepare] memory-sync runtime: {memory_root}")
    print(f"[maintenance-prepare] sandbox lifecycle state: {sandbox_state}")
    print("[maintenance-prepare] sidecar images build directly from Stack6 source")
    print("""
Maintenance sidecars prepared.

Git memory remains opt-in. To enable only the memory-sync sidecar after prepare-git-memory.py:
  docker compose --profile git-memory up -d --build hermes-memory-sync
  docker compose --profile git-memory ps

The default Stack6 deployment remains:
  docker compose up -d --build
  docker compose ps""")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        fail(str(error))
