#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

STACK_DIR_RE = re.compile(r"^stack(?P<id>[0-9]+)_-_.+$")
RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_recovery_schema(root: Path) -> dict:
    schema_path = root / "recovery.schema.json"
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {schema_path}: {exc}")

    try:
        contract = schema["$defs"]["contract"]
        resource = schema["$defs"]["resource"]
        restore = schema["$defs"]["restore"]
        schema_version = contract["properties"]["schema_version"]["const"]
        modes = set(contract["properties"]["mode"]["enum"])
        classes = set(resource["properties"]["class"]["enum"])
        strategies = set(resource["properties"]["strategy"]["enum"])
        restore_phases = set(restore["properties"]["phase"]["enum"])
    except (KeyError, TypeError) as exc:
        fail(f"invalid recovery schema structure in {schema_path}: missing {exc}")

    if schema_version != 1:
        fail(f"unsupported recovery schema version in {schema_path}: {schema_version}")

    return {
        "path": schema_path,
        "version": schema_version,
        "modes": modes,
        "classes": classes,
        "strategies": strategies,
        "restore_phases": restore_phases,
    }


def require_exact_keys(value: dict, required: set[str], optional: set[str], where: str) -> None:
    missing = required - set(value)
    if missing:
        fail(f"{where}: missing required fields: {', '.join(sorted(missing))}")
    unexpected = set(value) - required - optional
    if unexpected:
        fail(f"{where}: unsupported fields: {', '.join(sorted(unexpected))}")


def require_non_empty_string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{where} must be a non-empty string")
    return value


def validate_restore(restore: object, recovery_schema: dict, where: str) -> None:
    if not isinstance(restore, dict):
        fail(f"{where} must be an object")
    require_exact_keys(restore, {"phase"}, set(), where)
    phase = restore["phase"]
    if phase not in recovery_schema["restore_phases"]:
        fail(f"{where}.phase has unsupported value: {phase}")


def validate_recovery_resource(resource: object, recovery_schema: dict, where: str) -> None:
    if not isinstance(resource, dict):
        fail(f"{where} must be an object")

    require_exact_keys(
        resource,
        {"id", "class", "strategy", "sensitive"},
        {"config"},
        where,
    )

    resource_id = require_non_empty_string(resource["id"], f"{where}.id")
    if not RESOURCE_ID_RE.fullmatch(resource_id):
        fail(f"{where}.id has invalid format: {resource_id}")

    resource_class = resource["class"]
    if resource_class not in recovery_schema["classes"]:
        fail(f"{where}.class has unsupported value: {resource_class}")

    strategy = resource["strategy"]
    if strategy not in recovery_schema["strategies"]:
        fail(f"{where}.strategy has unsupported value: {strategy}")

    if not isinstance(resource["sensitive"], bool):
        fail(f"{where}.sensitive must be boolean")

    if "config" not in resource or not isinstance(resource["config"], dict):
        fail(f"{where}.config must be an object for strategy {strategy}")

    config = resource["config"]
    strategy_contracts = {
        "archive": {
            "source_type": "runtime-path",
            "source_required": {"type", "path"},
            "source_optional": set(),
            "config_optional": {"quiesce_container"},
            "restore_required": True,
        },
        "postgres-custom-dump": {
            "source_type": "postgres",
            "source_required": {"type", "service", "database_env"},
            "source_optional": {"user_env"},
            "config_optional": set(),
            "restore_required": True,
        },
        "gitea-native-dump": {
            "source_type": "application",
            "source_required": {"type", "service"},
            "source_optional": set(),
            "config_optional": set(),
            "restore_required": True,
        },
        "external-config": {
            "source_type": "environment",
            "source_required": {"type", "key"},
            "source_optional": set(),
            "config_optional": set(),
            "restore_required": False,
        },
        "git": {
            "source_type": "git",
            "source_required": {"type"},
            "source_optional": {"repository_env"},
            "config_optional": set(),
            "restore_required": False,
        },
    }

    contract = strategy_contracts.get(strategy)
    if contract is None:
        fail(f"{where}.strategy is declared by schema but unsupported by validator: {strategy}")

    required_config = {"source"}
    optional_config = contract["config_optional"]
    if contract["restore_required"]:
        required_config.add("restore")
    require_exact_keys(config, required_config, optional_config, f"{where}.config")

    source = config["source"]
    if not isinstance(source, dict):
        fail(f"{where}.config.source must be an object")
    require_exact_keys(
        source,
        contract["source_required"],
        contract["source_optional"],
        f"{where}.config.source",
    )
    if source["type"] != contract["source_type"]:
        fail(
            f"{where}.config.source.type must be {contract['source_type']} "
            f"for strategy {strategy}"
        )

    for key, value in source.items():
        if key != "type":
            require_non_empty_string(value, f"{where}.config.source.{key}")

    if "quiesce_container" in config:
        require_non_empty_string(config["quiesce_container"], f"{where}.config.quiesce_container")

    if contract["restore_required"]:
        validate_restore(config["restore"], recovery_schema, f"{where}.config.restore")


