# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Operator-facing orchestration behind ``./local-ai upgrade``.

Selection identity and stale-plan validation live in upgrade_selection; this
module owns command parsing, policy presentation and execution delegation.
"""
from __future__ import annotations

import json
import sys

from commands import upgrade, upgrade_executor, upgrade_policy, upgrade_registry, upgrade_selection

# Compatibility surface retained for callers/tests while implementation lives at
# the selection boundary.
_component_record = upgrade_selection.component_record
_effective_policy = upgrade_selection.effective_policy
_resolve_component = upgrade_selection.resolve_component
_force_metadata = upgrade_selection.force_metadata
_require_selection_permission = upgrade_selection.require_selection_permission
_current_runtime_version = upgrade_selection.current_runtime_version
_target_reference = upgrade_selection.target_reference
_validate_target = upgrade_selection.validate_target
_validate_immutable_target = upgrade_selection.validate_immutable_target
validate_selected_baselines = upgrade_selection.validate_selected_baselines
_execution_records_for = upgrade_selection.execution_records_for


def select(stack: str, component_name: str | None, version: str, *, force: bool = False) -> int:
    component = _resolve_component(stack, component_name)
    forced, blocked_by = _require_selection_permission(component, force=force)
    env = upgrade.read_env()
    current = _current_runtime_version(component, env)
    if current == version:
        raise upgrade.UpgradeError(
            f"{component.stack}/{component.name} is already at {version}", code="UPGRADE_ALREADY_CURRENT"
        )
    effective, target_ref, target_digest = _validate_target(component, current, version, env)
    plan = upgrade.load_plan()
    selection = {
        "stack": component.stack,
        "component": component.name,
        "current_at_selection": current,
        "version": version,
        "policy_at_selection": effective,
        "target_image": target_ref,
        "target_digest": target_digest,
    }
    if forced:
        selection.update(forced=True, qualification_bypassed=blocked_by)
    plan["selected"][upgrade.key(component)] = selection
    upgrade.save_plan(plan)
    qualifier = f", FORCED: {blocked_by}" if forced else ""
    print(f"Selected {component.stack}/{component.name}: {current} -> {version} ({effective}, {target_digest}{qualifier})")
    return 0


def clear(stack: str, component_name: str | None) -> int:
    component = _resolve_component(stack, component_name)
    plan = upgrade.load_plan()
    plan["selected"].pop(upgrade.key(component), None)
    upgrade.save_plan(plan)
    print(f"Cleared {component.stack}/{component.name}")
    return 0


def selected_records() -> list[dict]:
    return [dict(value) for _, value in sorted(upgrade.load_plan()["selected"].items())]


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
            components=_execution_records_for(selections),
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
            marker = " [FORCED]" if item.get("forced") is True else ""
            print(f"- {item['stack']}/{item['component']}: {item['current_at_selection']} -> {item['version']}{marker}")
        if payload["reverified_stacks"]:
            print("- reverified consumers: " + ", ".join(payload["reverified_stacks"]))
    return 0


def json_payload(rows: list[dict]) -> dict:
    return {"schema_version": upgrade.SCHEMA_VERSION, "command": "upgrade.check", "success": True, "components": rows}


def _policy_record(stack: str, component_name: str | None) -> tuple[str, dict]:
    records = upgrade.component_records()
    matches = [(key, value) for key, value in records.items() if value.get("stack") == stack]
    if not matches:
        raise upgrade.UpgradeError(f"unknown stack: {stack}", code="UPGRADE_STACK_UNKNOWN")
    if component_name is None:
        if len(matches) != 1:
            raise upgrade.UpgradeError(
                f"{stack} has multiple components; specify one: " + ", ".join(v["id"] for _, v in matches),
                code="UPGRADE_COMPONENT_REQUIRED",
            )
        return matches[0]
    for component_key, record in matches:
        if record.get("id") == component_name:
            return component_key, record
    raise upgrade.UpgradeError(f"unknown component for {stack}: {component_name}", code="UPGRADE_COMPONENT_UNKNOWN")


def _policy_row(component_key: str, record: dict, plan: dict) -> dict:
    try:
        state = upgrade_policy.selection_status(
            upgrade.runtime_root(), component_key, record, plan["selected"].get(component_key)
        )
    except upgrade_policy.PolicyError as exc:
        raise upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc
    return {
        "stack": record["stack"], "component": record["id"], **state,
        "selectable": record.get("selectable", True),
        "selected": plan["selected"].get(component_key, {}).get("version"),
    }


def _print_policy_rows(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "DEFAULT", "OVERRIDE", "EFFECTIVE", "SELECTABLE", "SELECTED", "VALID")
    values = [headers]
    for row in rows:
        valid = row["selection_valid"]
        values.append((
            upgrade.human_stack_id(row["stack"]), row["component"], row["default_policy"],
            row["override_policy"] or "-", row["effective_policy"],
            "yes" if row["selectable"] else "no", row["selected"] or "-",
            "-" if valid is None else ("yes" if valid else "no"),
        ))
    widths = [max(len(str(row[i])) for row in values) for i in range(len(headers))]
    for index, row in enumerate(values):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def policy_command(args: list[str], *, json_output: bool) -> int:
    records = upgrade.component_records()
    plan = upgrade.load_plan()
    if not args:
        rows = [_policy_row(key, record, plan) for key, record in sorted(records.items())]
        if json_output:
            print(json.dumps({"schema_version": upgrade.SCHEMA_VERSION, "command": "upgrade.policy", "success": True, "components": rows}, indent=2, sort_keys=True))
        else:
            _print_policy_rows(rows)
        return 0
    action = policy = None
    left = list(args)
    if "set" in left:
        pos = left.index("set")
        target, right = left[:pos], left[pos + 1:]
        if len(right) != 1:
            raise upgrade.UpgradeError("invalid policy set syntax", code="UPGRADE_USAGE")
        action, policy, left = "set", right[0], target
    elif left[-1:] == ["clear"]:
        action, left = "clear", left[:-1]
    if len(left) not in (1, 2):
        raise upgrade.UpgradeError("invalid policy syntax", code="UPGRADE_USAGE")
    component_key, record = _policy_record(left[0], left[1] if len(left) == 2 else None)
    before = _policy_row(component_key, record, plan)
    if action == "set":
        if policy not in upgrade_policy.POLICIES:
            raise upgrade.UpgradeError(f"unsupported upgrade policy: {policy}", code="UPGRADE_POLICY_INVALID")
        upgrade_policy.set_override(upgrade.runtime_root(), component_key, policy)
    elif action == "clear":
        upgrade_policy.clear_override(upgrade.runtime_root(), component_key)
    after = _policy_row(component_key, record, plan)
    payload = {"schema_version": upgrade.SCHEMA_VERSION, "command": "upgrade.policy", "success": True, "action": action or "show", **after}
    if action:
        payload["previous_effective_policy"] = before["effective_policy"]
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif action:
        print(f"Policy {component_key}: {before['effective_policy']} -> {after['effective_policy']} (default={after['default_policy']}, override={after['override_policy'] or '-'})")
        if after["selection_valid"] is False:
            print(f"Existing selection {after['selected']} is now invalid; it was not cleared.")
    else:
        _print_policy_rows([after])
    return 0


def usage() -> None:
    print("Usage:")
    print("  ./local-ai upgrade [--offline]")
    print("  ./local-ai upgrade check [--offline]  # compatibility alias")
    print("  ./local-ai upgrade policy")
    print("  ./local-ai upgrade policy <stack> [component]")
    print("  ./local-ai upgrade policy <stack> [component] set <minor-series|major-series|manual>")
    print("  ./local-ai upgrade policy <stack> [component] clear")
    print("  ./local-ai upgrade <stack> [component] select <version> [--force]")
    print("  ./local-ai upgrade <stack> [component] clear")
    print("  ./local-ai upgrade --yes")


def _print_error(exc: upgrade.UpgradeError, *, json_output: bool) -> None:
    if json_output:
        payload = {"schema_version": upgrade.SCHEMA_VERSION, "success": False, "error": {"code": exc.code, "message": str(exc)}}
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
            print(json.dumps(json_payload(rows), indent=2) if json_output else "", end="" if json_output else "")
            if not json_output:
                upgrade.print_table(rows)
            return 0
        if args in (["--offline"], ["check", "--offline"], ["--offline", "check"]):
            rows = upgrade.inventory(query_upstream=False)
            if json_output:
                print(json.dumps(json_payload(rows), indent=2))
            else:
                upgrade.print_table(rows)
            return 0
        if args == ["--yes"]:
            return execute_selected(json_output=json_output)
        if args and args[0] == "policy":
            return policy_command(args[1:], json_output=json_output)
        if "select" in args:
            if args.count("--force") > 1:
                raise upgrade.UpgradeError("invalid select syntax", code="UPGRADE_USAGE")
            force = "--force" in args
            select_args = [arg for arg in args if arg != "--force"]
            pos = select_args.index("select")
            left, right = select_args[:pos], select_args[pos + 1:]
            if len(right) != 1 or len(left) not in (1, 2):
                raise upgrade.UpgradeError("invalid select syntax", code="UPGRADE_USAGE")
            return select(left[0], left[1] if len(left) == 2 else None, right[0], force=force)
        if args[-1:] == ["clear"] and len(args) in (2, 3):
            left = args[:-1]
            return clear(left[0], left[1] if len(left) == 2 else None)
        usage()
        return 2
    except (upgrade.UpgradeError, upgrade_policy.PolicyError, OSError, json.JSONDecodeError) as exc:
        if isinstance(exc, upgrade_policy.PolicyError):
            exc = upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID")
        elif not isinstance(exc, upgrade.UpgradeError):
            exc = upgrade.UpgradeError(str(exc))
        _print_error(exc, json_output=json_output)
        return 1
