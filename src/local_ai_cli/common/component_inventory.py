#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Canonical component-topology compilation from stack manifests, shared by doctor, upgrade and inventory.

Stack ``manifest.json`` files are the semantic source of truth. Compose binds a
component to an implementation, while this module validates that every owned
container has exactly one declared component and that every declared service
exists in the stack Compose file.
"""

from __future__ import annotations
import re
from pathlib import Path
from .manifests import ROOT, ManifestError, all_manifests

MANAGEMENT_TYPES = {"versioned", "local", "helper", "platform"}
EXECUTION_MODES = {"guarded", "inventory-only", "not-applicable"}


class ComponentInventoryError(RuntimeError):
    pass


def _compose_services(path):
    if not path.is_file():
        return set()
    services = set()
    in_services = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw == "services:":
            in_services = True
            continue
        if in_services and raw and not raw.startswith(" "):
            break
        if in_services:
            match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", raw)
            if match:
                services.add(match.group(1))
    return services


def _validate_upgrade(stack_key, component, upgrade):
    if not isinstance(upgrade, dict):
        raise ComponentInventoryError(f"{stack_key}/{component['id']}: upgrade must be an object")
    missing = {"default_policy", "execution"} - set(upgrade)
    if missing:
        raise ComponentInventoryError(
            f"{stack_key}/{component['id']}: upgrade missing fields: {', '.join(sorted(missing))}"
        )
    execution = upgrade.get("execution")
    if not isinstance(execution, dict) or execution.get("mode") not in EXECUTION_MODES:
        raise ComponentInventoryError(f"{stack_key}/{component['id']}: invalid upgrade execution metadata")
    selectable = upgrade.get("selectable", True)
    if not isinstance(selectable, bool):
        raise ComponentInventoryError(f"{stack_key}/{component['id']}: selectable must be boolean")
    blocked_by = execution.get("blocked_by")
    if selectable:
        if execution["mode"] != "guarded" or blocked_by is not None:
            raise ComponentInventoryError(
                f"{stack_key}/{component['id']}: selectable components require guarded execution"
            )
    elif execution["mode"] == "guarded" or not isinstance(blocked_by, str) or not blocked_by:
        raise ComponentInventoryError(f"{stack_key}/{component['id']}: non-selectable components require a blocker")
    return dict(upgrade)


def compile_components():
    try:
        manifests = all_manifests()
    except ManifestError as exc:
        raise ComponentInventoryError(str(exc)) from exc
    result = []
    seen_keys = set()
    for sid in sorted(manifests):
        manifest = manifests[sid]
        stack_key = f"stack{sid}"
        components = manifest.get("components")
        if not isinstance(components, list) or not components:
            raise ComponentInventoryError(f"{stack_key}: manifest components must be a non-empty list")
        owned_containers = {
            value.split(":", 1)[1]
            for value in manifest.get("owns", [])
            if isinstance(value, str) and value.startswith("container:")
        }
        declared_containers = set()
        compose = ROOT / manifest["directory"] / "docker-compose.yml"
        services = _compose_services(compose)
        for index, raw in enumerate(components):
            if not isinstance(raw, dict):
                raise ComponentInventoryError(f"{stack_key}: components[{index}] must be an object")
            component_id = raw.get("id")
            if not isinstance(component_id, str) or not component_id.strip():
                raise ComponentInventoryError(f"{stack_key}: components[{index}].id must be a non-empty string")
            key = f"{stack_key}/{component_id}"
            if key in seen_keys:
                raise ComponentInventoryError(f"duplicate component id: {key}")
            seen_keys.add(key)
            management = raw.get("management")
            if not isinstance(management, dict) or management.get("type") not in MANAGEMENT_TYPES:
                raise ComponentInventoryError(f"{key}: management.type must be one of {sorted(MANAGEMENT_TYPES)}")
            service = raw.get("service")
            container = raw.get("container")
            if service is not None and (not isinstance(service, str) or not service):
                raise ComponentInventoryError(f"{key}: service must be a non-empty string")
            if container is not None and (not isinstance(container, str) or not container):
                raise ComponentInventoryError(f"{key}: container must be a non-empty string")
            if container:
                if container not in owned_containers:
                    raise ComponentInventoryError(f"{key}: container {container} is not declared in manifest owns")
                if container in declared_containers:
                    raise ComponentInventoryError(
                        f"{stack_key}: container {container} is declared by multiple components"
                    )
                declared_containers.add(container)
            if service and service not in services:
                raise ComponentInventoryError(f"{key}: Compose service not found: {service}")
            item = {
                "stack": stack_key,
                "stack_id": sid,
                "stack_directory": manifest["directory"],
                "id": component_id,
                "service": service,
                "container": container,
                "management": dict(management),
            }
            if "upgrade" in raw:
                item["upgrade"] = _validate_upgrade(stack_key, raw, raw["upgrade"])
            result.append(item)
        missing = owned_containers - declared_containers
        if missing:
            raise ComponentInventoryError(
                f"{stack_key}: owned containers lack component semantics: {', '.join(sorted(missing))}"
            )
    return result


def compile_upgrade_catalog():
    stacks = {}
    for component in compile_components():
        upgrade = component.get("upgrade")
        if upgrade is None:
            continue
        item = dict(upgrade)
        item["id"] = component["id"]
        if component.get("service"):
            item["service"] = component["service"]
        if component.get("container"):
            item["container"] = component["container"]
        compose_path = ROOT / component["stack_directory"] / "docker-compose.yml"
        if compose_path.is_file() and component.get("service"):
            item["compose"] = f"{component['stack_directory']}/docker-compose.yml"
        stacks.setdefault(component["stack"], []).append(item)
    return {
        "schema_version": 1,
        "stacks": [
            {"id": stack, "components": components}
            for stack, components in sorted(stacks.items(), key=lambda item: int(item[0][5:]))
        ],
    }
