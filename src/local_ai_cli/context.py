# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Global execution context owned by the sole public ``local-ai`` boundary."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CommandContext:
    """Global modifiers resolved once by the public CLI."""
    json_output: bool = False
    assume_yes: bool = False
