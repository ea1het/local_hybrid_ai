#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Self-contained shell completion command package."""

from . import api
from .api import (
    TOP_LEVEL,
    GLOBAL_OPTIONS,
    RESTORE_ACTIONS,
    BACKUP_SET_RE,
    SCHEMA_VERSION,
    complete,
    shell_script,
    detect_shell,
    completion_target,
    install_completion,
    completion_status,
    json_payload,
    cli_text,
    main,
)

__all__ = [
    "api",
    "TOP_LEVEL",
    "GLOBAL_OPTIONS",
    "RESTORE_ACTIONS",
    "BACKUP_SET_RE",
    "SCHEMA_VERSION",
    "complete",
    "shell_script",
    "detect_shell",
    "completion_target",
    "install_completion",
    "completion_status",
    "json_payload",
    "cli_text",
    "main",
]