def validate_recovery(data: dict, recovery_schema: dict, manifest_path: Path) -> None:
    recovery = data.get("recovery")
    if not isinstance(recovery, dict):
        fail(f"{manifest_path}: recovery must be an object")

    require_exact_keys(recovery, {"contract"}, {"resources"}, f"{manifest_path}: recovery")

    contract = recovery["contract"]
    if not isinstance(contract, dict):
        fail(f"{manifest_path}: recovery.contract must be an object")
    require_exact_keys(
        contract,
        {"schema_version", "mode"},
        set(),
        f"{manifest_path}: recovery.contract",
    )

    if contract["schema_version"] != recovery_schema["version"]:
        fail(
            f"{manifest_path}: recovery.contract.schema_version must be "
            f"{recovery_schema['version']}"
        )

    mode = contract["mode"]
    if mode not in recovery_schema["modes"]:
        fail(f"{manifest_path}: unsupported recovery mode: {mode}")

    resources = recovery.get("resources")
    if resources is not None:
        if not isinstance(resources, list) or not resources:
            fail(f"{manifest_path}: recovery.resources must be a non-empty list when present")

        resource_ids: set[str] = set()
        for index, resource in enumerate(resources):
            where = f"{manifest_path}: recovery.resources[{index}]"
            validate_recovery_resource(resource, recovery_schema, where)
            resource_id = resource["id"]
            if resource_id in resource_ids:
                fail(f"{manifest_path}: duplicate recovery resource id: {resource_id}")
            resource_ids.add(resource_id)

    if mode in {"managed", "mixed"} and resources is None:
        fail(f"{manifest_path}: recovery mode {mode} requires resources")

    if mode == "reconstructable" and resources is not None:
        for resource in resources:
            if resource["class"] != "externalized":
                fail(
                    f"{manifest_path}: reconstructable stacks may only declare "
                    "externalized recovery resources"
                )


def load_manifests(root: Path) -> dict[int, dict]:
    manifests: dict[int, dict] = {}
    recovery_schema = load_recovery_schema(root)

    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        match = STACK_DIR_RE.match(directory.name)
        if not match:
            continue

        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            fail(f"missing manifest: {manifest_path}")

        try:
            data = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"cannot read {manifest_path}: {exc}")

        stack_id = data.get("id")
        if not isinstance(stack_id, int) or stack_id < 0:
            fail(f"invalid id in {manifest_path}")
        if stack_id != int(match.group("id")):
            fail(f"manifest id {stack_id} does not match directory {directory.name}")
        if data.get("directory") != directory.name:
            fail(f"manifest directory does not match {directory.name}")
        if data.get("schema_version") != 1:
            fail(f"unsupported schema_version in {manifest_path}")
        if stack_id in manifests:
            fail(f"duplicate stack id {stack_id}")

        for key in ("requires", "optional", "provides", "owns"):
            if key not in data or not isinstance(data[key], list):
                fail(f"{manifest_path}: {key} must be a list")

        for key in ("target_requires", "blockers", "consumes", "optional_consumes"):
            if key in data and not isinstance(data[key], list):
                fail(f"{manifest_path}: {key} must be a list")

        if "atomic" in data and not isinstance(data["atomic"], bool):
            fail(f"{manifest_path}: atomic must be boolean")

        validate_recovery(data, recovery_schema, manifest_path)
        manifests[stack_id] = data

    if not manifests:
        fail("no stack manifests found")

    return manifests


def dependency_key(target: bool) -> str:
    return "target_requires" if target else "requires"


def dependencies(data: dict, target: bool) -> list[int]:
    if target and "target_requires" in data:
        return data["target_requires"]
    return data["requires"]


def validate_graph(manifests: dict[int, dict], target: bool) -> None:
    for stack_id, data in manifests.items():
        for dep in dependencies(data, target):
            if not isinstance(dep, int):
                fail(f"stack{stack_id}: dependency ids must be integers")
            if dep == stack_id:
                fail(f"stack{stack_id}: self dependency")
            if dep not in manifests:
                fail(f"stack{stack_id}: unknown dependency stack{dep}")

        for dep in data["optional"]:
            if not isinstance(dep, int):
                fail(f"stack{stack_id}: optional dependency ids must be integers")
            if dep == stack_id:
                fail(f"stack{stack_id}: self optional dependency")
            if dep not in manifests:
                fail(f"stack{stack_id}: unknown optional stack{dep}")

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(stack_id: int) -> None:
        if stack_id in visited:
            return
        if stack_id in visiting:
            fail(f"dependency cycle detected at stack{stack_id}")
        visiting.add(stack_id)
        for dep in dependencies(manifests[stack_id], target):
            visit(dep)
        visiting.remove(stack_id)
        visited.add(stack_id)

    for stack_id in sorted(manifests):
        visit(stack_id)


