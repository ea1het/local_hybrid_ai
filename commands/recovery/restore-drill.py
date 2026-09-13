#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dr_restore_drill
import dr_restore_managed
import dr_restore_stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated end-to-end recovery drill from a completed backup set")
    parser.add_argument("backup_set")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = dr_restore_drill.run_restore_drill(Path(args.backup_set), Path(args.destination))
    except (
        dr_restore_drill.RestoreDrillError,
        dr_restore_managed.RestoreManagedError,
        dr_restore_stage.RestoreStageError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR isolated end-to-end recovery drill")
        print(f"- destination: {result.destination}")
        print(f"- source commit: {result.source_commit}")
        print(f"- checksums verified: {result.checksums_verified}")
        print(f"- operational env restored: {'PASS' if result.env_restored else 'FAIL'}")
        print(f"- pre-prepare archives restored: {result.archives_restored}")
        print(f"- LiteLLM PostgreSQL tables/non-empty: {result.postgres_tables}/{result.postgres_nonempty_tables}")
        print(f"- Gitea SQLite tables/non-empty: {result.gitea_tables}/{result.gitea_nonempty_tables}")
        print(f"- Gitea repositories: {result.gitea_repositories}")
        print(f"- isolated Gitea health: {'PASS' if result.gitea_health else 'FAIL'}")
        print(f"- external Git prerequisites verified: {result.external_git_verified}")
        print("- live runtime modified: no")
        print("- ports published: no")
        print("- platform network attached: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
