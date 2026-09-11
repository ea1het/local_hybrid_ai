#!/usr/bin/env python3
"""Atomic manifest-driven full backup-set executor.

The engine owns orchestration; stack manifests own recovery policy. Strategy
adapters create artifacts in one private temporary set and publication happens
only after every artifact, prerequisite and checksum has passed.

The operational .env is a global sensitive artifact by ADR-0001. It is not
owned by any stack and is intentionally copied verbatim without displaying it.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_archive
import dr_filesystem
import dr_postgres_verify
import dr_stack3_backup
import dr_stack4_backup

ROOT = Path(__file__).resolve().parent
ENV_SOURCE = ROOT / ".env"
ENV_RELATIVE_PATH = "artifacts/global/operational.env"


class BackupAllError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedBackupAll:
    path: Path
    artifact_count: int
    prerequisite_count: int

    def as_dict(self) -> dict[str, object]:
        return {"backup_set": str(self.path), "artifact_count": self.artifact_count,
                "prerequisite_count": self.prerequisite_count, "published_atomically": True}


def _resource_map(manifests: dict[int, dict], plan: list[int]) -> dict[tuple[int, str], dict]:
    result = {}
    for sid in plan:
        for resource in manifests[sid]["recovery"].get("resources", []):
            result[(sid, resource["id"])] = resource
    return result


def _copy_private(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise BackupAllError("operational .env must resolve to a regular file")
    if source.stat().st_size <= 0:
        raise BackupAllError("operational .env is empty")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb", closefd=False) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush(); os.fsync(dst.fileno())
    finally:
        os.close(fd)
    os.chmod(destination, 0o600)
    if dr_archive.mode_of(destination) != 0o600:
        raise BackupAllError("operational .env backup is not mode 0600")


def _artifact_metadata(a: dr.BackupArtifactPlan, path: Path) -> dict[str, object]:
    return {"stack_id": a.stack_id, "resource_id": a.resource_id, "strategy": a.strategy,
            "sensitive": a.sensitive, "restore_phase": a.restore_phase,
            "relative_path": a.relative_path, "sha256": dr_archive.sha256_file(path),
            "size_bytes": path.stat().st_size}


def _create_manifest_artifact(a: dr.BackupArtifactPlan, resource: dict,
                              values: dict[str, str], base_path: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    source = resource["config"]["source"]
    if a.strategy == "archive":
        dr_archive.create_tar_archive(dr.expand_runtime_path(source["path"], base_path), destination)
        return
    if a.strategy == "postgres-custom-dump":
        database = dr_postgres_verify.validate_identifier(
            dr.require_env_value(values, source["database_env"], label="database configuration"), "database")
        dr_stack3_backup.create_postgres_dump(database, destination)
        return
    if a.strategy == "gitea-native-dump":
        members, stopped, restarted = dr_stack4_backup.create_gitea_dump_offline(destination)
        if not stopped or not restarted:
            raise BackupAllError("Gitea controlled-offline adapter did not complete stop/restart safely")
        if not members:
            raise BackupAllError("Gitea native dump contains no members")
        return
    raise BackupAllError(f"no executing adapter registered for recovery strategy: {a.strategy}")


def execute_backup_all(backup_root: Path) -> CompletedBackupAll:
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["all"])
    entries = dr.build_plan_entries(plan, manifests)
    artifacts, prerequisites = dr.build_backup_plan(entries)
    resources = _resource_map(manifests, plan)
    dr.preflight_runtime_sources(manifests, plan)
    dr_filesystem.validate_existing_root(backup_root)
    values = dr.read_dotenv_presence(ENV_SOURCE)
    base_path = dr.resolve_base_path(values)

    created_at, final_name = dr_archive.timestamp_parts(dr_archive.utc_now())
    final = backup_root / final_name
    if final.exists():
        raise BackupAllError(f"final backup-set name already exists: {final}")
    temp = backup_root / f".{final_name}.tmp-{secrets.token_hex(8)}"
    old_umask = os.umask(0o077)
    try:
        dr_archive.mkdir_private(temp)
        dr_archive.mkdir_private(temp / "artifacts")
        dr_archive.mkdir_private(temp / "artifacts" / "global")
        env_path = temp / ENV_RELATIVE_PATH
        _copy_private(ENV_SOURCE, env_path)

        completed_artifacts = []
        for artifact in artifacts:
            resource = resources.get((artifact.stack_id, artifact.resource_id))
            if resource is None:
                raise BackupAllError(f"manifest resource disappeared: stack{artifact.stack_id} {artifact.resource_id}")
            path = temp / artifact.relative_path
            _create_manifest_artifact(artifact, resource, values, base_path, path)
            if not path.is_file() or path.stat().st_size <= 0:
                raise BackupAllError(f"backup adapter produced missing/empty artifact: {artifact.relative_path}")
            completed_artifacts.append(_artifact_metadata(artifact, path))

        global_artifacts = [{"resource_id": "operational-env", "strategy": "file-copy",
            "sensitive": True, "restore_phase": "pre-prepare", "relative_path": ENV_RELATIVE_PATH,
            "sha256": dr_archive.sha256_file(env_path), "size_bytes": env_path.stat().st_size}]
        prerequisites_metadata = [item.as_dict() for item in prerequisites]

        # Reuse the proven v1 validator for the stack-owned portion. The schema
        # separately permits global_artifacts; keeping it optional preserves
        # validation of historical backup sets.
        base_metadata = {"schema_version": 1, "kind": "local-hybrid-ai-backup-set",
            "created_at": created_at, "source_commit": dr.git_head(), "requested": ["all"],
            "resolved_stacks": plan, "artifacts": completed_artifacts,
            "prerequisites": prerequisites_metadata}
        dr_archive.validate_completed_metadata(base_metadata)
        metadata = dict(base_metadata)
        metadata["global_artifacts"] = global_artifacts

        metadata_path = temp / "backup.json"
        dr_archive.write_private(metadata_path, (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode())
        checksum_items = [(ENV_RELATIVE_PATH, dr_archive.sha256_file(env_path))]
        checksum_items += [(str(a["relative_path"]), str(a["sha256"])) for a in completed_artifacts]
        checksum_items.append(("backup.json", dr_archive.sha256_file(metadata_path)))
        dr_archive.write_private(temp / "checksums.sha256",
            "".join(f"{digest}  {relative}\n" for relative, digest in checksum_items).encode())

        for relative, expected in checksum_items:
            if dr_archive.sha256_file(temp / relative) != expected:
                raise BackupAllError(f"pre-publication checksum mismatch: {relative}")
        directories = sorted([p for p in temp.rglob("*") if p.is_dir()],
                             key=lambda p: len(p.parts), reverse=True)
        for directory in directories:
            dr_archive.fsync_directory(directory)
        dr_archive.fsync_directory(temp)
        dr_archive.rename_noreplace(temp, final)
        dr_archive.fsync_directory(backup_root)
        return CompletedBackupAll(final, len(completed_artifacts) + 1, len(prerequisites))
    except Exception:
        dr_archive.cleanup_temp(temp)
        raise
    finally:
        os.umask(old_umask)
