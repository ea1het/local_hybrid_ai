#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Presentation boundary for the public ``local-ai`` interface.

Domain modules return structured Python objects. Only this module serializes
machine output or decorates human output.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from local_ai_cli import __version__

_ASCII_ART = """

█      ███   ███   ███  █            ███  ███
█     █   █ █     █   █ █           █   █  █
█     █   █ █     █████ █     ████  █████  █
█     █   █ █     █   █ █           █   █  █
█████  ███   ███  █   █ █████       █   █ ███

"""

DEFAULT_BANNER = f"{_ASCII_ART}\nVersion: {__version__}"


def render_json(payload: Any) -> None:
    """Serialize one JSON-compatible object to stdout."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def render_cli(
    body: str | Callable[[], None] | None = None,
    *,
    header: str | None = None,
    banner: str | None = DEFAULT_BANNER,
) -> None:
    """Render human output, prefixed by the project banner unless suppressed.

    Every human-text ``local-ai`` invocation renders through this function, so
    the banner shows once per successful invocation by default. Pass
    ``banner=None`` to omit it for a specific call (for example, tests
    asserting an exact body). ``--json`` output never goes through this
    function and is therefore never prefixed.
    """
    if banner:
        print(banner)
    if header:
        if banner:
            print()
        print(header)
    if body is None:
        return
    if header or banner:
        print()
    if callable(body):
        body()
    else:
        print(body)
