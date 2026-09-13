from __future__ import annotations

import json
import sys

from commands import upgrade
from internal import upgrade_executor


def select(stack: str, component_name: str | None, version: str) -> int:
    component = upgrade.find_component(stack, component_name)
    env = upgrade.read_env()
    current = upgrade.version_from_image(upgrade.running_image(component) or upgrade.compose_image(component, env))
    if current == version:
        raise upgrade.UpgradeError(
            f"{component.stack}/{component.name} is already at {version}",
            code="UPGRADE_ALREADY_CURRENT",
        )
    plan = upgrade.load_plan()
    plan["selected"][upgrade.key(component)] = {
        "stack": component.stack,
        "component": component.name,
        "current_at_selection": current,
        "version": version,
    }
    upgrade.save_plan(plan)
    print(f"Selected {component.stack}/{component.name}: {current} -> {version}")
    return 0


def clear(stack: str, component_name: str | None) -> int:
    component = upgrade.find_component(stack, component_name)
    plan = upgrade.load_plan()
    plan["selected"].pop(upgrade.key(component), None)
    upgrade.save_plan(plan)
    print(f"Cleared {component.stack}/{component.name}")
    return 0


def selected_records() -> list[dict]:
    plan = upgrade.load_plan()
    return [dict(value) for _, value in sorted(plan["selected"].items())]


def validate_selected_baselines(selections: list[dict]) -> None:
    components = {upgrade.key(c): c for c in upgrade.load_catalog()}
    env = upgrade.read_env()
    for selection in selections:
        component_key = f"{selection.get('stack')}/{selection.get('component')}"
        component = components.get(component_key)
        if component is None:
            raise upgrade.UpgradeError(
                f"selected component no longer exists: {component_key}",
                code="UPGRADE_PLAN_STALE",
            )
        current = upgrade.version_from_image(upgrade.running_image(component) or upgrade.compose_image(component, env))
        expected = selection.get("current_at_selection")
        if current != expected:
            raise upgrade.UpgradeError(
                f"upgrade plan is stale for {component_key}: selected from {expected}, current is {current}",
                code="UPGRADE_PLAN_STALE",
            )
        if selection.get("version") == current:
            raise upgrade.UpgradeError(
                f"upgrade target is already current for {component_key}: {current}",
                code="UPGRADE_PLAN_STALE",
            )


def execute_selected(*, json_output: bool) -> int:
    selections = selected_records()
    if not selections:
        raise upgrade.UpgradeError("no upgrades are selected", code="UPGRADE_NOTHING_SELECTED")
    validate_selected_baselines(selections)
    try:
        result = upgrade_executor.execute(
            root=upgrade.ROOT,
            runtime_root=upgrade.runtime_root(),
            selections=selections,
            components=upgrade.component_records(),
            plan_path=upgrade.plan_path(),
            quiet=json_output,
        )
    except upgrade_executor.UpgradeExecutionError as exc:
        raise upgrade.UpgradeError(str(exc), code=exc.code, recovery_point=exc.recovery_point) from exc

    payload = {
        "schema_version": upgrade.SCHEMA_VERSION,
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
        "schema_version": upgrade.SCHEMA_VERSION,
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


def _print_error(exc: upgrade.UpgradeError, *, json_output: bool) -> None:
    if json_output:
        payload = {
            "schema_version": upgrade.SCHEMA_VERSION,
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
            rows = upgrade.inventory(query_upstream=True)
            if json_output:
                print(json.dumps(json_payload(rows), indent=2))
            else:
                upgrade.print_table(rows)
            return 0
        if args in (["check", "--offline"], ["--offline", "check"]):
            rows = upgrade.inventory(query_upstream=False)
            if json_output:
                print(json.dumps(json_payload(rows), indent=2))
            else:
                upgrade.print_table(rows)
            return 0
        if args == ["--yes"]:
            return execute_selected(json_output=json_output)

        if "select" in args:
            pos = args.index("select")
            left, right = args[:pos], args[pos + 1:]
            if len(right) != 1 or len(left) not in (1, 2):
                raise upgrade.UpgradeError("invalid select syntax", code="UPGRADE_USAGE")
            return select(left[0], left[1] if len(left) == 2 else None, right[0])

        if args[-1:] == ["clear"] and len(args) in (2, 3):
            left = args[:-1]
            return clear(left[0], left[1] if len(left) == 2 else None)

        usage()
        return 2
    except (upgrade.UpgradeError, OSError, json.JSONDecodeError) as exc:
        if not isinstance(exc, upgrade.UpgradeError):
            exc = upgrade.UpgradeError(str(exc))
        _print_error(exc, json_output=json_output)
        return 1
