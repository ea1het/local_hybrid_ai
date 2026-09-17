#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Manifest-driven disaster-recovery planning and backup-plan orchestration."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import dr_preflight

BACKUP_ROOT_ENV = dr_preflight.BACKUP_ROOT_ENV
BACKUP_SET_NAME_PATTERN = dr_preflight.BACKUP_SET_NAME_PATTERN
DEFAULT_BACKUP_ROOT = dr_preflight.DEFAULT_BACKUP_ROOT
DestinationPreflight = dr_preflight.DestinationPreflight
RecoveryError = dr_preflight.RecoveryError
RuntimeCheck = dr_preflight.RuntimeCheck
docker_state = dr_preflight.docker_state
ensure_docker_preflight = dr_preflight.ensure_docker_preflight
expand_runtime_path = dr_preflight.expand_runtime_path
gitea_help_flags = dr_preflight.gitea_help_flags
nearest_existing_parent = dr_preflight.nearest_existing_parent
owned_container = dr_preflight.owned_container
preflight_archive_source = dr_preflight.preflight_archive_source
preflight_backup_destination = dr_preflight.preflight_backup_destination
preflight_docker_service = dr_preflight.preflight_docker_service
preflight_external_config_source = dr_preflight.preflight_external_config_source
preflight_git_source = dr_preflight.preflight_git_source
preflight_gitea_source = dr_preflight.preflight_gitea_source
preflight_postgres_source = dr_preflight.preflight_postgres_source
preflight_runtime_resource = dr_preflight.preflight_runtime_resource
preflight_runtime_sources = dr_preflight.preflight_runtime_sources
read_dotenv_presence = dr_preflight.read_dotenv_presence
require_env_value = dr_preflight.require_env_value
resolve_backup_root = dr_preflight.resolve_backup_root
resolve_base_path = dr_preflight.resolve_base_path
runtime_resources = dr_preflight.runtime_resources

ROOT = Path(__file__).resolve().parent
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
BACKUP_SET_SCHEMA_VERSION = 1
ARTIFACT_EXTENSIONS = {"archive": ".tar", "postgres-custom-dump": ".dump", "gitea-native-dump": ".zip"}


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
        return {"stack_id": self.stack_id, "directory": self.directory, "stack_mode": self.stack_mode, "resource_id": self.resource_id, "resource_class": self.resource_class, "strategy": self.strategy, "sensitive": self.sensitive, "restore_phase": self.restore_phase, "disposition": self.disposition}


@dataclass(frozen=True)
class BackupArtifactPlan:
    stack_id: int
    resource_id: str
    strategy: str
    sensitive: bool
    restore_phase: str | None
    relative_path: str

    def as_dict(self) -> dict[str, object]:
        return {"stack_id": self.stack_id, "resource_id": self.resource_id, "strategy": self.strategy, "sensitive": self.sensitive, "restore_phase": self.restore_phase, "relative_path": self.relative_path}


