#!/usr/bin/env python3
"""Isolated filesystem staging for the generic restore-all path.

This module executes only the non-service recovery phases that can be proven
without touching the live platform:

- materialize the recorded Git source commit into a private target tree;
- restore the protected operational .env into that staged source tree;
- verify REQUIRE/external-config prerequisites from the staged .env;
- restore pre-prepare archive artifacts into an isolated runtime root.

It deliberately does not run stack PREPARE/DEPLOY, PostgreSQL restore, Gitea
restore, external Git mutation, or any operation against the live runtime.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import dr
import dr_restore_all

DIR_MODE = 0o700
FILE_MODE = 0o600


class RestoreStageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageResult:
    destination: Path
    source_root: Path
    runtime_root: Path
    source_commit: str
    env_restored: bool
    external_config_verified: int
    archives_restored: int

    def as_dict(self) -> dict[str, object]:
        return {
            "destination": str(self.destination),
            "source_root": str(self.source_root),
            "runtime_root": str(self.runtime_root),
            "source_commit": self.source_commit,
            "env_restored": self.env_restored,
            "external_config_verified": self.external_config_verified,
            "archives_restored": self.archives_restored,
            "live_runtime_modified": False,
            "containers_modified": False,
        }


def _ensure_private_empty_destination(destination: Path) -> None:
    if not destination.is_absolute():
        raise RestoreStageError("staging destination must be an absolute path")
    if destination == Path("/"):
        raise RestoreStageError("staging destination cannot be filesystem root")
    if destination.exists():
        if not destination.is_dir() or destination.is_symlink():
            raise RestoreStageError("staging destination exists but is not a real directory")
        try:
            if next(destination.iterdir(), None) is not None:
                raise RestoreStageError("staging destination must be empty")
        except OSError as exc:
            raise RestoreStageError(f"cannot inspect staging destination: {exc}") from exc
        os.chmod(destination, DIR_MODE)
    else:
        destination.mkdir(parents=True, mode=DIR_MODE)
        os.chmod(destination, DIR_MODE)
    if stat.S_IMODE(destination.stat().st_mode) != DIR_MODE:
        raise RestoreStageError("staging destination must be mode 0700")


def _safe_tar_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise RestoreStageError(f"unsafe archive member path: {name}")
    return path


def _safe_symlink_target(member_path: PurePosixPath, target: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise RestoreStageError(f"absolute symlink target is not allowed: {member_path}")
    depth = 0
    for part in member_path.parent.joinpath(target_path).parts:
        if part == ".":
            continue
        if part == "..":
            depth -= 1
        else:
            depth += 1
        if depth < 0:
            raise RestoreStageError(f"symlink escapes staging root: {member_path}")


def _extract_tar_safely(archive: Path, destination: Path, *, expected_root: str | None = None) -> int:
    destination.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    count = 0
    try:
        with tarfile.open(archive, "r:*") as tf:
            members = tf.getmembers()
            if not members:
                raise RestoreStageError("archive is empty")
            for member in members:
                rel = _safe_tar_member(member.name)
                if expected_root is not None and rel.parts[0] != expected_root:
                    raise RestoreStageError(f"archive member outside expected {expected_root} root: {member.name}")
                target = destination.joinpath(*rel.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tf.extractfile(member)
                    if source is None:
                        raise RestoreStageError(f"cannot read archive member: {member.name}")
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
                    try:
                        with os.fdopen(fd, "wb", closefd=False) as handle:
                            shutil.copyfileobj(source, handle, 1024 * 1024)
                            handle.flush()
                            os.fsync(handle.fileno())
                    finally:
                        os.close(fd)
                        source.close()
                    os.chmod(target, stat.S_IMODE(member.mode))
                elif member.issym():
                    _safe_symlink_target(rel, member.linkname)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, target)
                elif member.islnk():
                    link_rel = _safe_tar_member(member.linkname)
                    link_source = destination.joinpath(*link_rel.parts)
                    if not link_source.exists():
                        raise RestoreStageError(f"hardlink source missing: {member.name}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.link(link_source, target)
                else:
                    raise RestoreStageError(f"unsupported archive member type: {member.name}")
                count += 1
    except (OSError, tarfile.TarError) as exc:
        raise RestoreStageError(f"archive extraction failed: {exc}") from exc
    return count


def _materialize_source(commit: str, destination: Path) -> None:
    destination.mkdir(mode=DIR_MODE)
    os.chmod(destination, DIR_MODE)
    fd, tar_name = tempfile.mkstemp(prefix="restore-source-", suffix=".tar", dir=destination.parent)
    os.close(fd)
    tar_path = Path(tar_name)
    try:
        cp = subprocess.run(
            ["git", "archive", "--format=tar", "--output", str(tar_path), commit],
            cwd=dr_restore_all.PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if cp.returncode != 0:
            detail = (cp.stderr or "").strip()
            raise RestoreStageError(f"cannot materialize recorded source commit: {detail or 'git archive failed'}")
        _extract_tar_safely(tar_path, destination)
    finally:
        tar_path.unlink(missing_ok=True)


def _copy_private(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise RestoreStageError("source artifact must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb", closefd=False) as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    finally:
        os.close(fd)
    os.chmod(destination, FILE_MODE)


def stage_restore_all(backup_set: Path, destination: Path) -> StageResult:
    plan = dr_restore_all.plan_restore_all(backup_set)
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    _ensure_private_empty_destination(destination)

    source_root = destination / "source"
    runtime_root = destination / "runtime"
    runtime_root.mkdir(mode=DIR_MODE)
    os.chmod(runtime_root, DIR_MODE)

    try:
        _materialize_source(plan.source_commit, source_root)

        global_artifact = metadata["global_artifacts"][0]
        env_source = backup_set / global_artifact["relative_path"]
        staged_env = source_root / ".env"
        _copy_private(env_source, staged_env)

        values = dr.read_dotenv_presence(staged_env)
        verified_external_config = 0
        manifests = dr.load_manifests()
        resources = {
            (sid, resource["id"]): resource
            for sid in plan.resolved_stacks
            for resource in manifests[sid].get("recovery", {}).get("resources", [])
        }
        for prereq in metadata.get("prerequisites", []):
            if prereq["kind"] != "REQUIRE" or prereq["strategy"] != "external-config":
                continue
            resource = resources[(prereq["stack_id"], prereq["resource_id"])]
            key = resource["config"]["source"]["key"]
            dr.require_env_value(values, key, label=f"recovery prerequisite {prereq['resource_id']}")
            verified_external_config += 1

        archives_restored = 0
        for artifact in metadata.get("artifacts", []):
            if artifact.get("restore_phase") != "pre-prepare":
                continue
            if artifact.get("strategy") != "archive":
                raise RestoreStageError(
                    f"unsupported pre-prepare staging strategy: {artifact.get('strategy')}"
                )
            archive_path = backup_set / artifact["relative_path"]
            # v1 archive contract stores Stack0 PKI with root name 'pki'.
            member_count = _extract_tar_safely(archive_path, runtime_root / "service_-_platform", expected_root="pki")
            if member_count <= 0:
                raise RestoreStageError("pre-prepare archive restored no members")
            archives_restored += 1

        return StageResult(
            destination=destination,
            source_root=source_root,
            runtime_root=runtime_root,
            source_commit=plan.source_commit,
            env_restored=staged_env.is_file() and stat.S_IMODE(staged_env.stat().st_mode) == FILE_MODE,
            external_config_verified=verified_external_config,
            archives_restored=archives_restored,
        )
    except Exception:
        # This destination was created/validated empty by this operation. On
        # failure remove only our isolated staging content, never live runtime.
        shutil.rmtree(destination, ignore_errors=True)
        raise
