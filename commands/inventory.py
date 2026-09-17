# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Read-only source inventory validation and explicit rescan snapshot support."""
from __future__ import annotations

from commands import component_inventory

SCHEMA_VERSION = "1"


def _error(command: str, code: str, message: str) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": command, "success": False, "error": {"code": code, "message": message}}


def json_payload(args=None):
    raw = list(args or [])
    if raw not in ([], ["rescan"]):
        return _error("inventory", "INVENTORY_USAGE", "Usage: ./local-ai inventory [rescan]")
    rescan = raw == ["rescan"]
    command = "inventory.rescan" if rescan else "inventory"
    try:
        previous = component_inventory.read_snapshot()
        current = component_inventory.snapshot()
        changes = component_inventory.diff(previous, current)
        if rescan:
            component_inventory.write_snapshot(current)
    except (component_inventory.InventoryError, OSError) as exc:
        return _error(command, "INVENTORY_INVALID", str(exc))
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "success": True,
        "source_fingerprint": current["source_fingerprint"],
        "components": current["components"],
        "changes": changes,
        "previous_snapshot": bool(previous),
        "snapshot_written": rescan,
    }


def cli_text(payload):
    if not payload["success"]:
        return payload["error"]["message"]
    lines = [
        f"SOURCE FINGERPRINT  {payload['source_fingerprint']}",
        f"COMPONENTS          {len(payload['components'])}",
        f"PREVIOUS SNAPSHOT   {'yes' if payload['previous_snapshot'] else 'no'}",
        f"SNAPSHOT WRITTEN    {'yes' if payload.get('snapshot_written') else 'no'}",
        "",
    ]
    for label in ("added", "removed", "changed"):
        values = payload["changes"][label]
        lines.append(f"{label.upper():<8} {', '.join(values) if values else '-'}")
    return "\n".join(lines)
