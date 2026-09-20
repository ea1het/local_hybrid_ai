#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Atomic manifest-driven full backup-set executor.

Recovery policy comes from manifests. For `all`, deployment discovery uses the
installer lifecycle's required containers, which are validated as manifest-owned.
A stack is considered deployed if at least one required container exists; this
also catches partially stopped/broken deployments instead of silently omitting
them. Stack0 is the mandatory platform base and is always included.

The operational .env is a global sensitive artifact by ADR-0001.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import _planner as planner
from local_ai_cli.common import archive
from local_ai_cli.common import filesystem
from local_ai_cli.common import postgres
import _stack3_backup as stack3_backup
import _stack4_backup as stack4_backup

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
LIFECYCLE_FILE = PROJECT_ROOT / "src" / "local_ai_cli" / "install-lifecycle.json"
ENV_SOURCE = ROOT / ".env"
ENV_RELATIVE_PATH = "artifacts/global/operational.env"


class BackupAllError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedBackupAll:
    path: Path
    artifact_count: int
    prerequisite_count: int
    deployed_stacks: tuple[int, ...]

    def as_dict(self):
        return {
            "backup_set": str(self.path),
            "artifact_count": self.artifact_count,
            "prerequisite_count": self.prerequisite_count,
            "deployed_stacks": list(self.deployed_stacks),
            "published_atomically": True,
        }


