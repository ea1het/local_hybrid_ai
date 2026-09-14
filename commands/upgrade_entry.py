# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Operator-facing upgrade command orchestration behind ``./local-ai upgrade``.

This module validates explicit selections, effective compatibility policy and
immutable registry target identity before delegating mutation to the guarded
executor. It also implements upgrade-policy inspection/mutation and stable
human/JSON command responses. Registry discovery never implies consent and
``--yes`` never broadens the set of already selected targets.
"""

from __future__ import annotations

import json
import sys

from commands import upgrade, upgrade_executor, upgrade_policy, upgrade_registry


def _component_record(component) -> dict:
    return upgrade.component_records()[upgrade.key(component)]


def _effective_policy(component) -> tuple[str, str | None, str]:
    try:
        return upgrade_policy.effective_policy(
            upgrade.runtime_root(),
            upgrade.key(component),
            _component_record(component),
        )
    except upgrade_policy.PolicyError as exc:
        raise upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc


def _target_reference(component, version: str, env: dict[str, str]) -> str:
    image = upgrade.running_image(component) or upgrade.compose_image(component, env)
    if not image:
        raise upgrade.UpgradeError(
            f"cannot determine image repository for {upgrade.key(component)}",
            code="UPGRADE_TARGET_NOT_AVAILABLE",
        )
    return upgrade_registry.parse_reference(image).with_tag(version)


def _probe_target(component, version: str, env: dict[str, str]) -> tuple[str, str]:
    target_ref = _target_reference(component, version, env)
    probe = upgrade_registry.manifest_probe(target_ref)
    if probe.status != "ok" or not probe.digest:
        raise upgrade.UpgradeError(
            f"target image is not available for {upgrade.key(component)}: {target_ref} ({probe.status})",
            code="UPGRADE_TARGET_NOT_AVAILABLE",
        )
    return target_ref, probe.digest


def _validate_target(component, current: str, version: str, env: dict[str, str]) -> tuple[str, str, str]:
    target_ref, target_digest = _probe_target(component, version, env)
    _, _, effective = _effective_policy(component)
    if not upgrade_policy.target_supported(effective, current, version):
        newer = upgrade_policy.target_is_newer(current, version)
        if newer is False:
            raise upgrade.UpgradeError(
                f"upgrade target is not newer for {upgrade.key(component)}: {current} -> {version}",
                code="UPGRADE_TARGET_NOT_NEWER",
            )
        raise upgrade.UpgradeError(
            f"target {version} is outside {effective} policy for {upgrade.key(component)}",
            code="UPGRADE_TARGET_UNSUPPORTED",
        )
    return effective, target_ref, target_digest


def select(stack: str, component_name: str | None, version: str) -> int:
    component = upgrade.find_component(stack, component_name)
    env = upgrade.read_env()
    current = upgrade.version_from_image(upgrade.running_image(component) or upgrade.compose_image(component, env))
    if current == version:
        raise upgrade.UpgradeError(
            f"{component.stack}/{component.name} is already at {version}",
            code="UPGRADE_ALREADY_CURRENT",
        )
    effective, target_ref, target_digest = _validate_target(component, current, version, env)
    plan = upgrade.load_plan()
    plan["selected"][upgrade.key(component)] = {
        "stack": component.stack,
        "component": component.name,
        "current_at_selection": current,
        "version": version,
        "policy_at_selection": effective,
        "target_image": target_ref,
        "target_digest": target_digest,
    }
    upgrade.save_plan(plan)
    print(
        f"Selected {component.stack}/{component.name}: {current} -> {version} "
        f"({effective}, {target_digest})"
    )
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


def _validate_immutable_target(component, selection: dict, env: dict[str, str]) -> None:
    target = selection.get("version")
    stored_ref = selection.get("target_image")
    stored_digest = selection.get("target_digest")
    if not all(isinstance(value, str) and value for value in (target, stored_ref, stored_digest)):
        raise upgrade.UpgradeError(
            f"upgrade selection predates immutable target identity for {upgrade.key(component)}; reselect the target",
            code="UPGRADE_PLAN_STALE",
        )

    target_ref = _target_reference(component, target, env)
    if target_ref != stored_ref:
        raise upgrade.UpgradeError(
            f"target image reference changed for {upgrade.key(component)}: selected {stored_ref}, now {target_ref}",
            code="UPGRADE_PLAN_STALE",
        )

    probe = upgrade_registry.manifest_probe(target_ref)
    if probe.status != "ok" or not probe.digest:
        raise upgrade.UpgradeError(
            f"selected target is no longer available for {upgrade.key(component)}: {target_ref} ({probe.status})",
            code="UPGRADE_TARGET_NOT_AVAILABLE",
        )
    if probe.digest != stored_digest:
        raise upgrade.UpgradeError(
            f"selected target tag moved for {upgrade.key(component)}: {stored_digest} -> {probe.digest}",
            code="UPGRADE_TARGET_MOVED",
        )


def validate_selected_baselines(selections: list[dict]) -> None:
    components = {upgrade.key(c): c for c in upgrade.load_catalog()}
    records = upgrade.component_records()
    env = upgrade.read_env()
    for selection in selections:
        component_key = f"{selection.get('stack')}/{selection.get('component')}"
        component = components.get(component_key)
        if component is None:
            raise upgrade.UpgradeError(
                f"selected component no longer exists: {component_key}",
                code="UPGRADE_PLAN_STALE",
            )
        if not component.selectable:
            raise upgrade.UpgradeError(
                f"selected component is no longer selectable: {component_key}",
                code="UPGRADE_COMPONENT_NOT_SELECTABLE",
            )
        current = upgrade.version_from_image(upgrade.running_image(component) or upgrade.compose_image(component, env))
        expected = selection.get("current_at_selection")
        if current != expected:
            raise upgrade.UpgradeError(
                f"upgrade plan is stale for {component_key}: selected from {expected}, current is {current}",
                code="UPGRADE_PLAN_STALE",
            )
        target = selection.get("version")
        if target == current:
            raise upgrade.UpgradeError(
                f"upgrade target is already current for {component_key}: {current}",
                code="UPGRADE_PLAN_STALE",
            )
        try:
            effective = upgrade_policy.effective_policy(
                upgrade.runtime_root(), component_key, records[component_key]
            )[2]
        except upgrade_policy.PolicyError as exc:
            raise upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc
        if not isinstance(target, str) or not upgrade_policy.target_supported(effective, current, target):
            raise upgrade.UpgradeError(
                f"selected target {target} is no longer permitted by {effective} policy for {component_key}",
                code="UPGRADE_TARGET_UNSUPPORTED",
            )
        _validate_immutable_target(component, selection, env)


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
    raise upgrade.UpgradeError(
        f"unknown component for {stack}: {component_name}",
        code="UPGRADE_COMPONENT_UNKNOWN",
    )


def _policy_row(component_key: str, record: dict, plan: dict) -> dict:
    try:
        state = upgrade_policy.selection_status(
            upgrade.runtime_root(), component_key, record, plan["selected"].get(component_key)
        )
    except upgrade_policy.PolicyError as exc:
        raise upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID") from exc
    return {
        "stack": record["stack"],
        "component": record["id"],
        **state,
        "selectable": record.get("selectable", True),
        "selected": plan["selected"].get(component_key, {}).get("version"),
    }


def _print_policy_rows(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "DEFAULT", "OVERRIDE", "EFFECTIVE", "SELECTABLE", "SELECTED", "VALID")
    values = [headers]
    for row in rows:
        valid = row["selection_valid"]
        values.append((
            upgrade.human_stack_id(row["stack"]),
            row["component"],
            row["default_policy"],
            row["override_policy"] or "-",
            row["effective_policy"],
            "yes" if row["selectable"] else "no",
            row["selected"] or "-",
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
            print(json.dumps({
                "schema_version": upgrade.SCHEMA_VERSION,
                "command": "upgrade.policy",
                "success": True,
                "components": rows,
            }, indent=2, sort_keys=True))
        else:
            _print_policy_rows(rows)
        return 0

    action = None
    policy = None
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
            raise upgrade.UpgradeError(
                f"unsupported upgrade policy: {policy}",
                code="UPGRADE_POLICY_INVALID",
            )
        upgrade_policy.set_override(upgrade.runtime_root(), component_key, policy)
    elif action == "clear":
        upgrade_policy.clear_override(upgrade.runtime_root(), component_key)

    after = _policy_row(component_key, record, plan)
    payload = {
        "schema_version": upgrade.SCHEMA_VERSION,
        "command": "upgrade.policy",
        "success": True,
        "action": action or "show",
        **after,
    }
    if action:
        payload["previous_effective_policy"] = before["effective_policy"]

    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif action:
        print(
            f"Policy {component_key}: {before['effective_policy']} -> {after['effective_policy']} "
            f"(default={after['default_policy']}, override={after['override_policy'] or '-'})"
        )
        if after["selection_valid"] is False:
            print(f"Existing selection {after['selected']} is now invalid; it was not cleared.")
    else:
        _print_policy_rows([after])
    return 0


def usage() -> None:
    print("Usage:")
    print("  ./local-ai upgrade check [--offline]")
    print("  ./local-ai upgrade policy")
    print("  ./local-ai upgrade policy <stack> [component]")
    print("  ./local-ai upgrade policy <stack> [component] set <minor-series|major-series|manual>")
    print("  ./local-ai upgrade policy <stack> [component] clear")
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
        if args and args[0] == "policy":
            return policy_command(args[1:], json_output=json_output)

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
    except (upgrade.UpgradeError, upgrade_policy.PolicyError, OSError, json.JSONDecodeError) as exc:
        if isinstance(exc, upgrade_policy.PolicyError):
            exc = upgrade.UpgradeError(str(exc), code="UPGRADE_POLICY_INVALID")
        elif not isinstance(exc, upgrade.UpgradeError):
            exc = upgrade.UpgradeError(str(exc))
        _print_error(exc, json_output=json_output)
        return 1
