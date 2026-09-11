#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import dr
import dr_restore_all
import dr_restore_live


class BootstrapError(RuntimeError):
    pass


def check_clean(backup_set: Path) -> dict[str, object]:
    plan = dr_restore_all.plan_restore_all(backup_set)
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    manifests = dr.load_manifests()
    env_path, values = dr_restore_live._read_env_artifact(backup_set, metadata)
    stacks_root = dr_restore_live._absolute_safe_path(values, "STACKS_ROOT")
    base_path = dr_restore_live._absolute_safe_path(values, "BASE_PATH")
    dr_restore_live.require_clean_target(stacks_root, base_path, manifests, list(plan.resolved_stacks))
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


def _validate_memory_sync_bootstrap(path: Path) -> Path:
    path = path.resolve()
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise BootstrapError("memory-sync SSH bootstrap must be an existing absolute real directory")
    for name in ("ssh_config", "id_ed25519", "known_hosts"):
        candidate = path / name
        if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_size <= 0:
            raise BootstrapError(f"memory-sync SSH bootstrap is missing a regular non-empty {name}")
    return path


def _install_memory_sync_bootstrap(backup_set: Path, source: Path) -> Path:
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    _, values = dr_restore_live._read_env_artifact(backup_set, metadata)
    base_path = dr_restore_live._absolute_safe_path(values, "BASE_PATH")
    service = dr.require_env_value(values, "MEMORY_SYNC_SERVICE", label="MEMORY_SYNC_SERVICE")
    if not service.startswith("service_-") or "/" in service or service in {"service_-", ".", ".."}:
        raise BootstrapError("MEMORY_SYNC_SERVICE has an unsafe value")
    uid = int(dr.require_env_value(values, "HERMES_UID", label="HERMES_UID"))
    gid = int(dr.require_env_value(values, "HERMES_GID", label="HERMES_GID"))
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

    modes = {"ssh_config": 0o600, "id_ed25519": 0o600, "known_hosts": 0o600}
    for name, mode in modes.items():
        src = source / name
        dst = target / name
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with src.open("rb") as inp, os.fdopen(fd, "wb", closefd=False) as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
        finally:
            os.close(fd)
        os.chown(dst, uid, gid)
        os.chmod(dst, mode)
    return target


def _execute_with_optional_bootstrap(backup_set: Path, bootstrap: Path | None) -> dict[str, object]:
    if bootstrap is None:
        return dr_restore_live.execute_restore_all(
            backup_set,
            confirm_clean_target=True,
        ).as_dict()

    source = _validate_memory_sync_bootstrap(bootstrap)
    original = dr_restore_live._restore_external_git

    def restore_external_then_bootstrap(metadata: dict, stacks_root: Path, manifests: dict[int, dict]) -> int:
        count = original(metadata, stacks_root, manifests)
        _install_memory_sync_bootstrap(backup_set, source)
        return count

    dr_restore_live._restore_external_git = restore_external_then_bootstrap
    try:
        return dr_restore_live.execute_restore_all(
            backup_set,
            confirm_clean_target=True,
        ).as_dict()
    finally:
        dr_restore_live._restore_external_git = original


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean-target full restore for local_hybrid_ai")
    parser.add_argument("backup_set")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-clean-target", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-clean-target", action="store_true", help="mandatory with --execute")
    parser.add_argument(
        "--memory-sync-ssh-bootstrap",
        default=None,
        help="external operator-owned SSH material directory (ssh_config,id_ed25519,known_hosts) used only to reprovision Stack6 memory-sync after a clean rebuild",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    backup_set = Path(args.backup_set)
    try:
        if args.check_clean_target:
            result = check_clean(backup_set)
        else:
            if not args.confirm_clean_target:
                raise dr_restore_live.RestoreLiveError("real restore requires explicit clean-target confirmation")
            bootstrap = Path(args.memory_sync_ssh_bootstrap) if args.memory_sync_ssh_bootstrap else None
            result = _execute_with_optional_bootstrap(backup_set, bootstrap)
    except (BootstrapError, dr_restore_live.RestoreLiveError, dr_restore_all.RestoreAllError, dr.RecoveryError, OSError, ValueError) as exc:
        print(f"RESTORE ALL ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.check_clean_target:
        print("RESTORE ALL CLEAN-TARGET PREFLIGHT: PASS")
        print(f"- backup set: {result['backup_set']}")
        print(f"- source commit: {result['source_commit']}")
        print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}")
        print(f"- checksums verified: {result['checksums_verified']}")
        print(f"- STACKS_ROOT: {result['stacks_root']}")
        print(f"- BASE_PATH: {result['base_path']}")
        print("- changes made: no")
    else:
        print("RESTORE ALL CLEAN TARGET: PASS")
        print(f"- backup set: {result['backup_set']}")
        print(f"- source commit: {result['source_commit']}")
        print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}")
        print(f"- LiteLLM PostgreSQL tables restored: {result['postgres_tables']}")
        print(f"- Gitea SQLite tables restored: {result['gitea_tables']}")
        print(f"- Gitea repositories restored: {result['gitea_repositories']}")
        print(f"- external Git resources restored: {result['external_git_restored']}")
        print(f"- STACKS_ROOT: {result['stacks_root']}")
        print(f"- BASE_PATH: {result['base_path']}")
        if args.memory_sync_ssh_bootstrap:
            print("- Stack6 memory-sync SSH bootstrap: reprovisioned from external operator material")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
