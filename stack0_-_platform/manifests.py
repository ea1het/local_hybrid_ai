#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

STACK_DIR_RE = re.compile(r"^stack(?P<id>[0-9]+)_-_.+$")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_manifests(root: Path) -> dict[int, dict]:
    manifests: dict[int, dict] = {}

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
                print(f"stack{stack_id}: {data['directory']} [{atomic}]")
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
