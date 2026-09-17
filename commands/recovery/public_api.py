# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Compatibility facade for package-owned Backup and Restore public APIs."""
from __future__ import annotations

from commands.backup.api import backup_payload, cli_text as backup_cli_text
from commands.restore.api import (
    SCHEMA_VERSION,
    apply_payload,
    check_clean_target_payload,
    cli_text as restore_cli_text,
    drill_payload,
    plan_payload,
    resume_payload,
)


def cli_text(payload: dict[str, object]) -> str:
    if payload.get("command") == "backup":
        return backup_cli_text(payload)
    return restore_cli_text(payload)


__all__ = [
    "SCHEMA_VERSION",
    "apply_payload",
    "backup_payload",
    "check_clean_target_payload",
    "cli_text",
    "drill_payload",
    "plan_payload",
    "resume_payload",
]
