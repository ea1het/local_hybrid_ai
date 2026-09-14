# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only operational status for the Local Hybrid AI installation.

Human status answers one question: is each stack operational? Detailed component
version state remains available in the JSON diagnostic contract, while normal
version maintenance belongs to ``./local-ai upgrade``. Component identity/drift
semantics are shared through ``commands.component_state`` rather than reimplemented
here.
"""

from __future__ import annotations

import json
from pathlib import Path

from commands import component_state, install, upgrade

SCHEMA_VERSION = "3"


class StatusError(RuntimeError):
    pass


# Compatibility aliases for internal callers/tests while ownership moves to the
# shared state module. They are private implementation details, not public API.
_deployed_versions = component_state.deployed_versions
_deployed = component_state.deployed
_drift = component_state.drift
_is_floating_image_reference = component_state.is_floating_image_reference
_resolve_state = component_state.resolve_identity


def inventory(*, runtime_root: Path | None = None, deployed_versions: dict[str, str] | None = None) -> list[dict]:
    """Return detailed component state for JSON diagnostics and drift aggregation."""
    env = upgrade.read_env()
    records = upgrade.component_records()
    if deployed_versions is None:
        deployed_versions = component_state.deployed_versions(runtime_root or upgrade.runtime_root())

    rows: list[dict] = []
    for component in upgrade.load_catalog():
        component_key = upgrade.key(component)
        actual_image = upgrade.running_image(component)
        record = records[component_key]

        if record.get("availability") == "local":
            actual = "local" if actual_image else "n/a"
            desired = "local"
            deployed = "local" if actual_image else "unknown"
            drift = "n/a"
        else:
            desired_image = upgrade.compose_image(component, env)
            desired, actual, drift = component_state.resolve_identity(component, desired_image, actual_image)
            deployed = component_state.deployed(component_key, desired, actual, deployed_versions)

        rows.append({
            "stack": component.stack,
            "component": component.name,
            "desired": desired,
            "deployed": deployed,
            "actual": actual,
            "drift": drift,
        })
    return rows


def _stack_name(directory: str) -> str:
    marker = "_-_"
    name = directory.split(marker, 1)[1] if marker in directory else directory
    return name.replace("_", "-")


def _runtime_summary(entry: dict, state: dict) -> tuple[str, str]:
    if not state["prepared"]:
        return "unprepared", "-"

    required = entry["required_containers"]
    if not required:
        return "prepared", "ready"

    states = [state["containers"].get(name, "absent") for name in required]
    running = [install.is_running(value) for value in states]
    healthy = [install.is_runtime_healthy(value) for value in states]

    if all(running):
        return "running", "ready" if all(healthy) else "degraded"
    if not any(running):
        return "stopped", "-"
    return "partial", "degraded"


def stack_inventory(component_rows: list[dict] | None = None) -> list[dict]:
    """Return one operational row per stack using manifest/lifecycle ownership."""
    manifests = install.all_manifests()
    lifecycle = install.load_lifecycle()
    install.validate_registry(manifests, lifecycle)
    component_rows = inventory() if component_rows is None else component_rows

    rows: list[dict] = []
    for sid in sorted(manifests):
        manifest = manifests[sid]
        entry = lifecycle["stacks"][str(sid)]
        runtime = install.stack_state(manifest)
        state, health = _runtime_summary(entry, runtime)
        stack_key = f"stack{sid}"
        owned_components = [row for row in component_rows if row["stack"] == stack_key]
        rows.append({
            "stack": stack_key,
            "name": _stack_name(manifest["directory"]),
            "state": state,
            "health": health,
            "drift": component_state.aggregate_drift(owned_components),
        })
    return rows


def _print_table(rows: list[dict]) -> None:
    headers = ("STACK", "NAME", "STATE", "HEALTH", "DRIFT")
    values = [headers]
    for row in rows:
        values.append((
            upgrade.human_stack_id(row["stack"]),
            row["name"],
            row["state"],
            row["health"],
            row["drift"],
        ))
    widths = [max(len(str(row[i])) for row in values) for i in range(len(headers))]
    for index, row in enumerate(values):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def main(*, json_output: bool = False) -> int:
    try:
        components = inventory()
        stacks = stack_inventory(components)
    except (component_state.ComponentStateError, install.InstallerError, StatusError, OSError, json.JSONDecodeError) as exc:
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": "status",
                "success": False,
                "error": {"code": "STATUS_STATE_INVALID", "message": str(exc)},
            }, indent=2, sort_keys=True))
        else:
            print(f"STATUS ERROR [STATUS_STATE_INVALID]: {exc}")
        return 1

    if json_output:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "command": "status",
            "success": True,
            "stacks": stacks,
            "components": components,
        }, indent=2, sort_keys=True))
    else:
        _print_table(stacks)
    return 0
