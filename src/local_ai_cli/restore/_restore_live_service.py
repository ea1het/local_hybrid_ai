#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Importable clean-target recovery service used by public and legacy CLIs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import _planner as planner
import _restore_all as restore_all
import _restore_compat as restore_compat
import _restore_live as restore_live


class BootstrapError(RuntimeError):
    pass


def read_env_artifact(backup_set: Path, metadata: dict) -> tuple[Path, dict[str, str]]:
    matches = [
        artifact
        for artifact in metadata.get("global_artifacts", [])
        if artifact.get("resource_id") == "operational-env"
    ]
    if len(matches) != 1:
        raise restore_live.RestoreLiveError("backup set must contain exactly one operational-env global artifact")
    env_path = backup_set / matches[0]["relative_path"]
    if not env_path.is_file() or env_path.is_symlink():
        raise restore_live.RestoreLiveError("operational environment artifact is missing or invalid")
    return env_path, planner.read_dotenv_presence(env_path)


def _install_compatibility() -> tuple[object, object]:
    previous_reader = restore_live._read_env_artifact
    previous_installer = restore_live._install
    restore_live._read_env_artifact = read_env_artifact
    restore_live._install = restore_compat.install_with_readiness_compat
    return previous_reader, previous_installer


def _restore_compatibility(previous: tuple[object, object]) -> None:
    restore_live._read_env_artifact, restore_live._install = previous


def check_clean(backup_set: Path) -> dict[str, object]:
    previous = _install_compatibility()
    try:
        plan = restore_all.plan_restore_all(backup_set)
        metadata = restore_all.read_completed_backup_set(backup_set)
        manifests = planner.load_manifests()
        env_path, values = read_env_artifact(backup_set, metadata)
        stacks_root = restore_live._absolute_safe_path(values, "STACKS_ROOT")
        base_path = restore_live._absolute_safe_path(values, "BASE_PATH")
        restore_live.require_clean_target(stacks_root, base_path, manifests, list(plan.resolved_stacks))
        return {
            "backup_set": str(backup_set),
            "source_commit": plan.source_commit,
            "stacks_root": str(stacks_root),
            "base_path": str(base_path),
            "operational_env": str(env_path),
            "resolved_stacks": list(plan.resolved_stacks),
            "checksums_verified": plan.checksums_verified,
            "clean_target": True,
            "changes_made": False,
        }
    finally:
        _restore_compatibility(previous)


def validate_memory_sync_bootstrap(path: Path) -> Path:
    path = path.resolve()
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise BootstrapError("memory-sync SSH bootstrap must be an existing absolute real directory")
    for name in ("ssh_config", "id_ed25519", "known_hosts"):
        candidate = path / name
        if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_size <= 0:
            raise BootstrapError(f"memory-sync SSH bootstrap is missing a regular non-empty {name}")
    return path


def install_memory_sync_bootstrap(backup_set: Path, source: Path) -> Path:
    metadata = restore_all.read_completed_backup_set(backup_set)
    _, values = read_env_artifact(backup_set, metadata)
    base_path = restore_live._absolute_safe_path(values, "BASE_PATH")
    service = planner.require_env_value(values, "MEMORY_SYNC_SERVICE", label="MEMORY_SYNC_SERVICE")
    if not service.startswith("service_-") or "/" in service or service in {"service_-", ".", ".."}:
        raise BootstrapError("MEMORY_SYNC_SERVICE has an unsafe value")
    uid = int(planner.require_env_value(values, "HERMES_UID", label="HERMES_UID"))
    gid = int(planner.require_env_value(values, "HERMES_GID", label="HERMES_GID"))
    if uid < 1 or gid < 1:
        raise BootstrapError("HERMES_UID/HERMES_GID must be positive")
    root = base_path / service
    target = root / "ssh"
    root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or not target.is_dir() or next(target.iterdir(), None) is not None:
            raise BootstrapError("memory-sync SSH target must be absent or an empty real directory")
    else:
        target.mkdir()
    os.chown(root, uid, gid)
    os.chmod(root, 0o750)
    os.chown(target, uid, gid)
    os.chmod(target, 0o700)
    for name in ("ssh_config", "id_ed25519", "known_hosts"):
        src = source / name
        dst = target / name
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with src.open("rb") as inp, os.fdopen(fd, "wb", closefd=False) as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
        finally:
            os.close(fd)
        os.chown(dst, uid, gid)
        os.chmod(dst, 0o600)
    return target


def enable_memory_sync(backup_set: Path, result: dict[str, object]) -> None:
    metadata = restore_all.read_completed_backup_set(backup_set)
    _, values = read_env_artifact(backup_set, metadata)
    container = planner.require_env_value(values, "MEMORY_SYNC_CONTAINER", label="MEMORY_SYNC_CONTAINER")
    stacks_root = Path(str(result["stacks_root"]))
    stack_dir = stacks_root / "stack6_-_hermes"
    cp = subprocess.run(
        ["docker", "compose", "--profile", "git-memory", "up", "-d", "--build", "hermes-memory-sync"],
        cwd=stack_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        detail = ("..." + detail[-1500:]) if len(detail) > 1500 else detail
        raise BootstrapError(f"cannot re-enable Stack6 memory-sync profile: {detail or 'docker compose failed'}")
    restore_compat.wait_required_runtime(stacks_root, [6], timeout=240)
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if inspect.returncode != 0 or inspect.stdout.strip() != "true":
        raise BootstrapError("Stack6 memory-sync container is not running after profile restore")


def execute(backup_set: Path, bootstrap: Path | None = None) -> dict[str, object]:
    previous = _install_compatibility()
    try:
        if bootstrap is None:
            return restore_live.execute_restore_all(backup_set, confirm_clean_target=True).as_dict()
        source = validate_memory_sync_bootstrap(bootstrap)
        original = restore_live._restore_external_git

        def restore_external_then_bootstrap(metadata: dict, stacks_root: Path, manifests: dict[int, dict]) -> int:
            count = original(metadata, stacks_root, manifests)
            install_memory_sync_bootstrap(backup_set, source)
            return count

        restore_live._restore_external_git = restore_external_then_bootstrap
        try:
            result = restore_live.execute_restore_all(backup_set, confirm_clean_target=True).as_dict()
        finally:
            restore_live._restore_external_git = original
        enable_memory_sync(backup_set, result)
        result["memory_sync_enabled"] = True
        return result
    finally:
        _restore_compatibility(previous)
