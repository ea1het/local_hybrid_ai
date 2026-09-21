#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Self-contained Install command domain."""

from . import api
from .api import SCHEMA_VERSION, InstallArgumentParser, parser, build_payload, json_payload, cli_text, main

__all__ = [
    "api",
    "SCHEMA_VERSION",
    "InstallArgumentParser",
    "parser",
    "build_payload",
    "json_payload",
    "cli_text",
    "main",
]
