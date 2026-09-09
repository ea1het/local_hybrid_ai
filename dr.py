#!/usr/bin/env python3
"""Manifest-driven disaster-recovery planner for local_hybrid_ai.

Phase 1 intentionally implements planning only. It reads the normalized recovery
contracts already validated by stack0_-_platform/manifests.py and produces the
effective recovery plan without touching Docker, runtime state, secrets, backup
artifacts, or application services.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryEntry:
    stack_id: int
    directory: str
    stack_mode: str
    resource_id: str | None
    resource_class: str | None
    strategy: str | None
    sensitive: bool | None
    restore_phase: str | None
    disposition: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "directory": self.directory,
            "stack_mode": self.stack_mode,
            "resource_id": self.resource_id,
            "resource_class": self.resource_class,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
            "restore_phase": self.restore_phase,
            "disposition": self.disposition,
        }


def run_manifest_tool(*args: str) -> object:
    try:
        cp = subprocess.run(
            [sys.executable, str(MANIFEST_TOOL), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RecoveryError(f"manifest resolver failed: {detail}") from exc

    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RecoveryError("manifest resolver returned invalid JSON") from exc


def load_manifests() -> dict[int, dict]:
    raw = run_manifest_tool("list", "--json")
    if not isinstance(raw, list):
        raise RecoveryError("manifest list is not an array")
    manifests: dict[int, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise RecoveryError("manifest list contains an invalid entry")
        manifests[item["id"]] = item
    return manifests


def resolve_plan(selectors: list[str], *, target: bool = False) -> list[int]:
    args = ["plan", *selectors, "--json"]
    if target:
        args.append("--target")
    raw = run_manifest_tool(*args)
    if not isinstance(raw, list) or not all(isinstance(value, int) for value in raw):
        raise RecoveryError("manifest dependency plan is invalid")
    return raw


def disposition_for(resource_class: str, strategy: str) -> str:
    if resource_class == "externalized":
        return "EXTERNAL"
    if strategy == "external-config":
        return "REQUIRE"
    return "BACKUP"


def resource_restore_phase(resource: dict) -> str | None:
    config = resource.get("config", {})
    if not isinstance(config, dict):
        return None
    restore = config.get("restore")
    if not isinstance(restore, dict):
        return None
    phase = restore.get("phase")
    return phase if isinstance(phase, str) else None


def build_plan_entries(plan: list[int], manifests: dict[int, dict]) -> list[RecoveryEntry]:
    entries: list[RecoveryEntry] = []

    for stack_id in plan:
        try:
            manifest = manifests[stack_id]
            recovery = manifest["recovery"]
            contract = recovery["contract"]
            mode = contract["mode"]
        except (KeyError, TypeError) as exc:
            raise RecoveryError(f"stack{stack_id}: invalid recovery contract: {exc}") from exc

        resources = recovery.get("resources")
        if not resources:
            entries.append(
                RecoveryEntry(
                    stack_id=stack_id,
                    directory=manifest["directory"],
                    stack_mode=mode,
                    resource_id=None,
                    resource_class=None,
                    strategy=None,
                    sensitive=None,
                    restore_phase=None,
                    disposition="RECONSTRUCT",
                )
            )
            continue

        for resource in resources:
            resource_class = resource["class"]
            strategy = resource["strategy"]
            entries.append(
                RecoveryEntry(
                    stack_id=stack_id,
                    directory=manifest["directory"],
                    stack_mode=mode,
                    resource_id=resource["id"],
                    resource_class=resource_class,
                    strategy=strategy,
                    sensitive=resource["sensitive"],
                    restore_phase=resource_restore_phase(resource),
                    disposition=disposition_for(resource_class, strategy),
                )
            )

    return entries


def print_human(selectors: list[str], plan: list[int], entries: list[RecoveryEntry]) -> None:
    print("Requested:", " ".join(selectors))
    print("Resolved dependency plan:", " -> ".join(f"stack{sid}" for sid in plan))
    print("Recovery plan:")

    for entry in entries:
        prefix = f"stack{entry.stack_id} {entry.directory}"
        if entry.disposition == "RECONSTRUCT":
            print(f"- {prefix}: RECONSTRUCT (mode={entry.stack_mode}; no recovery artifact)")
            continue

        sensitivity = "sensitive" if entry.sensitive else "non-sensitive"
        phase = f"; restore={entry.restore_phase}" if entry.restore_phase else ""
        print(
            f"- {prefix}: {entry.disposition} {entry.resource_id} "
            f"[{entry.resource_class}; strategy={entry.strategy}; {sensitivity}{phase}]"
        )

    print()
    print("No changes made.")
    print("Planning does not access secret values, Docker runtime, or backup artifacts.")


def print_json(selectors: list[str], plan: list[int], entries: list[RecoveryEntry]) -> None:
    payload = {
        "schema_version": 1,
        "requested": selectors,
        "resolved_stacks": plan,
        "entries": [entry.as_dict() for entry in entries],
        "changes_made": False,
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manifest-driven disaster-recovery planner (planning only)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="show effective recovery plan")
    plan_parser.add_argument(
        "stacks",
        nargs="+",
        help="stack ids, stackN, directory names, or all",
    )
    plan_parser.add_argument(
        "--target",
        action="store_true",
        help="use target dependency graph",
    )
    plan_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    args = parser.parse_args()

    try:
        manifests = load_manifests()
        plan = resolve_plan(args.stacks, target=args.target)
        entries = build_plan_entries(plan, manifests)
    except RecoveryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print_json(args.stacks, plan, entries)
    else:
        print_human(args.stacks, plan, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
