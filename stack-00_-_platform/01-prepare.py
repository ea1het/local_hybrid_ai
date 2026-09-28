#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Stack0 environment links and its shared Docker bridge network."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ops_common import die, load_env, log, require, require_commands, require_root, run, step


def main() -> None:
    """Validate platform prerequisites and prepare links and network if unlocked."""
    stack_dir = Path(__file__).resolve().parent
    root_dir = stack_dir.parent
    env_file = root_dir / ".env"
    lock_file = stack_dir / ".lock"
    if lock_file.exists() or lock_file.is_symlink():
        print(f"Stack0 already PREPARED ({lock_file}); nothing changed.")
        return

    require_root()
    require_commands("docker", "ln", "readlink", "chmod", "chown")
    run("docker", "compose", "version", capture=True)
    if not env_file.is_file() or env_file.is_symlink():
        die(f"missing root operational environment: {env_file}")

    os.chown(env_file, 0, 0)
    os.chmod(env_file, 0o600)
    env = load_env(env_file)
    require(env, env_file, "STACKS_ROOT", "BASE_PATH", "NETWORK_NAME", "ROOT_HOSTNAME")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    network_name = env["NETWORK_NAME"]
    if not stacks_root.startswith("/") or not base_path.startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute")
    if str(root_dir) != stacks_root:
        die(f"worktree must be {stacks_root}; current path: {root_dir}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", network_name):
        die("NETWORK_NAME contains unsupported characters")

    platform_root = Path(base_path) / "service_-_platform"
    if not platform_root.is_dir() or platform_root.is_symlink():
        die(f"missing {platform_root}; run {stack_dir}/00-bootstrap.py first")

    step("Central environment compatibility links")
    directories = sorted(
        directory for directory in root_dir.glob("stack-[0-9][0-9]_-_*")
        if directory.is_dir() and not directory.is_symlink() and directory != stack_dir
    )
    for directory in directories:
        env_link = directory / ".env"
        if env_link.is_symlink():
            if os.readlink(env_link) != "../.env":
                die(f"unexpected symlink target for {env_link}: {os.readlink(env_link)}")
            log(f"{directory.name}/.env -> ../.env")
        elif env_link.exists():
            die(f"{env_link} exists and is not the managed symlink; refusing to replace it")
        else:
            env_link.symlink_to("../.env")
            log(f"created {directory.name}/.env -> ../.env")

    step(f"Shared Docker network {network_name}")
    inspection = subprocess.run(["docker", "network", "inspect", network_name], capture_output=True)
    if inspection.returncode == 0:
        driver = run("docker", "network", "inspect", "-f", "{{.Driver}}", network_name, capture=True).stdout.strip()
        if driver != "bridge":
            die(f"{network_name} exists but uses driver {driver}, expected bridge")
        log("exists and is bridge")
    else:
        run("docker", "network", "create", "--driver", "bridge", network_name, capture=True)
        log("created")
    step("Platform preparation complete")
    log(".lock is written by install.py after certificate installation and verification")


if __name__ == "__main__":
    main()
