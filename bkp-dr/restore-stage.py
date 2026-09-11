#!/usr/bin/env python3
"""CLI for isolated filesystem staging of a full recovery point."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dr_restore_stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage non-service restore phases into an isolated filesystem target")
    parser.add_argument("backup_set", help="completed full backup-set directory")
    parser.add_argument("--destination", required=True, help="absolute empty directory used only for isolated staging")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = dr_restore_stage.stage_restore_all(Path(args.backup_set), Path(args.destination))
    except (dr_restore_stage.RestoreStageError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("Restore-all isolated filesystem stage: PASS")
        print(f"- destination: {result.destination}")
        print(f"- source commit: {result.source_commit}")
        print(f"- source tree: {result.source_root}")
        print(f"- runtime tree: {result.runtime_root}")
        print(f"- operational .env restored: {'PASS' if result.env_restored else 'FAIL'}")
        print(f"- external-config prerequisites verified: {result.external_config_verified}")
        print(f"- pre-prepare archives restored: {result.archives_restored}")
        print("- live runtime modified: no")
        print("- containers modified: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
