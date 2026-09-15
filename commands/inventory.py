# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only source inventory validation and explicit rescan snapshot support."""

from __future__ import annotations

import json
import sys

from commands import component_inventory

SCHEMA_VERSION = "1"


def _human(current: dict, changes: dict, previous: dict | None) -> None:
    print(f"SOURCE FINGERPRINT  {current['source_fingerprint']}")
    print(f"COMPONENTS          {len(current['components'])}")
    print(f"PREVIOUS SNAPSHOT   {'yes' if previous else 'no'}")
    print()
    for label in ("added", "removed", "changed"):
        values = changes[label]
        print(f"{label.upper():8} {len(values)}")
        for value in values:
            print(f"  {value}")
    print()
    print("RESCAN: PASS")


def main(args: list[str] | None = None, *, json_output: bool = False) -> int:
    raw = list(args or [])
    if raw not in ([], ["rescan"]):
        message = "Usage: ./local-ai inventory rescan"
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": "inventory.rescan",
                "success": False,
                "error": {"code": "INVENTORY_USAGE", "message": message},
            }, indent=2, sort_keys=True))
        else:
            print(message, file=sys.stderr)
        return 2

    try:
        previous = component_inventory.read_snapshot()
        current = component_inventory.snapshot()
        changes = component_inventory.diff(previous, current)
        component_inventory.write_snapshot(current)
    except (component_inventory.InventoryError, OSError) as exc:
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": "inventory.rescan",
                "success": False,
                "error": {"code": "INVENTORY_INVALID", "message": str(exc)},
            }, indent=2, sort_keys=True))
        else:
            print(f"INVENTORY ERROR [INVENTORY_INVALID]: {exc}", file=sys.stderr)
        return 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "command": "inventory.rescan",
        "success": True,
        "source_fingerprint": current["source_fingerprint"],
        "components": current["components"],
        "changes": changes,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _human(current, changes, previous)
    return 0
