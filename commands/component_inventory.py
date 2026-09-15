# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compile and validate component topology from stack manifests.

Stack ``manifest.json`` files are the semantic source of truth. Compose binds a
component to an implementation, while this module validates that every owned
container has exactly one declared component and that every declared service
exists in the stack Compose file. The compiled upgrade view is derived on every
read; the optional runtime snapshot exists only to report structural changes
across rescans and is never an authority for management commands.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from commands import install

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
MANAGEMENT_TYPES = {"versioned", "local", "helper", "platform"}
EXECUTION_MODES = {"guarded", "inventory-only", "not-applicable"}


class InventoryError(RuntimeError):
    pass


def runtime_root() -> Path:
    return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT", "/opt/docker/runtime"))


def snapshot_path() -> Path:
    return runtime_root() / "platform" / "component-inventory.json"


def _compose_services(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    services: set[str] = set()
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


def _validate_upgrade(stack_key: str, component: dict, upgrade: object) -> dict:
    if not isinstance(upgrade, dict):
        raise InventoryError(f"{stack_key}/{component['id']}: upgrade must be an object")
    required = {"default_policy", "execution"}
    missing = required - set(upgrade)
    if missing:
        raise InventoryError(
            f"{stack_key}/{component['id']}: upgrade missing fields: {', '.join(sorted(missing))}"
        )
    execution = upgrade.get("execution")
    if not isinstance(execution, dict) or execution.get("mode") not in EXECUTION_MODES:
        raise InventoryError(f"{stack_key}/{component['id']}: invalid upgrade execution metadata")
    selectable = upgrade.get("selectable", True)
    if not isinstance(selectable, bool):
        raise InventoryError(f"{stack_key}/{component['id']}: selectable must be boolean")
    blocked_by = execution.get("blocked_by")
    if selectable:
        if execution["mode"] != "guarded" or blocked_by is not None:
            raise InventoryError(
                f"{stack_key}/{component['id']}: selectable components require guarded execution"
            )
    elif execution["mode"] == "guarded" or not isinstance(blocked_by, str) or not blocked_by:
        raise InventoryError(
            f"{stack_key}/{component['id']}: non-selectable components require a blocker"
        )
    return dict(upgrade)


def compile_components() -> list[dict]:
    """Return validated semantic component records from all manifests."""
    try:
        manifests = install.all_manifests()
    except install.InstallerError as exc:
        raise InventoryError(str(exc)) from exc

    result: list[dict] = []
    seen_keys: set[str] = set()
    for sid in sorted(manifests):
        manifest = manifests[sid]
        stack_key = f"stack{sid}"
        components = manifest.get("components")
        if not isinstance(components, list) or not components:
            raise InventoryError(f"{stack_key}: manifest components must be a non-empty list")

        owned_containers = {
            value.split(":", 1)[1]
            for value in manifest.get("owns", [])
            if isinstance(value, str) and value.startswith("container:")
        }
        declared_containers: set[str] = set()
        compose = ROOT / manifest["directory"] / "docker-compose.yml"
        services = _compose_services(compose)

        for index, raw in enumerate(components):
            if not isinstance(raw, dict):
                raise InventoryError(f"{stack_key}: components[{index}] must be an object")
            component_id = raw.get("id")
            if not isinstance(component_id, str) or not component_id.strip():
                raise InventoryError(f"{stack_key}: components[{index}].id must be a non-empty string")
            key = f"{stack_key}/{component_id}"
            if key in seen_keys:
                raise InventoryError(f"duplicate component id: {key}")
            seen_keys.add(key)

            management = raw.get("management")
            if not isinstance(management, dict) or management.get("type") not in MANAGEMENT_TYPES:
                raise InventoryError(f"{key}: management.type must be one of {sorted(MANAGEMENT_TYPES)}")

            service = raw.get("service")
            container = raw.get("container")
            if service is not None and (not isinstance(service, str) or not service):
                raise InventoryError(f"{key}: service must be a non-empty string")
            if container is not None and (not isinstance(container, str) or not container):
                raise InventoryError(f"{key}: container must be a non-empty string")
            if container:
                if container not in owned_containers:
                    raise InventoryError(f"{key}: container {container} is not declared in manifest owns")
                if container in declared_containers:
                    raise InventoryError(f"{stack_key}: container {container} is declared by multiple components")
                declared_containers.add(container)
            if service and service not in services:
                raise InventoryError(f"{key}: Compose service not found: {service}")

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
            raise InventoryError(
                f"{stack_key}: owned containers lack component semantics: {', '.join(sorted(missing))}"
            )

    return result


def compile_upgrade_catalog() -> dict:
    """Derive the legacy-shaped upgrade catalog from manifest component metadata."""
    stacks: dict[str, list[dict]] = {}
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


def source_fingerprint() -> str:
    """Fingerprint manifest and Compose source without consulting Docker or registries."""
    digest = hashlib.sha256()
    try:
        manifests = install.all_manifests()
    except install.InstallerError as exc:
        raise InventoryError(str(exc)) from exc
    for sid in sorted(manifests):
        directory = ROOT / manifests[sid]["directory"]
        for name in ("manifest.json", "docker-compose.yml"):
            path = directory / name
            digest.update(f"stack{sid}/{name}\0".encode())
            if path.is_file():
                digest.update(path.read_bytes())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def snapshot() -> dict:
    components = compile_components()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_fingerprint": source_fingerprint(),
        "components": [
            {
                "stack": item["stack"],
                "id": item["id"],
                "management_type": item["management"]["type"],
                "service": item.get("service"),
                "container": item.get("container"),
                "upgrade_visible": "upgrade" in item,
            }
            for item in components
        ],
    }


def read_snapshot() -> dict | None:
    path = snapshot_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("components"), list):
        return None
    return data


def diff(previous: dict | None, current: dict) -> dict:
    previous_map = {
        f"{item['stack']}/{item['id']}": item
        for item in (previous or {}).get("components", [])
        if isinstance(item, dict) and isinstance(item.get("stack"), str) and isinstance(item.get("id"), str)
    }
    current_map = {f"{item['stack']}/{item['id']}": item for item in current["components"]}
    added = sorted(set(current_map) - set(previous_map))
    removed = sorted(set(previous_map) - set(current_map))
    changed = sorted(
        key for key in set(current_map) & set(previous_map)
        if current_map[key] != previous_map[key]
    )
    return {"added": added, "removed": removed, "changed": changed}


def write_snapshot(current: dict) -> None:
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
