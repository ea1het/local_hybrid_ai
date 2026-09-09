#!/usr/bin/env python3
"""Common manifest-driven installer for local_hybrid_ai.

This file deliberately orchestrates stack-owned lifecycle scripts instead of
absorbing their implementation. The manifest graph is the dependency source of
truth; stack-specific deployment commands live in installer/lifecycle.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
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


def run(cmd: list[str], *, cwd: Path = ROOT, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        for phase in ("prepare", "deploy", "verify"):
            commands = entry.get(phase, [])
            if not isinstance(commands, list) or not all(
                isinstance(command, list) and command and all(isinstance(x, str) and x for x in command)
                for command in commands
            ):
                raise InstallerError(f"stack{sid}: invalid {phase} command registry")
        for command in entry.get("prepare", []) + entry.get("deploy", []) + entry.get("verify", []):
            if command[0].startswith("./"):
                script = ROOT / manifest["directory"] / command[0][2:]
                if not script.is_file():
                    raise InstallerError(f"stack{sid}: lifecycle script missing: {script}")


def stack_prepared(directory: str) -> bool:
    return (ROOT / directory / ".lock").is_file()


def container_state(name: str) -> str:
    cp = run(
        ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", name],
        capture=True,
        check=False,
    )
    if cp.returncode != 0:
        return "absent"
    status, _, health = cp.stdout.strip().partition("|")
    if health:
        return f"{status}/{health}"
    return status or "unknown"


def stack_state(manifest: dict) -> dict:
    containers = [value.split(":", 1)[1] for value in manifest.get("owns", []) if value.startswith("container:")]
    return {
        "prepared": stack_prepared(manifest["directory"]),
        "containers": {name: container_state(name) for name in containers},
    }


def build_actions(plan: list[int], manifests: dict[int, dict], lifecycle: dict) -> list[Action]:
    actions: list[Action] = []
    for sid in plan:
        manifest = manifests[sid]
        entry = lifecycle["stacks"][str(sid)]
        if not stack_prepared(manifest["directory"]):
            for command in entry["prepare"]:
                actions.append(Action(sid, manifest["directory"], "prepare", tuple(command), "stack is not PREPARED"))
        for command in entry["deploy"]:
            actions.append(Action(sid, manifest["directory"], "deploy", tuple(command), "converge requested stack to deployed state"))
        for command in entry["verify"]:
            actions.append(Action(sid, manifest["directory"], "verify", tuple(command), "validate stack-owned contract"))
    return actions


def preflight(execute: bool) -> None:
    if not MANIFEST_TOOL.is_file() or not LIFECYCLE_FILE.is_file():
        raise InstallerError("installer files are incomplete")
    if execute and os.geteuid() != 0:
        raise InstallerError("execution requires root; --plan and --dry-run do not")
    if execute:
        if not (ROOT / ".env").is_file():
            raise InstallerError(f"missing operational environment: {ROOT / '.env'}")
        run(["docker", "compose", "version"], capture=True)


def print_plan(selectors: list[str], plan: list[int], manifests: dict[int, dict], actions: list[Action]) -> None:
    print("Requested:", " ".join(selectors))
    print("Resolved dependency plan:")
    for sid in plan:
        state = stack_state(manifests[sid])
        prepared = "PREPARED" if state["prepared"] else "ABSENT/UNPREPARED"
        containers = ", ".join(f"{k}={v}" for k, v in state["containers"].items()) or "no owned containers"
        print(f"  {sid}: {manifests[sid]['directory']} [{prepared}; {containers}]")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manifest-driven local_hybrid_ai installer")
    parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="resolve and print plan only")
    mode.add_argument("--dry-run", action="store_true", help="print exact actions without executing them")
    parser.add_argument("--target", action="store_true", help="resolve target_requires instead of current requires")
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
        plan = resolve_plan(args.stacks, args.target)
        actions = build_actions(plan, manifests, lifecycle)
        print_plan(args.stacks, plan, manifests, actions)
        if not execute_mode:
            print("\nNo changes made.")
            return 0
        if not args.yes:
            raise InstallerError("refusing execution without --yes; inspect --plan/--dry-run first")
        execute(actions)
        print("\nINSTALLER: PASS")
        return 0
    except (InstallerError, OSError, subprocess.CalledProcessError) as exc:
        print(f"INSTALLER ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
