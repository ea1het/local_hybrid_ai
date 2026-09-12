from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "internal" / "upgrade-components.json"
SCHEMA_VERSION = "1"


class UpgradeError(RuntimeError):
    pass


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


def load_catalog() -> list[Component]:
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise UpgradeError("unsupported component catalog schema")
    result: list[Component] = []
    for stack in raw["stacks"]:
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


def latest_release(repo: str | None) -> str:
    if not repo:
        return "unknown"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "local-ai-upgrade-check/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            data = json.load(response)
        return str(data.get("tag_name") or "unknown")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "unknown"


def load_plan() -> dict:
    path = plan_path()
    if not path.is_file():
        return {"schema_version": 1, "selected": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeError(f"cannot read upgrade plan: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("selected"), dict):
        raise UpgradeError("unsupported upgrade plan schema")
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
    rows: list[dict] = []
    for component in load_catalog():
        desired_image = compose_image(component, env)
        actual_image = running_image(component) or desired_image
        rows.append({
            "stack": component.stack,
            "component": component.name,
            "current": version_from_image(actual_image),
            "available": latest_release(component.upstream) if query_upstream else "unchecked",
            "selected": selected.get(key(component), {}).get("version"),
            "selectable": component.selectable,
        })
    return rows


def human_stack_id(stack: str) -> str:
    """Compact presentation only; machine/API identity remains e.g. stack7."""
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
        raise UpgradeError(f"unknown stack: {stack}")
    selectable = [c for c in matches if c.selectable]
    if name is None:
        if len(selectable) != 1:
            raise UpgradeError(
                f"{stack} has multiple selectable components; specify one: "
                + ", ".join(c.name for c in selectable)
            )
        return selectable[0]
    for component in matches:
        if component.name == name:
            if not component.selectable:
                raise UpgradeError(f"{stack}/{name} is not selectable")
            return component
    raise UpgradeError(f"unknown component for {stack}: {name}")


def select(stack: str, component_name: str | None, version: str) -> int:
    component = find_component(stack, component_name)
    env = read_env()
    current = version_from_image(running_image(component) or compose_image(component, env))
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
    print("  ./local-ai upgrade --yes   # executor intentionally not enabled yet")


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
            plan = load_plan()
            if not plan["selected"]:
                raise UpgradeError("no upgrades are selected")
            raise UpgradeError(
                "upgrade execution is not enabled until backup/rollback policy is wired into the executor; selections were preserved"
            )

        if "select" in args:
            pos = args.index("select")
            left, right = args[:pos], args[pos + 1:]
            if len(right) != 1 or len(left) not in (1, 2):
                raise UpgradeError("invalid select syntax")
            return select(left[0], left[1] if len(left) == 2 else None, right[0])

        if args[-1:] == ["clear"] and len(args) in (2, 3):
            left = args[:-1]
            return clear(left[0], left[1] if len(left) == 2 else None)

        usage()
        return 2
    except (UpgradeError, OSError, json.JSONDecodeError) as exc:
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "success": False,
                "error": {"code": "UPGRADE_ERROR", "message": str(exc)},
            }, indent=2))
        else:
            print(f"UPGRADE ERROR: {exc}", file=sys.stderr)
        return 1
