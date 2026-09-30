#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bootstrap missing Open WebUI environment values explicitly.

This utility fills missing non-LiteLLM Stack 70 values in the protected root
.env, keeping existing custom values. Before a change it saves the exact
original bytes to a root-owned, mode-0600, timestamped backup. Consumer API
keys are configured separately by the operator; this module never creates
LiteLLM keys. Importing the module does not write .env."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the worktree

import os
import re
import secrets
import stat
import tempfile
from datetime import datetime
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ROOT = STACK_DIR.parent
ENV_FILE = ROOT / ".env"

DEFAULTS = {
    "OPENWEBUI_IMAGE": "ghcr.io/open-webui/open-webui",
    "OPENWEBUI_VERSION": "v0.11.3",
    "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
}
ALL_KEYS = (*DEFAULTS.keys(), "OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY")
PLACEHOLDER_RE = re.compile(r"^PUT_YOUR_[A-Z0-9_]+_HERE$")
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class BootstrapError(RuntimeError):
    """Report an invalid environment or backup prerequisite."""
    pass


def require_env_file() -> str:
    """Read the root-owned operational environment after checking its mode."""
    if os.geteuid() != 0:
        raise BootstrapError("run as root so the protected operational .env remains root-owned")
    if not ENV_FILE.is_file() or ENV_FILE.is_symlink():
        raise BootstrapError(f"operational environment must be a regular file: {ENV_FILE}")
    st = ENV_FILE.stat()
    if stat.S_IMODE(st.st_mode) != 0o600:
        raise BootstrapError(f"operational environment must have mode 0600: {ENV_FILE}")
    if st.st_uid != 0 or st.st_gid != 0:
        raise BootstrapError(f"operational environment must be owned by root:root: {ENV_FILE}")
    return ENV_FILE.read_bytes().decode("utf-8")


def parse_values(text: str) -> tuple[dict[str, str], dict[str, int]]:
    """Extract Stack7 assignments and reject duplicate managed keys."""
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    for raw in text.splitlines():
        match = ASSIGNMENT_RE.match(raw)
        if not match:
            continue
        key, value = match.groups()
        if key in ALL_KEYS:
            counts[key] = counts.get(key, 0) + 1
            values[key] = value
    duplicates = [key for key, count in counts.items() if count != 1]
    if duplicates:
        raise BootstrapError("duplicate Stack 70 variables in .env: " + ", ".join(sorted(duplicates)))
    return values, counts


def missing_or_placeholder(value: str | None) -> bool:
    """Return whether a value is absent, empty, or a standard placeholder."""
    return value is None or value == "" or bool(PLACEHOLDER_RE.fullmatch(value))


def render_updated(text: str, replacements: dict[str, str]) -> str:
    """Replace managed assignments and append missing ones in key order."""
    seen: set[str] = set()
    output: list[str] = []
    for raw in text.splitlines():
        match = ASSIGNMENT_RE.match(raw)
        if match and match.group(1) in replacements:
            key = match.group(1)
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(raw)
    missing = [key for key in ALL_KEYS if key in replacements and key not in seen]
    if missing:
        if output and output[-1] != "":
            output.append("")
        output.append("# Stack7 / Open WebUI — bootstrapped explicitly; secrets never print to stdout")
        for key in missing:
            output.append(f"{key}={replacements[key]}")
    return "\n".join(output) + "\n"


def backup_env(expected_text: str) -> Path:
    """Save the unchanged operational .env exclusively before modifying it."""
    timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
    backup = ROOT / f".env-backup-{timestamp}"
    source_fd = os.open(ENV_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        source_stat = os.fstat(source_fd)
        if (not stat.S_ISREG(source_stat.st_mode)
                or stat.S_IMODE(source_stat.st_mode) != 0o600
                or source_stat.st_uid != 0 or source_stat.st_gid != 0):
            raise BootstrapError("operational .env changed type, mode, or owner before backup")
        with os.fdopen(source_fd, "rb", closefd=False) as source:
            original = source.read()
    finally:
        os.close(source_fd)
    if original != expected_text.encode("utf-8"):
        raise BootstrapError("operational .env changed during bootstrap; refusing to overwrite it")

    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, 0, 0)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return backup


def atomic_write(payload: str, expected_text: str) -> None:
    """Replace .env atomically only if it still matches the backed-up version."""
    fd, tmp_name = tempfile.mkstemp(prefix=".env.stack7.", dir=ROOT)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(tmp, 0, 0)
        if require_env_file() != expected_text:
            raise BootstrapError("operational .env changed during bootstrap; refusing to overwrite it")
        os.replace(tmp, ENV_FILE)
        # Sync the directory so the replacement survives a sudden power loss.
        directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    """Fill missing Stack7 values and return an operator-facing exit code."""
    try:
        text = require_env_file()
        values, _ = parse_values(text)
        replacements: dict[str, str] = {}

        for key, default in DEFAULTS.items():
            if missing_or_placeholder(values.get(key)):
                replacements[key] = default

        if missing_or_placeholder(values.get("OPENWEBUI_SECRET_KEY")):
            replacements["OPENWEBUI_SECRET_KEY"] = secrets.token_hex(32)

        if not replacements:
            print("Stack 70 environment already bootstrapped; no changes made.")
            return 0

        backup = backup_env(text)
        updated = render_updated(text, replacements)
        atomic_write(updated, text)
        print("Stack 70 environment bootstrap: PASS")
        print(f"- protected backup: {backup}")
        print(f"- updated variables: {len(replacements)}")
        print("- secret values were not printed")
        return 0
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"Stack 70 bootstrap error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
