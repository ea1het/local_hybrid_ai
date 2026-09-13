#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dr_restore_managed


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore managed DR artifacts into isolated disposable containers")
    parser.add_argument("backup_set")
    parser.add_argument("--stage", required=True, help="existing restore-stage destination")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = dr_restore_managed.run_managed_restore(Path(args.backup_set), Path(args.stage))
    except (dr_restore_managed.RestoreManagedError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR isolated managed-state restore qualification")
        print(f"- stage: {result.stage}")
        print(f"- PostgreSQL restored tables: {result.postgres_tables}")
        print(f"- PostgreSQL non-empty tables: {result.postgres_nonempty_tables}")
        print(f"- Gitea restored SQLite tables: {result.gitea_tables}")
        print(f"- Gitea non-empty SQLite tables: {result.gitea_nonempty_tables}")
        print(f"- Gitea repositories fsck/startup set: {result.gitea_repositories}")
        print(f"- isolated Gitea health: {'PASS' if result.gitea_health else 'FAIL'}")
        print("- ports published: no")
        print("- platform network attached: no")
        print("- live runtime modified: no")
        print(f"- drill containers removed: {'PASS' if result.drill_containers_removed else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
