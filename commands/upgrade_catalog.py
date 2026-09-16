# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pure transformations for the manifest-derived upgrade component catalog."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

ComponentT = TypeVar("ComponentT")


def records(raw: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for stack in raw["stacks"]:
        for item in stack["components"]:
            record = dict(item)
            record["stack"] = stack["id"]
            result[f"{stack['id']}/{item['id']}"] = record
    return result


def components(raw: dict, factory: Callable[..., ComponentT]) -> list[ComponentT]:
    result: list[ComponentT] = []
    for stack in raw["stacks"]:
        for item in stack["components"]:
            result.append(factory(
                stack=stack["id"],
                name=item["id"],
                service=item.get("service"),
                container=item.get("container"),
                compose=item.get("compose"),
                upstream=item.get("upstream"),
                selectable=item.get("selectable", True),
            ))
    return result
