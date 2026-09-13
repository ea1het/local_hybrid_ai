from __future__ import annotations

import json
from pathlib import Path

from commands import upgrade

SCHEMA_VERSION = "1"


class StatusError(RuntimeError):
    pass


def _deployed_versions(runtime_root: Path) -> dict[str, str]:
    """Return the last successfully applied version known for each component."""
    path = runtime_root / "platform" / "upgrade-history.jsonl"
    if not path.is_file():
        return {}

    deployed: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StatusError(f"cannot read upgrade history: {exc}") from exc

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StatusError(f"invalid upgrade history at line {number}") from exc
        if event.get("success") is not True:
            continue
        upgraded = event.get("upgraded", [])
        if not isinstance(upgraded, list):
            raise StatusError(f"invalid successful upgrade history at line {number}")
        for item in upgraded:
            if not isinstance(item, dict):
                raise StatusError(f"invalid successful upgrade history at line {number}")
            stack = item.get("stack")
            component = item.get("component")
            version = item.get("version")
            if all(isinstance(value, str) and value for value in (stack, component, version)):
                deployed[f"{stack}/{component}"] = version
    return deployed


def _drift(desired: str, actual: str) -> str:
    if desired == "n/a":
        return "unknown"
    return "ok" if desired == actual else "drift"


def inventory(*, runtime_root: Path | None = None, deployed_versions: dict[str, str] | None = None) -> list[dict]:
    """Build status without hiding state dependencies behind global runtime lookups."""
    env = upgrade.read_env()
    if deployed_versions is None:
        deployed_versions = _deployed_versions(runtime_root or upgrade.runtime_root())

    rows: list[dict] = []
    for component in upgrade.load_catalog():
        desired = upgrade.version_from_image(upgrade.compose_image(component, env))
        actual = upgrade.version_from_image(upgrade.running_image(component))
        rows.append({
            "stack": component.stack,
            "component": component.name,
            "desired": desired,
            "deployed": deployed_versions.get(upgrade.key(component), "unknown"),
            "actual": actual,
            "drift": _drift(desired, actual),
        })
    return rows


def _print_table(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "DESIRED", "DEPLOYED", "ACTUAL", "DRIFT")
    values = [headers]
    for row in rows:
        values.append((
            upgrade.human_stack_id(row["stack"]),
            row["component"],
            row["desired"],
            row["deployed"],
            row["actual"],
            row["drift"],
        ))
    widths = [max(len(str(row[i])) for row in values) for i in range(len(headers))]
    for index, row in enumerate(values):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def main(*, json_output: bool = False) -> int:
    try:
        rows = inventory()
    except (StatusError, OSError, json.JSONDecodeError) as exc:
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
            "components": rows,
        }, indent=2, sort_keys=True))
    else:
        _print_table(rows)
    return 0
