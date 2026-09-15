# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Core upgrade inventory, plan persistence and component metadata helpers.

This module keeps runtime observation, registry availability, compatibility
policy, selectability and explicit operator selection as separate facts. Stack
manifests own component topology and upgrade semantics; this module consumes the
compiled manifest view but does not execute upgrades. Guarded mutation belongs
to the executor.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from commands import (
    component_inventory,
    upgrade_cache,
    upgrade_catalog,
    upgrade_plan,
    upgrade_policy,
    upgrade_registry,
    upgrade_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1"
REGISTRY_CACHE_SCHEMA_VERSION = upgrade_cache.SCHEMA_VERSION
REGISTRY_CACHE_DEFAULT_TTL_SECONDS = upgrade_cache.DEFAULT_TTL_SECONDS
REGISTRY_CACHE_MAX_ENTRIES = upgrade_cache.MAX_ENTRIES


class UpgradeError(RuntimeError):
    def __init__(self, message: str, *, code: str = "UPGRADE_ERROR", recovery_point: str | None = None):
        super().__init__(message)
        self.code = code
        self.recovery_point = recovery_point


@dataclass(frozen=True)
class Component:
    stack: str
    name: str
    service: str | None
    container: str | None
    compose: str | None
    upstream: str | None
    selectable: bool = True


def runtime_root() -> Path:
    return Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT", "/opt/docker/runtime"))


def plan_path() -> Path:
    """Compatibility facade for callers that consume the persisted plan path."""
    return upgrade_plan.path(runtime_root())


def registry_cache_path() -> Path:
    return upgrade_cache.path(runtime_root())


def registry_cache_ttl_seconds() -> int:
    return upgrade_cache.ttl_seconds()


def _load_registry_cache() -> dict[str, dict]:
    return upgrade_cache.load(registry_cache_path())


def _save_registry_cache(entries: dict[str, dict]) -> None:
    cache_path = registry_cache_path()
    ordered = sorted(
        entries.items(),
        key=lambda item: float(item[1].get("stored_at", 0)),
        reverse=True,
    )[:REGISTRY_CACHE_MAX_ENTRIES]
    upgrade_cache.save(cache_path, dict(ordered))


def _registry_cache_key(component: Component, image: str, local_digest: str | None) -> str:
    return upgrade_cache.key(key(component), image, local_digest)


def _cached_registry_state(component: Component, image: str) -> upgrade_registry.RegistryState | None:
    ttl = registry_cache_ttl_seconds()
    if ttl <= 0:
        return None
    local = upgrade_registry.local_digest(component.container, image) if component.container else None
    entry = _load_registry_cache().get(_registry_cache_key(component, image, local))
    if not entry:
        return None
    stored_at = entry.get("stored_at")
    state = entry.get("state")
    if not isinstance(stored_at, (int, float)) or time.time() - float(stored_at) > ttl:
        return None
    if not isinstance(state, dict):
        return None
    try:
        return upgrade_registry.RegistryState(**state)
    except TypeError:
        return None


def _store_registry_state(component: Component, image: str, state: upgrade_registry.RegistryState) -> None:
    if registry_cache_ttl_seconds() <= 0:
        return
    entries = _load_registry_cache()
    entries[_registry_cache_key(component, image, state.local_digest)] = {
        "stored_at": time.time(),
        "state": dict(state.__dict__),
    }
    _save_registry_cache(entries)


def load_catalog_raw() -> dict:
    """Return the upgrade-shaped view compiled from validated stack manifests."""
    try:
        raw = component_inventory.compile_upgrade_catalog()
    except component_inventory.InventoryError as exc:
        raise UpgradeError(f"cannot compile component catalog: {exc}", code="UPGRADE_CATALOG_INVALID") from exc
    if raw.get("schema_version") != 1 or not isinstance(raw.get("stacks"), list):
        raise UpgradeError("unsupported component catalog schema", code="UPGRADE_CATALOG_INVALID")
    return raw


def component_records() -> dict[str, dict]:
    """Compatibility facade for callers consuming manifest component records."""
    return upgrade_catalog.records(load_catalog_raw())


def load_catalog() -> list[Component]:
    """Compatibility facade returning the established Component type."""
    return upgrade_catalog.components(load_catalog_raw(), Component)


def read_env() -> dict[str, str]:
    """Compatibility facade for callers that import runtime helpers from upgrade."""
    return upgrade_runtime.read_env(ROOT)


def substitute_env(value: str, env: dict[str, str]) -> str:
    """Compatibility facade for the extracted runtime helper."""
    return upgrade_runtime.substitute_env(value, env)


def compose_image(component: Component, env: dict[str, str]) -> str | None:
    """Return the configured image while preserving the established public API."""
    return upgrade_runtime.compose_image(ROOT, component, env)


def running_image(component: Component) -> str | None:
    """Return the observed container image while preserving the established public API."""
    return upgrade_runtime.running_image(ROOT, component)


def version_from_image(image: str | None) -> str:
    """Return the installed identity used for status and stale-plan protection."""
    if not image:
        return "n/a"
    if "@sha256:" in image:
        base, digest = image.split("@sha256:", 1)
        tag = base.rsplit(":", 1)[1] if ":" in base.rsplit("/", 1)[-1] else None
        return f"{tag}@{digest[:12]}" if tag else f"sha256:{digest[:12]}"
    tail = image.rsplit("/", 1)[-1]
    return tail.rsplit(":", 1)[1] if ":" in tail else "latest"


def load_plan() -> dict:
    """Compatibility facade for persisted upgrade selections."""
    try:
        return upgrade_plan.load(plan_path())
    except upgrade_plan.PlanError as exc:
        raise UpgradeError(str(exc), code="UPGRADE_PLAN_INVALID") from exc


def save_plan(plan: dict) -> None:
    """Compatibility facade for persisted upgrade selections."""
    upgrade_plan.save(plan_path(), plan)


def key(component: Component) -> str:
    return f"{component.stack}/{component.name}"


def _execution_metadata(record: dict, component: Component) -> dict:
    """Return explicit execution metadata while tolerating synthetic legacy records.

    Manifest-derived catalog records always declare execution metadata. Unit tests
    and private callers may provide reduced synthetic records; those must not make
    read-only inventory crash. Such records receive conservative metadata only for
    presentation.
    """
    execution = record.get("execution")
    if isinstance(execution, dict):
        return dict(execution)
    if component.selectable:
        return {"mode": "guarded"}
    return {"mode": "inventory-only", "blocked_by": "legacy-or-synthetic-record"}


def _registry_availability(component: Component, image: str | None, *, online: bool) -> tuple[str, dict | None, str | None]:
    if not online:
        return "unchecked", None, None
    try:
        state = _cached_registry_state(component, image) if image else None
        if state is None:
            state = upgrade_registry.inspect(component.container, image)
            if state is not None and image:
                _store_registry_state(component, image, state)
    except upgrade_registry.RegistryError as exc:
        raise UpgradeError(
            f"registry discovery failed for {key(component)}: {exc}",
            code="UPGRADE_REGISTRY_SOURCE_INVALID",
        ) from exc
    if state is None:
        return "n/a", None, None
    details = {
        "image": state.image, "registry": state.registry, "repository": state.repository,
        "tracking_image": state.tracking_image, "local_digest": state.local_digest,
        "remote_digest": state.remote_digest, "remote_status": state.remote_status,
        "tags_status": state.tags_status, "current_version": state.current_version,
        "available_version": state.available_version, "update_available": state.update_available,
    }
    if state.available_version:
        if state.current_version == state.available_version:
            return "current", details, state.current_version
        return state.available_version, details, state.current_version
    if state.update_available is True:
        return "update", details, state.current_version
    if state.update_available is False:
        return "current", details, state.current_version
    if state.remote_status == "not_tracked":
        return "pinned", details, state.current_version
    return "unknown", details, state.current_version


def inventory(*, query_upstream: bool = True) -> list[dict]:
    """Return upgrade-decision state without conflating it with installation intent."""
    env = read_env()
    plan = load_plan()
    selected = plan["selected"]
    records = component_records()
    rows: list[dict] = []
    for component in load_catalog():
        component_key = key(component)
        desired_image = compose_image(component, env)
        observed_image = running_image(component)
        discovery_image = observed_image or desired_image
        actual = version_from_image(observed_image)
        actual_display = actual
        record = records[component_key]
        registry = None
        availability = record.get("availability")
        if availability in ("local", "n/a"):
            available = availability
            if availability == "local" and observed_image:
                actual_display = "local"
        else:
            available, registry, discovered_current = _registry_availability(component, discovery_image, online=query_upstream)
            if observed_image:
                actual_display = upgrade_registry.display_label(observed_image, discovered_version=discovered_current)
        try:
            policy_state = upgrade_policy.selection_status(runtime_root(), component_key, record, selected.get(component_key))
        except upgrade_policy.PolicyError as exc:
            raise UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc
        rows.append({
            "stack": component.stack, "component": component.name, "actual": actual,
            "actual_display": actual_display, "current": actual, "current_display": actual_display,
            "available": available, "policy": policy_state["effective_policy"],
            "selectable": component.selectable, "execution": _execution_metadata(record, component),
            "selected": selected.get(component_key, {}).get("version"),
            "selection_valid": policy_state["selection_valid"], "registry": registry,
        })
    return rows


def human_stack_id(stack: str) -> str:
    match = re.fullmatch(r"stack(\d+)", stack)
    return match.group(1) if match else stack


def _human_available(row: dict) -> str:
    available = row["available"]
    registry = row.get("registry")
    if available == "unknown" and registry:
        status = registry.get("remote_status")
        if status == "rate_limited":
            return "unknown (rate limited)"
        if status and status not in {"ok", "not_tracked"}:
            return f"unknown ({status.replace('_', ' ')})"
        tags_status = registry.get("tags_status")
        if tags_status == "rate_limited":
            return "unknown (rate limited)"
        if tags_status and tags_status not in {"ok", "unchecked"}:
            return f"unknown ({tags_status.replace('_', ' ')})"
    return available


def print_table(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "INSTALLED", "AVAILABLE", "POLICY", "SELECTABLE", "SELECTED", "VALID")
    values = [headers]
    for row in rows:
        valid = row["selection_valid"]
        values.append((human_stack_id(row["stack"]), row["component"], row.get("actual_display", row["actual"]),
                       _human_available(row), row["policy"], "yes" if row["selectable"] else "no",
                       row["selected"] or "-", "-" if valid is None else ("yes" if valid else "no")))
    widths = [max(len(str(row[i])) for row in values) for i in range(len(headers))]
    for index, row in enumerate(values):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def find_component(stack: str, name: str | None) -> Component:
    matches = [c for c in load_catalog() if c.stack == stack]
    if not matches:
        raise UpgradeError(f"unknown stack: {stack}", code="UPGRADE_STACK_UNKNOWN")
    if name is None:
        if len(matches) != 1:
            raise UpgradeError(f"{stack} has multiple components; specify one: " + ", ".join(c.name for c in matches), code="UPGRADE_COMPONENT_REQUIRED")
        component = matches[0]
    else:
        component = next((c for c in matches if c.name == name), None)
        if component is None:
            raise UpgradeError(f"unknown component for {stack}: {name}", code="UPGRADE_COMPONENT_UNKNOWN")
    if not component.selectable:
        record = component_records()[key(component)]
        blocked_by = _execution_metadata(record, component)["blocked_by"]
        raise UpgradeError(f"component is inventory-only: {key(component)} ({blocked_by})", code="UPGRADE_COMPONENT_NOT_SELECTABLE")
    return component
