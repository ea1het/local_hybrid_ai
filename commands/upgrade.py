from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from internal import container_registry, upgrade_executor

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "internal" / "upgrade-components.json"
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
    """Machine-facing installed identity used for stale-plan protection."""
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
        state = container_registry.inspect(component.container, image)
    except container_registry.RegistryError as exc:
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
    env = read_env()
    plan = load_plan()
    selected = plan["selected"]
    records = component_records()
    rows: list[dict] = []

    for component in load_catalog():
        desired_image = compose_image(component, env)
        actual_image = running_image(component) or desired_image
        current = version_from_image(actual_image)
        record = records[key(component)]
        registry = None
        availability = record.get("availability")
        current_display = current

        if availability in ("local", "n/a"):
            available = availability
            current_display = availability if availability == "local" else current
        else:
            available, registry, discovered_current = _registry_availability(
                component,
                actual_image,
                online=query_upstream,
            )
            if actual_image:
                current_display = container_registry.display_label(
                    actual_image,
                    discovered_version=discovered_current,
                )

        rows.append({
            "stack": component.stack,
            "component": component.name,
            "current": current,
            "current_display": current_display,
            "available": available,
            "selected": selected.get(key(component), {}).get("version"),
            "selectable": component.selectable,
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
    headers = ("STACK", "COMPONENT", "CURRENT", "AVAILABLE", "SELECTED")
    values = [headers]
    for row in rows:
        values.append((
            human_stack_id(row["stack"]),
            row["component"],
            row.get("current_display", row["current"]),
            _human_available(row),
            row["selected"] or "-",
        ))
    widths = [max(len(str(row[i])) for row in values) for i in range(5)]
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


def select_component(stack: str, name: str | None, version: str) -> None:
    component = find_component(stack, name)
    current = next(
        row["current"]
        for row in inventory(query_upstream=False)
        if row["stack"] == stack and row["component"] == component.name
    )
    if version == current:
        raise UpgradeError(f"{key(component)} is already at {version}", code="UPGRADE_ALREADY_CURRENT")
    plan = load_plan()
    plan["selected"][key(component)] = {"version": version, "current_at_selection": current}
    save_plan(plan)
    print(f"Selected {key(component)}: {current} -> {version}")


def clear_selection(stack: str | None = None, name: str | None = None) -> None:
    plan = load_plan()
    if stack is None:
        plan["selected"] = {}
    else:
        if name is None:
            for component_key in list(plan["selected"]):
                if component_key.startswith(stack + "/"):
                    del plan["selected"][component_key]
        else:
            plan["selected"].pop(f"{stack}/{name}", None)
    save_plan(plan)
    print("Upgrade selection cleared.")


def validate_selected_baselines(plan: dict, rows: list[dict]) -> None:
    by_key = {f"{row['stack']}/{row['component']}": row for row in rows}
    for component_key, selection in plan["selected"].items():
        row = by_key.get(component_key)
        if row is None:
            raise UpgradeError(f"selected component disappeared: {component_key}", code="UPGRADE_PLAN_STALE")
        if row["current"] != selection.get("current_at_selection") or row["current"] == selection.get("version"):
            raise UpgradeError(f"stale upgrade selection: {component_key}", code="UPGRADE_PLAN_STALE")


def execute_selected(*, json_output: bool) -> dict:
    plan = load_plan()
    if not plan["selected"]:
        raise UpgradeError("no selected upgrades", code="UPGRADE_NOTHING_SELECTED")
    rows = inventory(query_upstream=False)
    validate_selected_baselines(plan, rows)
    try:
        result = upgrade_executor.execute(
            root=ROOT,
            runtime_root=runtime_root(),
            plan=plan,
            component_records=component_records(),
            quiet=json_output,
        )
    except upgrade_executor.UpgradeExecutionError as exc:
        raise UpgradeError(str(exc), code=exc.code, recovery_point=exc.recovery_point) from exc
    if json_output:
        return {
            "schema_version": SCHEMA_VERSION,
            "command": "upgrade.apply",
            "success": True,
            "recovery_point": result.recovery_point,
            "upgraded": result.upgraded,
            "reverified_stacks": result.reverified_stacks,
        }
    if result.recovery_point:
        print(f"Recovery point: {result.recovery_point}")
    print("UPGRADE: PASS")
    for item in result.upgraded:
        print(f"  {item['component']}: {item['from']} -> {item['to']}")
    if result.reverified_stacks:
        print("  reverified consumers: " + ", ".join(result.reverified_stacks))
    return {}


def run(args, *, json_output: bool) -> int:
    try:
        if args.upgrade_command == "check":
            rows = inventory(query_upstream=not args.offline)
            if json_output:
                print(json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "command": "upgrade.check",
                    "success": True,
                    "components": rows,
                }))
            else:
                print_table(rows)
            return 0
        if args.upgrade_command == "select":
            select_component(args.stack, args.component, args.version)
            return 0
        if args.upgrade_command == "clear":
            clear_selection(args.stack, args.component)
            return 0
        if args.upgrade_command is None and getattr(args, "yes", False):
            payload = execute_selected(json_output=json_output)
            if json_output:
                print(json.dumps(payload))
            return 0
        raise UpgradeError("missing upgrade subcommand", code="UPGRADE_USAGE")
    except UpgradeError as exc:
        if json_output:
            error = {"code": exc.code, "message": str(exc)}
            if exc.recovery_point:
                error["recovery_point"] = exc.recovery_point
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": "upgrade",
                "success": False,
                "error": error,
            }))
        else:
            print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
            if exc.recovery_point:
                print(f"Recovery point: {exc.recovery_point}", file=sys.stderr)
        return 1
