#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dr
import dr_restore_all
import dr_restore_live


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean-target full restore for local_hybrid_ai")
    parser.add_argument("backup_set")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-clean-target", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-clean-target", action="store_true", help="mandatory with --execute")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    backup_set = Path(args.backup_set)
    try:
        if args.check_clean_target:
            result = check_clean(backup_set)
        else:
            result = dr_restore_live.execute_restore_all(
                backup_set,
                confirm_clean_target=args.confirm_clean_target,
            ).as_dict()
    except (dr_restore_live.RestoreLiveError, dr_restore_all.RestoreAllError, dr.RecoveryError, OSError) as exc:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
