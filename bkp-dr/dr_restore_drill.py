#!/usr/bin/env python3
"""End-to-end isolated recovery drill for a completed full backup set.

This orchestrator composes the already-qualified recovery slices without enabling
live-host restore:

1. strict restore-all planner/checksum/source preflight;
2. isolated Git source + operational .env + pre-prepare archive staging;
3. isolated managed-state reconstruction for PostgreSQL and Gitea;
4. read-only verification of declared external Git prerequisites.

The destination must be new/empty. Service drill containers are disposable,
unnamed relative to production, publish no ports, use no platform network and are
removed by the managed-state adapter. Live BASE_PATH is never a restore target.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import dr
import dr_restore_all
import dr_restore_managed
import dr_restore_stage
import dr_stack6_verify


class RestoreDrillError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreDrillResult:
    destination: Path
    source_commit: str
    checksums_verified: int
    env_restored: bool
    archives_restored: int
    postgres_tables: int
    postgres_nonempty_tables: int
    gitea_tables: int
    gitea_nonempty_tables: int
    gitea_repositories: int
    gitea_health: bool
    external_git_verified: int

    def as_dict(self) -> dict[str, object]:
        return {
            "destination": str(self.destination),
            "source_commit": self.source_commit,
            "checksums_verified": self.checksums_verified,
            "env_restored": self.env_restored,
            "archives_restored": self.archives_restored,
            "postgres_tables": self.postgres_tables,
            "postgres_nonempty_tables": self.postgres_nonempty_tables,
            "gitea_tables": self.gitea_tables,
            "gitea_nonempty_tables": self.gitea_nonempty_tables,
            "gitea_repositories": self.gitea_repositories,
            "gitea_health": self.gitea_health,
            "external_git_verified": self.external_git_verified,
            "live_runtime_modified": False,
            "ports_published": False,
            "platform_network_attached": False,
        }


def _verify_external_prerequisites(backup_set: Path, staged_env: Path) -> int:
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    count = 0
    for prerequisite in metadata.get("prerequisites", []):
        if prerequisite.get("kind") != "EXTERNAL":
            continue
        strategy = prerequisite.get("strategy")
        if strategy != "git":
            raise RestoreDrillError(f"unsupported external prerequisite strategy: {strategy}")
        # The current Git externalization contract belongs to Stack6 portable
        # memory. The verifier is read-only and intentionally does not assume
        # which Git server hosts the configured origin.
        try:
            dr_stack6_verify.verify_stack6_memory(staged_env)
        except (dr_stack6_verify.Stack6VerifyError, dr.RecoveryError, OSError) as exc:
            raise RestoreDrillError(f"external Git prerequisite verification failed: {exc}") from exc
        count += 1
    return count


def run_restore_drill(backup_set: Path, destination: Path) -> RestoreDrillResult:
    plan = dr_restore_all.plan_restore_all(backup_set)
    stage = dr_restore_stage.stage_restore_all(backup_set, destination)
    try:
        managed = dr_restore_managed.run_managed_restore(backup_set, destination)
        external = _verify_external_prerequisites(backup_set, stage.source_root / ".env")
    except Exception:
        # Preserve the isolated destination for forensic inspection. The stage
        # executor already cleans only failures that happen during its own phase;
        # later failures should leave reconstructed evidence intact.
        raise
    return RestoreDrillResult(
        destination=destination,
        source_commit=plan.source_commit,
        checksums_verified=plan.checksums_verified,
        env_restored=stage.env_restored,
        archives_restored=stage.archives_restored,
        postgres_tables=managed.postgres_tables,
        postgres_nonempty_tables=managed.postgres_nonempty_tables,
        gitea_tables=managed.gitea_tables,
        gitea_nonempty_tables=managed.gitea_nonempty_tables,
        gitea_repositories=managed.gitea_repositories,
        gitea_health=managed.gitea_health,
        external_git_verified=external,
    )