def dependency_closure(
    manifests: dict[int, dict],
    roots: list[int],
    target: bool,
) -> set[int]:
    closure: set[int] = set()

    def add(stack_id: int) -> None:
        if stack_id in closure:
            return
        closure.add(stack_id)
        for dep in dependencies(manifests[stack_id], target):
            add(dep)

    for stack_id in roots:
        add(stack_id)

    return closure


def validate_contracts(manifests: dict[int, dict], target: bool) -> None:
    providers: dict[str, set[int]] = {}
    owner_of: dict[str, int] = {}

    for stack_id, data in manifests.items():
        for key in ("provides", "owns", "consumes", "optional_consumes"):
            values = data.get(key, [])

            for value in values:
                if not isinstance(value, str) or not value.strip():
                    fail(f"stack{stack_id}: {key} entries must be non-empty strings")

            if len(values) != len(set(values)):
                fail(f"stack{stack_id}: duplicate entries in {key}")

        for capability in data["provides"]:
            providers.setdefault(capability, set()).add(stack_id)

        for resource in data["owns"]:
            previous = owner_of.get(resource)

            if previous is not None:
                fail(
                    f"ownership collision: {resource} is owned by "
                    f"stack{previous} and stack{stack_id}"
                )

            owner_of[resource] = stack_id

    for stack_id, data in manifests.items():
        required_stacks = dependency_closure(
            manifests,
            dependencies(data, target),
            target,
        )

        optional_stacks = dependency_closure(
            manifests,
            data["optional"],
            target,
        )

        available_optional = required_stacks | optional_stacks

        for capability in data.get("consumes", []):
            capability_providers = providers.get(capability, set())

            if not capability_providers:
                fail(
                    f"stack{stack_id}: required capability {capability} "
                    f"has no provider"
                )

            if not (capability_providers & required_stacks):
                fail(
                    f"stack{stack_id}: required capability {capability} "
                    f"is not provided by its required dependency closure"
                )

        for capability in data.get("optional_consumes", []):
            capability_providers = providers.get(capability, set())

            if not capability_providers:
                fail(
                    f"stack{stack_id}: optional capability {capability} "
                    f"has no provider"
                )

            if not (capability_providers & available_optional):
                fail(
                    f"stack{stack_id}: optional capability {capability} "
                    f"is not reachable through required/optional dependencies"
                )


def resolve_token(token: str, manifests: dict[int, dict]) -> int:
    if token.isdigit():
        stack_id = int(token)
    elif re.fullmatch(r"stack[0-9]+", token):
        stack_id = int(token[5:])
    else:
        matches = [sid for sid, data in manifests.items() if data["directory"] == token]
        if len(matches) != 1:
            fail(f"unknown stack selector: {token}")
        stack_id = matches[0]

    if stack_id not in manifests:
        fail(f"unknown stack: {token}")
    return stack_id


def plan(requested: list[int], manifests: dict[int, dict], target: bool) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()

    def add(stack_id: int) -> None:
        if stack_id in seen:
            return
        for dep in dependencies(manifests[stack_id], target):
            add(dep)
        seen.add(stack_id)
        ordered.append(stack_id)

    for stack_id in requested:
        add(stack_id)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="Stack manifest registry and dependency planner")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--target", action="store_true")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    sub.add_parser("directories")

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    plan_parser.add_argument("--target", action="store_true")
    plan_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    root = args.root.resolve()
    manifests = load_manifests(root)

    if args.command == "validate":
        validate_graph(manifests, args.target)
        validate_contracts(manifests, args.target)
        mode = "target" if args.target else "current"
        print(f"manifest graph ({mode}): OK ({len(manifests)} stacks)")
        return

    validate_graph(manifests, False)
    validate_contracts(manifests, False)
    validate_graph(manifests, True)
    validate_contracts(manifests, True)

    if args.command == "directories":
        for stack_id in sorted(manifests):
            print(manifests[stack_id]["directory"])
        return

    if args.command == "list":
        if args.json:
            print(json.dumps([manifests[sid] for sid in sorted(manifests)], indent=2))
        else:
            for stack_id in sorted(manifests):
                data = manifests[stack_id]
                atomic = "atomic" if data.get("atomic", False) else "blocked"
                recovery_mode = data["recovery"]["contract"]["mode"]
                print(
                    f"stack{stack_id}: {data['directory']} "
                    f"[{atomic}] [recovery:{recovery_mode}]"
                )
                for blocker in data.get("blockers", []):
                    print(f"  blocker: {blocker}")
        return

    if args.command == "plan":
        if len(args.stacks) == 1 and args.stacks[0] == "all":
            requested = sorted(manifests)
        else:
            if "all" in args.stacks:
                fail("all cannot be combined with explicit stack selectors")
            requested = [resolve_token(token, manifests) for token in args.stacks]

        result = plan(requested, manifests, args.target)
        if args.json:
            print(json.dumps(result))
        else:
            for stack_id in result:
                print(manifests[stack_id]["directory"])
        return

    fail("unsupported command")


if __name__ == "__main__":
    main()
