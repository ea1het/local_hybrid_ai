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

DEFAULT_BANNER = """█      ███   ███   ███  █           ███  ███
█     █   █ █     █   █ █          █   █  █
█     █   █ █     █████ █     ████ █████  █
█     █   █ █     █   █ █          █   █  █
█████  ███   ███  █   █ █████      █   █ ███"""


def render_json(payload: Any) -> None:
    """Serialize one JSON-compatible object to stdout."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def render_cli(
    body: str | Callable[[], None] | None = None,
    *,
    header: str | None = None,
    banner: str | None = None,
) -> None:
    """Render human output with an optional customizable text header.

    ``banner`` is opt-in so existing command output remains stable while callers
    migrate. Passing ``banner=DEFAULT_BANNER`` enables the project banner.
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
