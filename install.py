#!/usr/bin/env python3
"""Common manifest-driven installer for local_hybrid_ai.

The installer orchestrates stack-owned lifecycle operations. Dependency and
capability truth stays in manifest.json; stack lifecycle entry points stay in
installer/lifecycle.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
LIFECYCLE_FILE = ROOT / "installer" / "lifecycle.json"


class InstallerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Action:
    stack_id: int
    directory: str
    phase: str
    command: tuple[str, ...]
    reason: str

    def display(self) -> str:
        return f"stack{self.stack_id} {self.phase}: {shlex.join(self.command)}"


def run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
    )


def manifest_json(*args: str) -> object:
    try:
        cp = run([sys.executable, str(MANIFEST_TOOL), *args], capture=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise InstallerError(f"manifest resolver failed: {detail}") from exc
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise InstallerError("manifest resolver returned invalid JSON") from exc


def load_lifecycle() -> dict:
    try:
        data = json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(f"cannot read lifecycle registry: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise InstallerError("unsupported installer/lifecycle.json schema")
    return data


def all_manifests() -> dict[int, dict]:
    raw = manifest_json("list", "--json")
    if not isinstance(raw, list):
        raise InstallerError("manifest list is not an array")
    return {int(item["id"]): item for item in raw}


def resolve_requested(selectors: list[str], manifests: dict[int, dict]) -> list[int]:
    if selectors == ["all"]:
        return sorted(manifests)
    if "all" in selectors:
        raise InstallerError("all cannot be combined with explicit stack selectors")

    by_directory = {data["directory"]: sid for sid, data in manifests.items()}
    requested: list[int] = []
    seen: set[int] = set()

    for token in selectors:
        if token.isdigit():
            sid = int(token)
        elif token.startswith("stack") and token[5:].isdigit():
            sid = int(token[5:])
        elif token in by_directory:
            sid = by_directory[token]
        else:
            raise InstallerError(f"unknown stack selector: {token}")

        if sid not in manifests:
            raise InstallerError(f"unknown stack selector: {token}")
        if sid not in seen:
            requested.append(sid)
            seen.add(sid)

    return requested


def resolve_plan(selectors: list[str], target: bool) -> list[int]:
    args = ["plan", *selectors, "--json"]
    if target:
        args.append("--target")
    raw = manifest_json(*args)
    if not isinstance(raw, list) or not all(isinstance(v, int) for v in raw):
        raise InstallerError("manifest plan is invalid")
    return raw


def validate_registry(manifests: dict[int, dict], lifecycle: dict) -> None:
    entries = lifecycle["stacks"]
    expected = {str(sid) for sid in manifests}
    if set(entries) != expected:
        raise InstallerError("lifecycle registry stack ids do not exactly match manifests")

    for sid, manifest in manifests.items():
        entry = entries[str(sid)]
        if entry.get("directory") != manifest["directory"]:
            raise InstallerError(f"stack{sid}: lifecycle directory disagrees with manifest")

        owned_containers = {
            value.split(":", 1)[1]
            for value in manifest.get("owns", [])
            if value.startswith("container:")
        }
        required_containers = entry.get("required_containers")
        if not isinstance(required_containers, list) or not all(
            isinstance(name, str) and name for name in required_containers
        ):
            raise InstallerError(f"stack{sid}: invalid required_containers registry")
        if not set(required_containers).issubset(owned_containers):
            raise InstallerError(f"stack{sid}: required_containers must be owned by the stack")

        for phase in ("prepare", "deploy", "reconcile", "verify"):
            commands = entry.get(phase, [])
            if not isinstance(commands, list) or not all(
                isinstance(command, list)
                and command
                and all(isinstance(value, str) and value for value in command)
                for command in commands
            ):
                raise InstallerError(f"stack{sid}: invalid {phase} command registry")

        for phase in ("prepare", "deploy", "reconcile", "verify"):
            for command in entry[phase]:
                if command[0].startswith("./"):
                    script = ROOT / manifest["directory"] / command[0][2:]
                    if not script.is_file():
                        raise InstallerError(f"stack{sid}: lifecycle script missing: {script}")


def stack_prepared(directory: str) -> bool:
    return (ROOT / directory / ".lock").is_file()


def container_state(name: str) -> str:
    if shutil.which("docker") is None:
        return "unknown-no-docker"
    cp = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
            name,
        ],
        capture=True,
        check=False,
    )
    if cp.returncode != 0:
        return "absent"
    status, _, health = cp.stdout.strip().partition("|")
    if health:
        return f"{status}/{health}"
    return status or "unknown"


def is_running(state: str) -> bool:
    return state == "running" or state.startswith("running/")


def is_runtime_healthy(state: str) -> bool:
    return state in {"running", "running/healthy"}


def stack_state(manifest: dict) -> dict:
    containers = [
        value.split(":", 1)[1]
        for value in manifest.get("owns", [])
        if value.startswith("container:")
    ]
    return {
        "prepared": stack_prepared(manifest["directory"]),
        "containers": {name: container_state(name) for name in containers},
    }


def deployment_ready(entry: dict, state: dict) -> bool:
    return all(
        is_running(state["containers"].get(name, "absent"))
        for name in entry["required_containers"]
    )


def state_transition_ids(
    plan: list[int],
    states: dict[int, dict],
    lifecycle: dict,
) -> set[int]:
    """Stacks whose installer run will change PREPARED or DEPLOYED state."""
    changed: set[int] = set()
    for sid in plan:
        entry = lifecycle["stacks"][str(sid)]
        state = states[sid]
        if not state["prepared"] or not deployment_ready(entry, state):
            changed.add(sid)
    return changed


def reconciliation_targets(
    requested: list[int],
    plan: list[int],
    changed_stack_ids: set[int],
    manifests: dict[int, dict],
    lifecycle: dict,
    *,
    force_reconcile: bool,
) -> list[int]:
    """Return prepared consumers that need reconciliation after this run.

    Requesting an already-stable provider is not a capability change. A consumer
    is reconciled automatically only when this installer run prepares/deploys a
    provider it consumes, or when the consumer itself is prepared/deployed. The
    operator may explicitly force reconciliation with --reconcile.
    """
    targets: set[int] = set()

    if force_reconcile:
        for sid in requested:
            if lifecycle["stacks"][str(sid)]["reconcile"]:
                if sid in plan or stack_prepared(manifests[sid]["directory"]):
                    targets.add(sid)

    for sid in requested:
        if sid in changed_stack_ids and lifecycle["stacks"][str(sid)]["reconcile"]:
            targets.add(sid)

    changed_capabilities: set[str] = set()
    for sid in changed_stack_ids:
        changed_capabilities.update(manifests[sid].get("provides", []))

    if changed_capabilities:
        for sid, manifest in manifests.items():
            if not lifecycle["stacks"][str(sid)]["reconcile"]:
                continue
            if sid not in plan and not stack_prepared(manifest["directory"]):
                continue
            optional_consumes = set(manifest.get("optional_consumes", []))
            if optional_consumes & changed_capabilities:
                targets.add(sid)

    return sorted(targets)


def add_commands(
    actions: list[Action],
    sid: int,
    manifest: dict,
    phase: str,
    commands: list[list[str]],
    reason: str,
) -> None:
    for command in commands:
        actions.append(Action(sid, manifest["directory"], phase, tuple(command), reason))


def build_actions(
    requested: list[int],
    plan: list[int],
    manifests: dict[int, dict],
    lifecycle: dict,
    *,
    force_reconcile: bool = False,
) -> tuple[list[Action], list[int], set[int]]:
    actions: list[Action] = []
    states = {sid: stack_state(manifests[sid]) for sid in plan}
    changed_stack_ids = state_transition_ids(plan, states, lifecycle)

    for sid in plan:
        manifest = manifests[sid]
        entry = lifecycle["stacks"][str(sid)]
        state = states[sid]

        if not state["prepared"]:
            add_commands(
                actions,
                sid,
                manifest,
                "prepare",
                entry["prepare"],
                "stack is not PREPARED",
            )

        if not deployment_ready(entry, state):
            add_commands(
                actions,
                sid,
                manifest,
                "deploy",
                entry["deploy"],
                "one or more required containers are not running",
            )

    reconcile_ids = reconciliation_targets(
        requested,
        plan,
        changed_stack_ids,
        manifests,
        lifecycle,
        force_reconcile=force_reconcile,
    )
    for sid in reconcile_ids:
        manifest = manifests[sid]
        entry = lifecycle["stacks"][str(sid)]
        reason = (
            "operator requested explicit reconciliation"
            if force_reconcile and sid in requested and sid not in changed_stack_ids
            else "installer state transition changes capabilities consumed by this stack"
        )
        add_commands(actions, sid, manifest, "reconcile", entry["reconcile"], reason)

    verify_ids = list(plan)
    for sid in reconcile_ids:
        if sid not in verify_ids:
            verify_ids.append(sid)

    for sid in verify_ids:
        manifest = manifests[sid]
        entry = lifecycle["stacks"][str(sid)]
        add_commands(
            actions,
            sid,
            manifest,
            "verify",
            entry["verify"],
            "validate stack-owned contract",
        )

    return actions, reconcile_ids, changed_stack_ids


def preflight(execute_mode: bool) -> None:
    if not MANIFEST_TOOL.is_file() or not LIFECYCLE_FILE.is_file():
        raise InstallerError("installer files are incomplete")
    if execute_mode and os.geteuid() != 0:
        raise InstallerError("execution requires root; --plan and --dry-run do not")
    if execute_mode:
        if not (ROOT / ".env").is_file():
            raise InstallerError(f"missing operational environment: {ROOT / '.env'}")
        if shutil.which("docker") is None:
            raise InstallerError("docker is not installed")
        run(["docker", "compose", "version"], capture=True)


def print_plan(
    selectors: list[str],
    plan: list[int],
    manifests: dict[int, dict],
    lifecycle: dict,
    actions: list[Action],
    reconcile_ids: list[int],
    changed_stack_ids: set[int],
) -> None:
    print("Requested:", " ".join(selectors))
    print("Resolved dependency plan:")
    for sid in plan:
        state = stack_state(manifests[sid])
        prepared = "PREPARED" if state["prepared"] else "ABSENT/UNPREPARED"
        containers = ", ".join(
            f"{name}={value}" for name, value in state["containers"].items()
        ) or "no owned containers"
        ready = "DEPLOYED" if deployment_ready(lifecycle["stacks"][str(sid)], state) else "NOT-DEPLOYED"
        transition = "; WILL-CHANGE" if sid in changed_stack_ids else ""
        print(f"  {sid}: {manifests[sid]['directory']} [{prepared}; {ready}{transition}; {containers}]")

    if reconcile_ids:
        print("Reconcile consumers:")
        for sid in reconcile_ids:
            suffix = " (outside dependency plan)" if sid not in plan else ""
            print(f"  {sid}: {manifests[sid]['directory']}{suffix}")

    print("Actions:")
    if not actions:
        print("  none")
    for index, action in enumerate(actions, 1):
        print(f"  {index:02d}. {action.display()}  # {action.reason}")


def execute(actions: list[Action]) -> None:
    for index, action in enumerate(actions, 1):
        print(f"\n== [{index}/{len(actions)}] {action.display()}", flush=True)
        cwd = ROOT / action.directory
        command = list(action.command)
        if command[0].startswith("./"):
            command = ["bash", command[0], *command[1:]]
        try:
            run(command, cwd=cwd)
        except subprocess.CalledProcessError as exc:
            raise InstallerError(f"failed: {action.display()} (rc={exc.returncode})") from exc


def validate_runtime(plan: list[int], manifests: dict[int, dict], lifecycle: dict) -> None:
    failures: list[str] = []
    for sid in plan:
        entry = lifecycle["stacks"][str(sid)]
        for name in entry["required_containers"]:
            state = container_state(name)
            if not is_runtime_healthy(state):
                failures.append(f"stack{sid}:{name}={state}")
    if failures:
        raise InstallerError("required runtime validation failed: " + ", ".join(failures))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manifest-driven local_hybrid_ai installer")
    parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="resolve and print plan only")
    mode.add_argument("--dry-run", action="store_true", help="print exact actions without executing them")
    parser.add_argument("--target", action="store_true", help="resolve target_requires instead of current requires")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="force reconciliation for requested stacks that own a reconcile phase",
    )
    parser.add_argument("--yes", action="store_true", help="required for real execution")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    execute_mode = not args.plan and not args.dry_run
    try:
        preflight(execute_mode)
        manifests = all_manifests()
        lifecycle = load_lifecycle()
        validate_registry(manifests, lifecycle)
        requested = resolve_requested(args.stacks, manifests)
        plan = resolve_plan(args.stacks, args.target)
        actions, reconcile_ids, changed_stack_ids = build_actions(
            requested,
            plan,
            manifests,
            lifecycle,
            force_reconcile=args.reconcile,
        )
        print_plan(
            args.stacks,
            plan,
            manifests,
            lifecycle,
            actions,
            reconcile_ids,
            changed_stack_ids,
        )

        if not execute_mode:
            print("\nNo changes made.")
            return 0
        if not args.yes:
            raise InstallerError("refusing execution without --yes; inspect --plan/--dry-run first")

        execute(actions)
        validate_runtime(plan, manifests, lifecycle)
        print("\nINSTALLER: PASS")
        return 0
    except (InstallerError, OSError, subprocess.CalledProcessError) as exc:
        print(f"INSTALLER ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
