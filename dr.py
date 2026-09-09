#!/usr/bin/env python3
"""Manifest-driven disaster-recovery engine for local_hybrid_ai.

Current milestones:
- plan: read-only recovery classification and dependency closure.
- backup --dry-run: read-only backup-set planning and artifact layout.

No adapter executes yet. The command intentionally does not touch Docker,
runtime state, secrets, backup artifacts, or application services.
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
BACKUP_SET_SCHEMA_VERSION = 1
ARTIFACT_EXTENSIONS = {
    "archive": ".tar",
    "postgres-custom-dump": ".dump",
    "gitea-native-dump": ".zip",
}


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


@dataclass(frozen=True)
class BackupArtifactPlan:
    stack_id: int
    resource_id: str
    strategy: str
    sensitive: bool
    restore_phase: str | None
    relative_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
            "restore_phase": self.restore_phase,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True)
class BackupPrerequisitePlan:
    stack_id: int
    resource_id: str
    kind: str
    strategy: str
    sensitive: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "kind": self.kind,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
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


def git_head() -> str:
    cp = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        raise RecoveryError("cannot determine Git HEAD for backup-set provenance")
    head = cp.stdout.strip()
    if len(head) != 40:
        raise RecoveryError("unexpected Git HEAD format")
    return head


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


def artifact_relative_path(entry: RecoveryEntry) -> str:
    if entry.disposition != "BACKUP" or entry.resource_id is None or entry.strategy is None:
        raise RecoveryError("artifact path requested for non-backup recovery entry")
    extension = ARTIFACT_EXTENSIONS.get(entry.strategy)
    if extension is None:
        raise RecoveryError(f"strategy {entry.strategy} has no artifact extension contract")
    return f"artifacts/stack{entry.stack_id}/{entry.resource_id}{extension}"


def build_backup_plan(
    entries: list[RecoveryEntry],
) -> tuple[list[BackupArtifactPlan], list[BackupPrerequisitePlan]]:
    artifacts: list[BackupArtifactPlan] = []
    prerequisites: list[BackupPrerequisitePlan] = []

    for entry in entries:
        if entry.disposition == "BACKUP":
            if (
                entry.resource_id is None
                or entry.strategy is None
                or entry.sensitive is None
            ):
                raise RecoveryError("backup entry is missing normalized recovery fields")
            artifacts.append(
                BackupArtifactPlan(
                    stack_id=entry.stack_id,
                    resource_id=entry.resource_id,
                    strategy=entry.strategy,
                    sensitive=entry.sensitive,
                    restore_phase=entry.restore_phase,
                    relative_path=artifact_relative_path(entry),
                )
            )
        elif entry.disposition in {"REQUIRE", "EXTERNAL"}:
            if (
                entry.resource_id is None
                or entry.strategy is None
                or entry.sensitive is None
            ):
                raise RecoveryError("prerequisite entry is missing normalized recovery fields")
            prerequisites.append(
                BackupPrerequisitePlan(
                    stack_id=entry.stack_id,
                    resource_id=entry.resource_id,
                    kind=entry.disposition,
                    strategy=entry.strategy,
                    sensitive=entry.sensitive,
                )
            )

    return artifacts, prerequisites


def backup_plan_payload(
    selectors: list[str],
    resolved_stacks: list[int],
    artifacts: list[BackupArtifactPlan],
    prerequisites: list[BackupPrerequisitePlan],
    *,
    source_commit: str,
) -> dict[str, object]:
    return {
        "schema_version": BACKUP_SET_SCHEMA_VERSION,
        "kind": "local-hybrid-ai-backup-plan",
        "source_commit": source_commit,
        "requested": selectors,
        "resolved_stacks": resolved_stacks,
        "layout": {
            "metadata": "backup.json",
            "checksums": "checksums.sha256",
            "artifact_root": "artifacts/",
        },
        "artifacts": [artifact.as_dict() for artifact in artifacts],
        "prerequisites": [prerequisite.as_dict() for prerequisite in prerequisites],
        "changes_made": False,
    }


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


def print_backup_human(payload: dict[str, object]) -> None:
    print("Backup dry-run")
    print("Source commit:", payload["source_commit"])
    print("Requested:", " ".join(payload["requested"]))
    print(
        "Resolved dependency plan:",
        " -> ".join(f"stack{sid}" for sid in payload["resolved_stacks"]),
    )
    print("Planned backup-set layout:")
    layout = payload["layout"]
    print(f"- metadata: {layout['metadata']}")
    print(f"- checksums: {layout['checksums']}")
    print(f"- artifacts: {layout['artifact_root']}")
    print("Artifacts:")
    for artifact in payload["artifacts"]:
        sensitivity = "sensitive" if artifact["sensitive"] else "non-sensitive"
        phase = (
            f"; restore={artifact['restore_phase']}"
            if artifact["restore_phase"]
            else ""
        )
        print(
            f"- stack{artifact['stack_id']} {artifact['resource_id']}: "
            f"{artifact['relative_path']} [{artifact['strategy']}; {sensitivity}{phase}]"
        )
    print("Prerequisites:")
    for prerequisite in payload["prerequisites"]:
        sensitivity = "sensitive" if prerequisite["sensitive"] else "non-sensitive"
        print(
            f"- stack{prerequisite['stack_id']} {prerequisite['resource_id']}: "
            f"{prerequisite['kind']} [{prerequisite['strategy']}; {sensitivity}]"
        )
    print()
    print("No changes made.")
    print("No directories, metadata files, checksums, dumps, archives, or secrets were created/read.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manifest-driven disaster-recovery engine")
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

    backup_parser = sub.add_parser("backup", help="plan a backup set; execution is not implemented yet")
    backup_parser.add_argument(
        "stacks",
        nargs="+",
        help="stack ids, stackN, directory names, or all",
    )
    backup_parser.add_argument(
        "--target",
        action="store_true",
        help="use target dependency graph",
    )
    backup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="required in the current milestone; plan layout without creating artifacts",
    )
    backup_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    args = parser.parse_args()

    if args.command == "backup" and not args.dry_run:
        print(
            "ERROR: backup execution is not implemented yet; use --dry-run",
            file=sys.stderr,
        )
        return 2

    try:
        manifests = load_manifests()
        plan = resolve_plan(args.stacks, target=args.target)
        entries = build_plan_entries(plan, manifests)

        if args.command == "backup":
            artifacts, prerequisites = build_backup_plan(entries)
            payload = backup_plan_payload(
                args.stacks,
                plan,
                artifacts,
                prerequisites,
                source_commit=git_head(),
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print_backup_human(payload)
            return 0
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