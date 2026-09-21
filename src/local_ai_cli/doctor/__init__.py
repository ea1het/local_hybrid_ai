#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Read-only platform diagnostics command package."""

from . import api
from .api import SCHEMA_VERSION, ROOT, _check, run_checks, json_payload, payload, cli_text, main

__all__ = ["api", "SCHEMA_VERSION", "ROOT", "_check", "run_checks", "json_payload", "payload", "cli_text", "main"]
