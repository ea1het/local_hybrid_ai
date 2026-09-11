#!/usr/bin/env python3
"""Execution entry point for the atomic full backup milestone."""
from __future__ import annotations

import argparse
import json
import sys

import dr
import dr_archive
import dr_backup_all
import dr_filesystem
import dr_postgres_verify
import dr_stack3_backup
import dr_stack4_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one atomic manifest-driven full DR backup set")
    parser.add_argument("--destination", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        root, _ = dr.resolve_backup_root(args.destination)
        result = dr_backup_all.execute_backup_all(root)
    except (dr_backup_all.BackupAllError, dr.RecoveryError, dr_archive.ArchiveBackupError,
            dr_filesystem.FilesystemPreflightError, dr_postgres_verify.PostgresVerifyError,
            dr_stack3_backup.Stack3BackupError, dr_stack4_backup.Stack4BackupError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR backup all created")
        print(f"- backup set: {result.path}")
        print(f"- artifacts: {result.artifact_count}")
        print(f"- external/required prerequisites verified: {result.prerequisite_count}")
        print("- publication: atomic")
        print("- operational .env: included as sensitive global artifact (ADR-0001)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