def load_lifecycle() -> dict:
    try:
        data = json.loads(LIFECYCLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupAllError(f"cannot read installer lifecycle: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise BackupAllError("unsupported installer lifecycle contract")
    return data


def _owned_containers(manifest: dict) -> set[str]:
    return {
        value.split(":", 1)[1]
        for value in manifest.get("owns", [])
        if value.startswith("container:")
    }


def _required_containers(sid: int, manifest: dict, lifecycle: dict) -> list[str]:
    entry = lifecycle.get(str(sid))
    if not isinstance(entry, dict) or entry.get("directory") != manifest["directory"]:
        raise BackupAllError(f"stack{sid}: lifecycle/manifest mismatch")
    required = entry.get("required_containers")
    if not isinstance(required, list) or not required:
        raise BackupAllError(f"stack{sid}: cannot determine deployment without required containers")
    if not set(required).issubset(_owned_containers(manifest)):
        raise BackupAllError(f"stack{sid}: lifecycle required containers are not manifest-owned")
    return required


def _any_container_exists(required: list[str], runner) -> bool:
    for name in required:
        cp = runner(["docker", "inspect", "-f", "{{.State.Status}}", name])
        if cp.returncode == 0:
            return True
    return False


def detect_deployed_stacks(manifests: dict[int, dict], runner=planner.run_command) -> list[int]:
    lifecycle = load_lifecycle()["stacks"]
    deployed = [0]
    for sid in sorted(manifests):
        if sid == 0:
            continue
        required = _required_containers(sid, manifests[sid], lifecycle)
        if _any_container_exists(required, runner):
            deployed.append(sid)
    return deployed


def _resource_map(manifests, plan):
    return {
        (sid, resource["id"]): resource
        for sid in plan
        for resource in manifests[sid]["recovery"].get("resources", [])
    }


def _paths_overlap(first: Path, second: Path) -> bool:
    """Return True when resolved paths are equal or one contains the other."""
    first = first.resolve()
    second = second.resolve()
    return first == second or first in second.parents or second in first.parents


def validate_backup_destination(backup_root: Path, stacks_root: Path, base_path: Path) -> Path:
    """Reject destinations that overlap project source or mutable runtime trees."""
    destination = backup_root.resolve()
    protected = (
        ("STACKS_ROOT", stacks_root.resolve()),
        ("BASE_PATH", base_path.resolve()),
    )
    for label, root in protected:
        if _paths_overlap(destination, root):
            raise BackupAllError(
                f"unsafe backup destination overlaps {label}: destination={destination} protected={root}"
            )
    return destination


def _copy_private(source: Path, destination: Path):
    if not source.is_file() or source.is_symlink():
        raise BackupAllError("operational .env must resolve to a regular file")
    if source.stat().st_size <= 0:
        raise BackupAllError("operational .env is empty")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb", closefd=False) as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    finally:
        os.close(fd)
    os.chmod(destination, 0o600)
    if archive.mode_of(destination) != 0o600:
        raise BackupAllError("operational .env backup is not mode 0600")


def _artifact_metadata(artifact, path):
    return {
        "stack_id": artifact.stack_id,
        "resource_id": artifact.resource_id,
        "strategy": artifact.strategy,
        "sensitive": artifact.sensitive,
        "restore_phase": artifact.restore_phase,
        "relative_path": artifact.relative_path,
        "sha256": archive.sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _docker_output(command: list[str], label: str) -> str:
    cp = planner.run_command(command)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise BackupAllError(f"{label} failed: {detail or 'no diagnostic output'}")
    return cp.stdout.strip()


def _wait_container_ready(container: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _docker_output(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                container,
            ],
            f"container state for {container}",
        )
        try:
            status, health = state.split("|", 1)
        except ValueError as exc:
            raise BackupAllError(f"invalid Docker state for {container}: {state}") from exc
        if status == "running" and health in {"none", "healthy"}:
            return
        if status in {"exited", "dead", "removing"}:
            raise BackupAllError(f"{container} entered terminal state {status} after backup")
        time.sleep(2)
    raise BackupAllError(f"timeout waiting for {container} after backup")


def _create_archive_artifact(resource: dict, manifest: dict, base_path: Path, destination: Path) -> None:
    config = resource["config"]
    source_path = planner.expand_runtime_path(config["source"]["path"], base_path)
    quiesce = config.get("quiesce_container")
    if not quiesce:
        archive.create_tar_archive(source_path, destination)
        return

    if quiesce not in _owned_containers(manifest):
        raise BackupAllError(f"archive quiesce container is not owned by stack{manifest['id']}: {quiesce}")

    running = (
        _docker_output(
            ["docker", "inspect", "-f", "{{.State.Running}}", quiesce],
            f"inspect {quiesce}",
        )
        == "true"
    )
    stopped_by_backup = False
    archive_error: Exception | None = None
    restart_error: Exception | None = None

    if running:
        _docker_output(["docker", "stop", "--time", "30", quiesce], f"quiesce {quiesce}")
        stopped_by_backup = True

    try:
        archive.create_tar_archive(source_path, destination)
    except Exception as exc:
        archive_error = exc

    if stopped_by_backup:
        try:
            _docker_output(["docker", "start", quiesce], f"restart {quiesce}")
            _wait_container_ready(quiesce)
        except Exception as exc:
            restart_error = exc

    if archive_error is not None and restart_error is not None:
        raise BackupAllError(
            f"archive failed and {quiesce} could not be restored: {restart_error}"
        ) from archive_error
    if restart_error is not None:
        raise restart_error
    if archive_error is not None:
        raise archive_error


def _create_manifest_artifact(artifact, resource, manifest, values, base_path, destination):
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    source = resource["config"]["source"]

    if artifact.strategy == "archive":
        _create_archive_artifact(resource, manifest, base_path, destination)
        return
    if artifact.strategy == "postgres-custom-dump":
        database = postgres.validate_identifier(
            planner.require_env_value(values, source["database_env"], label="database configuration"),
            "database",
        )
        stack3_backup.create_postgres_dump(database, destination)
        return
    if artifact.strategy == "gitea-native-dump":
        members, stopped, restarted = stack4_backup.create_gitea_dump_offline(destination)
        if not stopped or not restarted:
            raise BackupAllError("Gitea controlled-offline adapter did not complete stop/restart safely")
        if not members:
            raise BackupAllError("Gitea native dump contains no members")
        return
    raise BackupAllError(f"no executing adapter registered for recovery strategy: {artifact.strategy}")


def _prepare_backup_plan():
    manifests = planner.load_manifests()
    deployed = detect_deployed_stacks(manifests)
    selectors = [str(sid) for sid in deployed]
    plan = planner.resolve_plan(selectors)
    entries = planner.build_plan_entries(plan, manifests)
    artifacts, prerequisites = planner.build_backup_plan(entries)
    resources = _resource_map(manifests, plan)
    planner.preflight_runtime_sources(manifests, plan)
    return manifests, deployed, plan, artifacts, prerequisites, resources


def _prepare_backup_destination(backup_root: Path):
    values = planner.read_dotenv_presence(ENV_SOURCE)
    base_path = planner.resolve_base_path(values)
    stacks_root = Path(planner.require_env_value(values, "STACKS_ROOT", label="STACKS_ROOT"))
    destination = validate_backup_destination(backup_root, stacks_root, base_path)
    filesystem.validate_existing_root(destination)
    return values, base_path, destination


def execute_backup_all(backup_root: Path) -> CompletedBackupAll:
    manifests, deployed, plan, artifacts, prerequisites, resources = _prepare_backup_plan()
    values, base_path, backup_root = _prepare_backup_destination(backup_root)

    created_at, final_name = archive.timestamp_parts(archive.utc_now())
    final = backup_root / final_name
    if final.exists():
        raise BackupAllError(f"final backup-set name already exists: {final}")

    temp = backup_root / f".{final_name}.tmp-{secrets.token_hex(8)}"
    old_umask = os.umask(0o077)
    try:
        archive.mkdir_private(temp)
        archive.mkdir_private(temp / "artifacts")
        archive.mkdir_private(temp / "artifacts" / "global")

        env_path = temp / ENV_RELATIVE_PATH
        _copy_private(ENV_SOURCE, env_path)
        completed = []
        for artifact in artifacts:
            resource = resources.get((artifact.stack_id, artifact.resource_id))
            if resource is None:
                raise BackupAllError(
                    f"manifest resource disappeared: stack{artifact.stack_id} {artifact.resource_id}"
                )
            path = temp / artifact.relative_path
            _create_manifest_artifact(
                artifact,
                resource,
                manifests[artifact.stack_id],
                values,
                base_path,
                path,
            )
            if not path.is_file() or path.stat().st_size <= 0:
                raise BackupAllError(
                    f"backup adapter produced missing/empty artifact: {artifact.relative_path}"
                )
            completed.append(_artifact_metadata(artifact, path))

        globals_ = [
            {
                "resource_id": "operational-env",
                "strategy": "file-copy",
                "sensitive": True,
                "restore_phase": "pre-prepare",
                "relative_path": ENV_RELATIVE_PATH,
                "sha256": archive.sha256_file(env_path),
                "size_bytes": env_path.stat().st_size,
            }
        ]
        prereq = [item.as_dict() for item in prerequisites]
        base = {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": created_at,
            "source_commit": planner.git_head(),
            "requested": ["all"],
            "resolved_stacks": plan,
            "artifacts": completed,
            "prerequisites": prereq,
        }
        archive.validate_completed_metadata(base)
        metadata = dict(base)
        metadata["global_artifacts"] = globals_
        metadata["deployed_stacks"] = deployed
        metadata.pop("deployed_stacks")

        metadata_path = temp / "backup.json"
        archive.write_private(
            metadata_path,
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(),
        )
        items = [(ENV_RELATIVE_PATH, archive.sha256_file(env_path))] + [
            (str(artifact["relative_path"]), str(artifact["sha256"]))
            for artifact in completed
        ]
        items.append(("backup.json", archive.sha256_file(metadata_path)))
        archive.write_private(
            temp / "checksums.sha256",
            "".join(f"{digest}  {path}\n" for path, digest in items).encode(),
        )
        for relative, expected in items:
            if archive.sha256_file(temp / relative) != expected:
                raise BackupAllError(f"pre-publication checksum mismatch: {relative}")
        for directory in sorted(
            [path for path in temp.rglob("*") if path.is_dir()],
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            archive.fsync_directory(directory)
        archive.fsync_directory(temp)
        archive.rename_noreplace(temp, final)
        archive.fsync_directory(backup_root)
        return CompletedBackupAll(
            final,
            len(completed) + 1,
            len(prerequisites),
            tuple(deployed),
        )
    except Exception:
        archive.cleanup_temp(temp)
        raise
    finally:
        os.umask(old_umask)
