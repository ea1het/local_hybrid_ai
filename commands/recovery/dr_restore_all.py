#!/usr/bin/env python3
"""Manifest-driven restore-all planner and read-only preflight.

This module is deliberately non-destructive. It validates a completed full backup
set, checks every stored checksum, correlates stored artifacts/prerequisites with
current manifest recovery contracts, and emits the ordered restore phases that a
future executing restore engine must follow.

It never writes .env, runtime state, databases, Git repositories or containers.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_archive

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE_FILE = PROJECT_ROOT / "installer" / "lifecycle.json"
PHASE_ORDER = (
    "global",
    "pre-prepare",
    "prepare",
    "post-prepare-pre-deploy",
    "deploy",
    "post-deploy",
    "external",
    "verify",
)
SUPPORTED_ARTIFACT_STRATEGIES = {
    "archive",
    "postgres-custom-dump",
    "gitea-native-dump",
}
SUPPORTED_GLOBAL_STRATEGIES = {"file-copy"}
SUPPORTED_PREREQUISITE_STRATEGIES = {"external-config", "git"}


class RestoreAllError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreAction:
    phase: str
    kind: str
    stack_id: int | None
    resource_id: str | None
    strategy: str | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "kind": self.kind,
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "strategy": self.strategy,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RestorePlan:
    backup_set: Path
    source_commit: str
    resolved_stacks: tuple[int, ...]
    actions: tuple[RestoreAction, ...]
    checksums_verified: int

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "local-hybrid-ai-restore-plan",
            "backup_set": str(self.backup_set),
            "source_commit": self.source_commit,
            "resolved_stacks": list(self.resolved_stacks),
            "phase_order": list(PHASE_ORDER),
            "actions": [action.as_dict() for action in self.actions],
            "checksums_verified": self.checksums_verified,
            "changes_made": False,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RestoreAllError(f"unsafe backup-set relative path: {raw}")
    return path


def read_completed_backup_set(backup_set: Path) -> dict:
    if not backup_set.is_dir():
        raise RestoreAllError(f"backup set is not a directory: {backup_set}")
    metadata_path = backup_set / "backup.json"
    checksums_path = backup_set / "checksums.sha256"
    if not metadata_path.is_file() or not checksums_path.is_file():
        raise RestoreAllError("backup set is missing backup.json or checksums.sha256")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        dr_archive.validate_completed_metadata(metadata)
    except (OSError, json.JSONDecodeError, dr_archive.ArchiveBackupError) as exc:
        raise RestoreAllError(f"invalid completed backup metadata: {exc}") from exc
    if metadata.get("kind") != "local-hybrid-ai-backup-set":
        raise RestoreAllError("backup metadata kind is not a completed backup set")
    return metadata


def verify_checksum_index(backup_set: Path, metadata: dict) -> int:
    checksum_path = backup_set / "checksums.sha256"
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RestoreAllError(f"cannot read checksum index: {exc}") from exc
    expected: dict[str, str] = {}
    for raw in lines:
        if not raw.strip():
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise RestoreAllError("invalid checksums.sha256 format")
        relative = parts[1].lstrip("* ")
        _safe_relative(relative)
        if relative in expected:
            raise RestoreAllError(f"duplicate checksum entry: {relative}")
        expected[relative] = parts[0]

    declared = [a["relative_path"] for a in metadata.get("global_artifacts", [])]
    declared += [a["relative_path"] for a in metadata.get("artifacts", [])]
    declared += ["backup.json"]
    if set(expected) != set(declared):
        missing = sorted(set(declared) - set(expected))
        extra = sorted(set(expected) - set(declared))
        raise RestoreAllError(f"checksum index does not exactly cover declared files (missing={missing}, extra={extra})")

    for relative, digest in expected.items():
        target = backup_set / _safe_relative(relative)
        if not target.is_file() or target.is_symlink():
            raise RestoreAllError(f"checksummed backup file is missing or not regular: {relative}")
        if _sha256(target) != digest:
            raise RestoreAllError(f"checksum mismatch: {relative}")
    return len(expected)


def load_lifecycle() -> dict:
    try:
        lifecycle = json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreAllError(f"cannot read installer lifecycle: {exc}") from exc
    if lifecycle.get("schema_version") != 1 or not isinstance(lifecycle.get("stacks"), dict):
        raise RestoreAllError("unsupported installer lifecycle contract")
    return lifecycle


def _resource_map(manifests: dict[int, dict], stacks: tuple[int, ...]) -> dict[tuple[int, str], dict]:
    resources: dict[tuple[int, str], dict] = {}
    for sid in stacks:
        manifest = manifests.get(sid)
        if manifest is None:
            raise RestoreAllError(f"backup references unknown stack{sid}")
        for resource in manifest.get("recovery", {}).get("resources", []):
            resources[(sid, resource["id"])] = resource
    return resources


def validate_manifest_correspondence(metadata: dict, manifests: dict[int, dict]) -> None:
    stacks = tuple(metadata["resolved_stacks"])
    if not stacks or stacks[0] != 0 or len(set(stacks)) != len(stacks):
        raise RestoreAllError("resolved_stacks must be a unique dependency plan beginning with Stack0")
    resources = _resource_map(manifests, stacks)

    for artifact in metadata.get("artifacts", []):
        key = (artifact["stack_id"], artifact["resource_id"])
        resource = resources.get(key)
        if resource is None:
            raise RestoreAllError(f"backup artifact has no current manifest resource: stack{key[0]} {key[1]}")
        if artifact["strategy"] != resource.get("strategy"):
            raise RestoreAllError(f"strategy drift for stack{key[0]} {key[1]}")
        current_phase = dr.resource_restore_phase(resource)
        if artifact.get("restore_phase") != current_phase:
            raise RestoreAllError(f"restore-phase drift for stack{key[0]} {key[1]}")
        if artifact["strategy"] not in SUPPORTED_ARTIFACT_STRATEGIES:
            raise RestoreAllError(f"unsupported restore artifact strategy: {artifact['strategy']}")

    for prereq in metadata.get("prerequisites", []):
        key = (prereq["stack_id"], prereq["resource_id"])
        resource = resources.get(key)
        if resource is None:
            raise RestoreAllError(f"backup prerequisite has no current manifest resource: stack{key[0]} {key[1]}")
        if prereq["strategy"] != resource.get("strategy"):
            raise RestoreAllError(f"prerequisite strategy drift for stack{key[0]} {key[1]}")
        if prereq["strategy"] not in SUPPORTED_PREREQUISITE_STRATEGIES:
            raise RestoreAllError(f"unsupported restore prerequisite strategy: {prereq['strategy']}")

    globals_ = metadata.get("global_artifacts", [])
    if len(globals_) != 1:
        raise RestoreAllError("complete restore currently requires exactly one global artifact")
    global_artifact = globals_[0]
    if global_artifact.get("resource_id") != "operational-env" or global_artifact.get("strategy") not in SUPPORTED_GLOBAL_STRATEGIES:
        raise RestoreAllError("complete restore requires the operational-env file-copy global artifact")
    if global_artifact.get("restore_phase") != "pre-prepare":
        raise RestoreAllError("operational-env must restore before PREPARE")


def git_commit_available(commit: str) -> bool:
    cp = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return cp.returncode == 0


def _phase_for_artifact(artifact: dict) -> str:
    phase = artifact.get("restore_phase")
    if phase not in {"pre-prepare", "post-prepare-pre-deploy", "post-deploy"}:
        raise RestoreAllError(
            f"artifact stack{artifact['stack_id']} {artifact['resource_id']} has unsupported restore phase: {phase}"
        )
    return phase


def build_restore_actions(metadata: dict, manifests: dict[int, dict], lifecycle: dict) -> list[RestoreAction]:
    stacks = tuple(metadata["resolved_stacks"])
    entries = lifecycle["stacks"]
    for sid in stacks:
        item = entries.get(str(sid))
        if not isinstance(item, dict) or item.get("directory") != manifests[sid]["directory"]:
            raise RestoreAllError(f"stack{sid}: lifecycle/manifest mismatch")

    actions: list[RestoreAction] = [
        RestoreAction("global", "source", None, None, "git", f"make recorded source commit {metadata['source_commit']} the target source tree"),
    ]
    for global_artifact in metadata.get("global_artifacts", []):
        actions.append(
            RestoreAction("global", "global-artifact", None, global_artifact["resource_id"], global_artifact["strategy"], global_artifact["relative_path"])
        )

    for artifact in metadata.get("artifacts", []):
        if _phase_for_artifact(artifact) == "pre-prepare":
            actions.append(RestoreAction("pre-prepare", "artifact", artifact["stack_id"], artifact["resource_id"], artifact["strategy"], artifact["relative_path"]))

    for sid in stacks:
        actions.append(RestoreAction("prepare", "lifecycle", sid, None, None, f"run Stack{sid} PREPARE lifecycle"))

    for artifact in metadata.get("artifacts", []):
        if _phase_for_artifact(artifact) == "post-prepare-pre-deploy":
            actions.append(RestoreAction("post-prepare-pre-deploy", "artifact", artifact["stack_id"], artifact["resource_id"], artifact["strategy"], artifact["relative_path"]))

    for sid in stacks:
        actions.append(RestoreAction("deploy", "lifecycle", sid, None, None, f"run Stack{sid} DEPLOY/READY lifecycle"))

    for artifact in metadata.get("artifacts", []):
        if _phase_for_artifact(artifact) == "post-deploy":
            actions.append(RestoreAction("post-deploy", "artifact", artifact["stack_id"], artifact["resource_id"], artifact["strategy"], artifact["relative_path"]))

    for prerequisite in metadata.get("prerequisites", []):
        kind = prerequisite["kind"]
        if kind == "EXTERNAL":
            actions.append(RestoreAction("external", "prerequisite", prerequisite["stack_id"], prerequisite["resource_id"], prerequisite["strategy"], "verify configured externalized recovery source"))
        elif kind == "REQUIRE":
            actions.append(RestoreAction("global", "prerequisite", prerequisite["stack_id"], prerequisite["resource_id"], prerequisite["strategy"], "satisfied from restored protected operational environment; verify presence before PREPARE"))
        else:
            raise RestoreAllError(f"unsupported prerequisite kind: {kind}")

    for sid in stacks:
        actions.append(RestoreAction("verify", "lifecycle", sid, None, None, f"run Stack{sid} VERIFY/readiness lifecycle"))

    order = {phase: index for index, phase in enumerate(PHASE_ORDER)}
    actions.sort(key=lambda action: order[action.phase])
    return actions


def plan_restore_all(backup_set: Path) -> RestorePlan:
    metadata = read_completed_backup_set(backup_set)
    checksums = verify_checksum_index(backup_set, metadata)
    source_commit = metadata.get("source_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RestoreAllError("backup source_commit is invalid")
    if not git_commit_available(source_commit):
        raise RestoreAllError("recorded backup source commit is not available in the local Git object database")

    manifests = dr.load_manifests()
    validate_manifest_correspondence(metadata, manifests)
    lifecycle = load_lifecycle()
    actions = build_restore_actions(metadata, manifests, lifecycle)
    return RestorePlan(
        backup_set=backup_set,
        source_commit=source_commit,
        resolved_stacks=tuple(metadata["resolved_stacks"]),
        actions=tuple(actions),
        checksums_verified=checksums,
    )
