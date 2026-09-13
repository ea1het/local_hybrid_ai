"""Core upgrade inventory, plan persistence and component metadata helpers.

This module keeps runtime observation, registry availability, compatibility
policy, selectability and explicit operator selection as separate facts. It owns
the installation-local upgrade plan format and component catalog interpretation,
but it does not execute upgrades; guarded mutation belongs to the executor.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from commands import upgrade_policy, upgrade_registry

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "commands" / "upgrade-components.json"
SCHEMA_VERSION = "1"


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
    return runtime_root() / "platform" / "upgrade-plan.json"


def load_catalog_raw() -> dict:
    try:
        raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeError(f"cannot read component catalog: {exc}", code="UPGRADE_CATALOG_INVALID") from exc
    if raw.get("schema_version") != 1 or not isinstance(raw.get("stacks"), list):
        raise UpgradeError("unsupported component catalog schema", code="UPGRADE_CATALOG_INVALID")
    return raw


def component_records() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for stack in load_catalog_raw()["stacks"]:
        for item in stack["components"]:
            record = dict(item)
            record["stack"] = stack["id"]
            result[f"{stack['id']}/{item['id']}"] = record
    return result


def load_catalog() -> list[Component]:
    result: list[Component] = []
    for stack in load_catalog_raw()["stacks"]:
        for item in stack["components"]:
            result.append(Component(
                stack=stack["id"],
                name=item["id"],
                service=item.get("service"),
                container=item.get("container"),
                compose=item.get("compose"),
                upstream=item.get("upstream"),
                selectable=item.get("selectable", True),
            ))
    return result


def read_env() -> dict[str, str]:
    result: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        path = ROOT / ".env.template"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def substitute_env(value: str, env: dict[str, str]) -> str:
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[-?]([^}]*))?\}")

    def repl(match: re.Match[str]) -> str:
        key, default = match.group(1), match.group(2)
        return env.get(key) or (default or match.group(0))

    return pattern.sub(repl, value)


def compose_image(component: Component, env: dict[str, str]) -> str | None:
    if not component.compose or not component.service:
        return None
    path = ROOT / component.compose
    if not path.is_file():
        return None
    current_service: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        service_match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", raw)
        if service_match:
            current_service = service_match.group(1)
            continue
        if current_service == component.service:
            image_match = re.match(r"^    image:\s*(.+?)\s*$", raw)
            if image_match:
                return substitute_env(image_match.group(1).strip('"').strip("'"), env)
    return None


def running_image(component: Component) -> str | None:
    if not component.container:
        return None
    try:
        cp = subprocess.run(
            ["docker", "inspect", "-f", "{{.Config.Image}}", component.container],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


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
    path = plan_path()
    if not path.is_file():
        return {"schema_version": 1, "selected": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeError(f"cannot read upgrade plan: {exc}", code="UPGRADE_PLAN_INVALID") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("selected"), dict):
        raise UpgradeError("unsupported upgrade plan schema", code="UPGRADE_PLAN_INVALID")
    return data


def save_plan(plan: dict) -> None:
    path = plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def key(component: Component) -> str:
    return f"{component.stack}/{component.name}"


def _registry_availability(
    component: Component,
    image: str | None,
    *,
    online: bool,
) -> tuple[str, dict | None, str | None]:
    if not online:
        return "unchecked", None, None
    try:
        state = upgrade_registry.inspect(component.container, image)
    except upgrade_registry.RegistryError as exc:
        raise UpgradeError(
            f"registry discovery failed for {key(component)}: {exc}",
            code="UPGRADE_REGISTRY_SOURCE_INVALID",
        ) from exc
    if state is None:
        return "n/a", None, None

    details = {
        "image": state.image,
        "registry": state.registry,
        "repository": state.repository,
        "tracking_image": state.tracking_image,
        "local_digest": state.local_digest,
        "remote_digest": state.remote_digest,
        "remote_status": state.remote_status,
        "tags_status": state.tags_status,
        "current_version": state.current_version,
        "available_version": state.available_version,
        "update_available": state.update_available,
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
    """Return upgrade-decision state without conflating it with installation intent.

    `actual` is observed runtime. `available` is registry discovery. Compatibility
    policy, executor selectability and operator selection are separate facts.
    Legacy `current` fields remain in JSON as aliases of actual for schema-1
    compatibility, but the human interface uses ACTUAL.
    """
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
            available, registry, discovered_current = _registry_availability(
                component,
                discovery_image,
                online=query_upstream,
            )
            if observed_image:
                actual_display = upgrade_registry.display_label(
                    observed_image,
                    discovered_version=discovered_current,
                )

        try:
            policy_state = upgrade_policy.selection_status(
                runtime_root(), component_key, record, selected.get(component_key)
            )
        except upgrade_policy.PolicyError as exc:
            raise UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc

        rows.append({
            "stack": component.stack,
            "component": component.name,
            "actual": actual,
            "actual_display": actual_display,
            "current": actual,
            "current_display": actual_display,
            "available": available,
            "policy": policy_state["effective_policy"],
            "selectable": component.selectable,
            "selected": selected.get(component_key, {}).get("version"),
            "selection_valid": policy_state["selection_valid"],
            "registry": registry,
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
    headers = ("STACK", "COMPONENT", "ACTUAL", "AVAILABLE", "POLICY", "SELECTABLE", "SELECTED", "VALID")
    values = [headers]
    for row in rows:
        valid = row["selection_valid"]
        values.append((
            human_stack_id(row["stack"]),
            row["component"],
            row.get("actual_display", row["actual"]),
            _human_available(row),
            row["policy"],
            "yes" if row["selectable"] else "no",
            row["selected"] or "-",
            "-" if valid is None else ("yes" if valid else "no"),
        ))
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
            raise UpgradeError(
                f"{stack} has multiple components; specify one: " + ", ".join(c.name for c in matches),
                code="UPGRADE_COMPONENT_REQUIRED",
            )
        component = matches[0]
    else:
        component = next((c for c in matches if c.name == name), None)
        if component is None:
            raise UpgradeError(f"unknown component for {stack}: {name}", code="UPGRADE_COMPONENT_UNKNOWN")
    if not component.selectable:
        raise UpgradeError(f"component is inventory-only: {key(component)}", code="UPGRADE_COMPONENT_NOT_SELECTABLE")
    return component
