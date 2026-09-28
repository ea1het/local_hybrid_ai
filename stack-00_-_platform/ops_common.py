# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared command, environment, and prerequisite helpers for Stack0 scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path


def die(message: str) -> None:
    """Report an error and exit unsuccessfully."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def log(message: str) -> None:
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message: str) -> None:
    """Print a section heading."""
    print(f"\n== {message}")


def require_root() -> None:
    """Exit unless the effective user is root."""
    if os.geteuid() != 0:
        die("run as root")


def require_commands(*names: str) -> None:
    """Exit if any named executable is unavailable on PATH."""
    for name in names:
        if shutil.which(name) is None:
            die(f"missing required command: {name}")


def run(*command: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command, optionally capturing text output, or exit on failure."""
    try:
        return subprocess.run(command, check=True, text=True, capture_output=capture)
    except subprocess.CalledProcessError as error:
        die(f"command failed ({error.returncode}): {' '.join(command)}")


def load_env(path: Path) -> dict[str, str]:
    """Source a shell environment file and return its exported variables."""
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1" || exit; set +a; env -0', "_", str(path)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        die(f"could not load {path}: {result.stderr.decode(errors='replace').strip()}")
    values = {}
    for item in result.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            values[key.decode()] = value.decode(errors="replace")
    return values


def require(env: dict[str, str], path: Path, *names: str) -> None:
    """Exit if any required environment variable is empty or absent."""
    for name in names:
        if not env.get(name):
            die(f"missing {name} in {path}")