@dataclass(frozen=True)
class BackupPrerequisitePlan:
    stack_id: int
    resource_id: str
    kind: str
    strategy: str
    sensitive: bool

    def as_dict(self) -> dict[str, object]:
        return {"stack_id": self.stack_id, "resource_id": self.resource_id, "kind": self.kind, "strategy": self.strategy, "sensitive": self.sensitive}


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def run_manifest_tool(*args: str) -> object:
    try:
        cp = subprocess.run([sys.executable, str(MANIFEST_TOOL), *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
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
    cp = run_command(["git", "rev-parse", "HEAD"])
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
            mode = recovery["contract"]["mode"]
        except (KeyError, TypeError) as exc:
            raise RecoveryError(f"stack{stack_id}: invalid recovery contract: {exc}") from exc
        resources = recovery.get("resources")
        if not resources:
            entries.append(RecoveryEntry(stack_id, manifest["directory"], mode, None, None, None, None, None, "RECONSTRUCT"))
            continue
        for resource in resources:
            resource_class, strategy = resource["class"], resource["strategy"]
            entries.append(RecoveryEntry(stack_id, manifest["directory"], mode, resource["id"], resource_class, strategy, resource["sensitive"], resource_restore_phase(resource), disposition_for(resource_class, strategy)))
    return entries


def artifact_relative_path(entry: RecoveryEntry) -> str:
    if entry.disposition != "BACKUP" or entry.resource_id is None or entry.strategy is None:
        raise RecoveryError("artifact path requested for non-backup recovery entry")
    extension = ARTIFACT_EXTENSIONS.get(entry.strategy)
    if extension is None:
        raise RecoveryError(f"strategy {entry.strategy} has no artifact extension contract")
    return f"artifacts/stack{entry.stack_id}/{entry.resource_id}{extension}"


def build_backup_plan(entries: list[RecoveryEntry]) -> tuple[list[BackupArtifactPlan], list[BackupPrerequisitePlan]]:
    artifacts: list[BackupArtifactPlan] = []
    prerequisites: list[BackupPrerequisitePlan] = []
    for entry in entries:
        if entry.disposition == "BACKUP":
            if entry.resource_id is None or entry.strategy is None or entry.sensitive is None:
                raise RecoveryError("backup entry is missing normalized recovery fields")
            artifacts.append(BackupArtifactPlan(entry.stack_id, entry.resource_id, entry.strategy, entry.sensitive, entry.restore_phase, artifact_relative_path(entry)))
        elif entry.disposition in {"REQUIRE", "EXTERNAL"}:
            if entry.resource_id is None or entry.strategy is None or entry.sensitive is None:
                raise RecoveryError("prerequisite entry is missing normalized recovery fields")
            prerequisites.append(BackupPrerequisitePlan(entry.stack_id, entry.resource_id, entry.disposition, entry.strategy, entry.sensitive))
    return artifacts, prerequisites


def backup_plan_payload(selectors: list[str], resolved_stacks: list[int], artifacts: list[BackupArtifactPlan], prerequisites: list[BackupPrerequisitePlan], *, source_commit: str, destination: DestinationPreflight, runtime_checks: list[RuntimeCheck]) -> dict[str, object]:
    return {"schema_version": BACKUP_SET_SCHEMA_VERSION, "kind": "local-hybrid-ai-backup-plan", "source_commit": source_commit, "requested": selectors, "resolved_stacks": resolved_stacks, "destination": destination.as_dict(), "runtime_preflight": [check.as_dict() for check in runtime_checks], "layout": {"metadata": "backup.json", "checksums": "checksums.sha256", "artifact_root": "artifacts/"}, "artifacts": [artifact.as_dict() for artifact in artifacts], "prerequisites": [prerequisite.as_dict() for prerequisite in prerequisites], "changes_made": False}


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
        print(f"- {prefix}: {entry.disposition} {entry.resource_id} [{entry.resource_class}; strategy={entry.strategy}; {sensitivity}{phase}]")
    print("\nNo changes made.")
    print("Planning does not access secret values, Docker runtime, or backup artifacts.")


def print_json(selectors: list[str], plan: list[int], entries: list[RecoveryEntry]) -> None:
    print(json.dumps({"schema_version": 1, "requested": selectors, "resolved_stacks": plan, "entries": [entry.as_dict() for entry in entries], "changes_made": False}, indent=2))


def print_backup_human(payload: dict[str, object]) -> None:
    print("Backup dry-run")
    print("Source commit:", payload["source_commit"])
    print("Requested:", " ".join(payload["requested"]))
    print("Resolved dependency plan:", " -> ".join(f"stack{sid}" for sid in payload["resolved_stacks"]))
    destination = payload["destination"]
    print("Destination preflight:")
    print(f"- root: {destination['root']}")
    print(f"- selected by: {destination['source']}")
    print(f"- root exists: {'yes' if destination['root_exists'] else 'no; would create during execution'}")
    print(f"- nearest existing parent: {destination['nearest_existing_parent']}")
    print(f"- writable by current user: {'yes' if destination['writable_parent'] else 'no'}")
    print(f"- backup-set directory pattern: {destination['backup_set_name_pattern']}")
    print("Runtime/source preflight:")
    for check in payload["runtime_preflight"]:
        scope = "platform" if check["stack_id"] is None else f"stack{check['stack_id']} {check['resource_id']}"
        blocking = "blocking" if check["blocking"] else "informational"
        print(f"- {scope}: {check['check']}={check['status']} [{blocking}] — {check['detail']}")
    print("Planned backup-set layout:")
    layout = payload["layout"]
    print(f"- metadata: {layout['metadata']}")
    print(f"- checksums: {layout['checksums']}")
    print(f"- artifacts: {layout['artifact_root']}")
    print("Artifacts:")
    for artifact in payload["artifacts"]:
        sensitivity = "sensitive" if artifact["sensitive"] else "non-sensitive"
        phase = f"; restore={artifact['restore_phase']}" if artifact["restore_phase"] else ""
        print(f"- stack{artifact['stack_id']} {artifact['resource_id']}: {artifact['relative_path']} [{artifact['strategy']}; {sensitivity}{phase}]")
    print("Prerequisites:")
    for prerequisite in payload["prerequisites"]:
        sensitivity = "sensitive" if prerequisite["sensitive"] else "non-sensitive"
        print(f"- stack{prerequisite['stack_id']} {prerequisite['resource_id']}: {prerequisite['kind']} [{prerequisite['strategy']}; {sensitivity}]")
    print("\nNo changes made.")
    print("Destination and runtime/source preflight are read-only; no backup artifacts were created.")
    print("Protected values were checked only for presence and were not displayed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manifest-driven disaster-recovery engine")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan", help="show effective recovery plan")
    plan_parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    plan_parser.add_argument("--target", action="store_true", help="use target dependency graph")
    plan_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    backup_parser = sub.add_parser("backup", help="plan a backup set; execution is not implemented yet")
    backup_parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    backup_parser.add_argument("--target", action="store_true", help="use target dependency graph")
    backup_parser.add_argument("--destination", help=f"backup root directory; precedence: --destination, {BACKUP_ROOT_ENV}, default {DEFAULT_BACKUP_ROOT}")
    backup_parser.add_argument("--dry-run", action="store_true", help="required in the current milestone; preflight destination/runtime and plan without writing")
    backup_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    if args.command == "backup" and not args.dry_run:
        print("ERROR: backup execution is not implemented yet; use --dry-run", file=sys.stderr)
        return 2
    try:
        manifests = load_manifests()
        plan = resolve_plan(args.stacks, target=args.target)
        entries = build_plan_entries(plan, manifests)
        if args.command == "backup":
            backup_root, destination_source = resolve_backup_root(args.destination)
            destination = preflight_backup_destination(backup_root, destination_source)
            runtime_checks = preflight_runtime_sources(manifests, plan)
            artifacts, prerequisites = build_backup_plan(entries)
            payload = backup_plan_payload(args.stacks, plan, artifacts, prerequisites, source_commit=git_head(), destination=destination, runtime_checks=runtime_checks)
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
