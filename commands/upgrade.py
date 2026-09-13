from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from internal import upgrade_executor, version_sources

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


def inventory(*, query_upstream: bool = True) -> list[dict]:
    env = read_env()
    plan = load_plan()
    selected = plan["selected"]
    records = component_records()
    rows: list[dict] = []
    for component in load_catalog():
        desired_image = compose_image(component, env)
        actual_image = running_image(component) or desired_image
        try:
            available = version_sources.available_version(records[key(component)], online=query_upstream)
        except version_sources.VersionSourceError as exc:
            raise UpgradeError(
                f"invalid version source for {key(component)}: {exc}",
                code="UPGRADE_VERSION_SOURCE_INVALID",
            ) from exc
        rows.append({
            "stack": component.stack,
            "component": component.name,
            "current": version_from_image(actual_image),
            "available": available,
            "selected": selected.get(key(component), {}).get("version"),
            "selectable": component.selectable,
        })
    return rows


def human_stack_id(stack: str) -> str:
    match = re.fullmatch(r"stack(\d+)", stack)
    return match.group(1) if match else stack


def print_table(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "CURRENT", "AVAILABLE", "SELECTED")
    values = [headers]
    for row in rows:
        values.append((
            human_stack_id(row["stack"]), row["component"], row["current"], row["available"], row["selected"] or "-"
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
        raise UpgradeError(f"{component.stack}/{component.name} is not selectable", code="UPGRADE_COMPONENT_NOT_SELECTABLE")
    return component


def select(stack: str, component_name: str | None, version: str) -> int:
    component = find_component(stack, component_name)
    env = read_env()
    current = version_from_image(running_image(component) or compose_image(component, env))
    if current == version:
        raise UpgradeError(
            f"{component.stack}/{component.name} is already at {version}",
            code="UPGRADE_ALREADY_CURRENT",
        )
    plan = load_plan()
    plan["selected"][key(component)] = {
        "stack": component.stack,
        "component": component.name,
        "current_at_selection": current,
        "version": version,
    }
    save_plan(plan)
    print(f"Selected {component.stack}/{component.name}: {current} -> {version}")
    return 0


def clear(stack: str, component_name: str | None) -> int:
    component = find_component(stack, component_name)
    plan = load_plan()
    plan["selected"].pop(key(component), None)
    save_plan(plan)
    print(f"Cleared {component.stack}/{component.name}")
    return 0


def selected_records() -> list[dict]:
    plan = load_plan()
    return [dict(value) for _, value in sorted(plan["selected"].items())]


def validate_selected_baselines(selections: list[dict]) -> None:
    components = {key(c): c for c in load_catalog()}
    env = read_env()
    for selection in selections:
        component_key = f"{selection.get('stack')}/{selection.get('component')}"
        component = components.get(component_key)
        if component is None:
            raise UpgradeError(
                f"selected component no longer exists: {component_key}",
                code="UPGRADE_PLAN_STALE",
            )
        current = version_from_image(running_image(component) or compose_image(component, env))
        expected = selection.get("current_at_selection")
        if current != expected:
            raise UpgradeError(
                f"upgrade plan is stale for {component_key}: selected from {expected}, current is {current}",
                code="UPGRADE_PLAN_STALE",
            )
        if selection.get("version") == current:
            raise UpgradeError(
                f"upgrade target is already current for {component_key}: {current}",
                code="UPGRADE_PLAN_STALE",
            )


def execute_selected(*, json_output: bool) -> int:
    selections = selected_records()
    if not selections:
        raise UpgradeError("no upgrades are selected", code="UPGRADE_NOTHING_SELECTED")
    validate_selected_baselines(selections)
    try:
        result = upgrade_executor.execute(
            root=ROOT,
            runtime_root=runtime_root(),
            selections=selections,
            components=component_records(),
            plan_path=plan_path(),
            quiet=json_output,
        )
    except upgrade_executor.UpgradeExecutionError as exc:
        raise UpgradeError(str(exc), code=exc.code, recovery_point=exc.recovery_point) from exc

    payload = {
        "schema_version": SCHEMA_VERSION,
        "command": "upgrade.apply",
        "success": True,
        "recovery_point": result.get("recovery_point"),
        "upgraded": result.get("upgraded", []),
        "reverified_stacks": [f"stack{sid}" for sid in result.get("reverified_stacks", [])],
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("UPGRADE: PASS")
        if payload["recovery_point"]:
            print(f"- recovery point: {payload['recovery_point']}")
        for item in payload["upgraded"]:
            print(f"- {item['stack']}/{item['component']}: {item['current_at_selection']} -> {item['version']}")
        if payload["reverified_stacks"]:
            print("- reverified consumers: " + ", ".join(payload["reverified_stacks"]))
    return 0


def json_payload(rows: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "upgrade.check",
        "success": True,
        "components": rows,
    }


def usage() -> None:
    print("Usage:")
    print("  ./local-ai upgrade check [--offline]")
    print("  ./local-ai upgrade <stack> [component] select <version>")
    print("  ./local-ai upgrade <stack> [component] clear")
    print("  ./local-ai upgrade --yes")


def _print_error(exc: UpgradeError, *, json_output: bool) -> None:
    if json_output:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "success": False,
            "error": {"code": exc.code, "message": str(exc)},
        }
        if exc.recovery_point:
            payload["recovery_point"] = exc.recovery_point
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        suffix = f"; recovery point: {exc.recovery_point}" if exc.recovery_point else ""
        print(f"UPGRADE ERROR [{exc.code}]: {exc}{suffix}", file=sys.stderr)


def main(args: list[str], *, json_output: bool = False) -> int:
    try:
        if not args or args == ["check"]:
            rows = inventory(query_upstream=True)
            if json_output:
                print(json.dumps(json_payload(rows), indent=2))
            else:
                print_table(rows)
            return 0
        if args in (["check", "--offline"], ["--offline", "check"]):
            rows = inventory(query_upstream=False)
            if json_output:
                print(json.dumps(json_payload(rows), indent=2))
            else:
                print_table(rows)
            return 0
        if args == ["--yes"]:
            return execute_selected(json_output=json_output)

        if "select" in args:
            pos = args.index("select")
            left, right = args[:pos], args[pos + 1:]
            if len(right) != 1 or len(left) not in (1, 2):
                raise UpgradeError("invalid select syntax", code="UPGRADE_USAGE")
            return select(left[0], left[1] if len(left) == 2 else None, right[0])

        if args[-1:] == ["clear"] and len(args) in (2, 3):
            left = args[:-1]
            return clear(left[0], left[1] if len(left) == 2 else None)

        usage()
        return 2
    except (UpgradeError, OSError, json.JSONDecodeError) as exc:
        if not isinstance(exc, UpgradeError):
            exc = UpgradeError(str(exc))
        _print_error(exc, json_output=json_output)
        return 1
