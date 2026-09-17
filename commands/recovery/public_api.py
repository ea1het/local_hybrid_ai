# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Structured recovery operations consumed by the public management CLI.

Recovery implementation modules historically support direct script execution and
therefore use sibling imports. This adapter keeps that compatibility detail
inside the recovery package while exposing JSON-serializable results to the sole
public ``local-ai`` dispatcher. It does not print or choose an output format.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

RECOVERY_ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1"


def _load(name: str) -> ModuleType:
    """Load a recovery engine without leaking its sibling-import layout upward."""
    root = str(RECOVERY_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(name)
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


def plan_payload(backup_set: str | Path) -> dict[str, object]:
    engine = _load("dr_restore_all")
    plan = engine.plan_restore_all(Path(backup_set))
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "restore.plan",
        "success": True,
        "result": plan.as_dict(),
    }


def drill_payload(backup_set: str | Path, destination: str | Path) -> dict[str, object]:
    engine = _load("dr_restore_drill")
    result = engine.run_restore_drill(Path(backup_set), Path(destination))
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "restore.drill",
        "success": True,
        "result": result.as_dict(),
    }


def cli_text(payload: dict[str, object]) -> str:
    """Return human-readable text without writing to stdout or stderr."""
    command = payload.get("command")
    result = payload.get("result")
    if not isinstance(result, dict):
        return str(result)

    if command == "restore.plan":
        lines = ["RESTORE PLAN: PASS"]
        order = result.get("restore_order")
        if isinstance(order, list) and order:
            lines.append("- restore order: " + ", ".join(str(item) for item in order))
        changes = result.get("changes_made")
        if changes is not None:
            lines.append(f"- changes made: {'yes' if changes else 'no'}")
        return "\n".join(lines)

    if command == "restore.drill":
        lines = ["RESTORE DRILL: PASS"]
        destination = result.get("destination")
        if destination:
            lines.append(f"- destination: {destination}")
        lines.append(
            "- live runtime modified: "
            + ("yes" if result.get("live_runtime_modified") else "no")
        )
        lines.append(
            "- ports published: " + ("yes" if result.get("ports_published") else "no")
        )
        lines.append(
            "- platform network attached: "
            + ("yes" if result.get("platform_network_attached") else "no")
        )
        return "\n".join(lines)

    return str(result)
