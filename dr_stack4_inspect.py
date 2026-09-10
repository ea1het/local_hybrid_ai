#!/usr/bin/env python3
"""Inspect and verify a completed Stack4 Gitea backup set without restoring it.

This verifier checks backup-set checksums, validates the Gitea native ZIP and
summarizes recoverable content categories. It never extracts into the live
runtime and never restarts containers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import dr_archive
import dr_stack4_backup


class Stack4InspectError(RuntimeError):
    pass


def read_metadata(backup_set: Path) -> dict:
    path = backup_set / "backup.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stack4InspectError("cannot read valid backup.json") from exc
    dr_archive.validate_completed_metadata(metadata)
    if metadata.get("requested") != ["4"] or metadata.get("resolved_stacks") != [0, 4]:
        raise Stack4InspectError("backup set is not a dependency-complete Stack4 backup")
    matches = [
        a for a in metadata.get("artifacts", [])
        if a.get("stack_id") == 4
        and a.get("resource_id") == dr_stack4_backup.GITEA_RESOURCE_ID
        and a.get("strategy") == "gitea-native-dump"
    ]
    if len(matches) != 1:
        raise Stack4InspectError("backup set must contain exactly one Stack4 Gitea native dump")
    return metadata


def verify_checksums(backup_set: Path) -> None:
    checksum_file = backup_set / "checksums.sha256"
    if not checksum_file.is_file():
        raise Stack4InspectError("checksums.sha256 is missing")
    lines = [line.strip() for line in checksum_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {}
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise Stack4InspectError("invalid checksums.sha256 format")
        relative = parts[1].lstrip("* ")
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise Stack4InspectError("unsafe checksum path")
        expected[relative] = parts[0]
    for relative, digest in expected.items():
        target = backup_set / relative
        if not target.is_file():
            raise Stack4InspectError(f"checksummed file is missing: {relative}")
        if dr_archive.sha256_file(target) != digest:
            raise Stack4InspectError(f"checksum mismatch: {relative}")


def classify_members(names: list[str]) -> dict[str, int]:
    counts = {
        "database_like": 0,
        "repositories_like": 0,
        "lfs_like": 0,
        "attachments_like": 0,
        "packages_like": 0,
        "custom_config_like": 0,
        "other": 0,
    }
    for name in names:
        low = name.lower()
        matched = False
        if any(token in low for token in ("gitea-db", "database", ".sql", ".db")):
            counts["database_like"] += 1
            matched = True
        if "repo" in low or low.startswith("repositories/"):
            counts["repositories_like"] += 1
            matched = True
        if "lfs" in low:
            counts["lfs_like"] += 1
            matched = True
        if "attachment" in low:
            counts["attachments_like"] += 1
            matched = True
        if "package" in low:
            counts["packages_like"] += 1
            matched = True
        if "custom" in low or "app.ini" in low:
            counts["custom_config_like"] += 1
            matched = True
        if not matched:
            counts["other"] += 1
    return counts


def inspect_backup_set(backup_set: Path) -> dict[str, object]:
    metadata = read_metadata(backup_set)
    verify_checksums(backup_set)
    artifact = next(a for a in metadata["artifacts"] if a["stack_id"] == 4)
    dump_path = backup_set / artifact["relative_path"]
    names = dr_stack4_backup.validate_gitea_dump(dump_path)
    counts = classify_members(names)
    top_levels = sorted({Path(name).parts[0] for name in names if Path(name).parts})
    return {
        "backup_set": str(backup_set),
        "gitea_dump": artifact["relative_path"],
        "zip_members": len(names),
        "top_level_entries": top_levels[:50],
        "categories": counts,
        "checksums_valid": True,
        "zip_integrity_valid": True,
        "live_runtime_modified": False,
        "container_restarted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a completed Stack4 Gitea DR backup set")
    parser.add_argument("backup_set")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect_backup_set(Path(args.backup_set))
    except (Stack4InspectError, dr_stack4_backup.Stack4BackupError, dr_archive.ArchiveBackupError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("DR Stack4 Gitea native dump inspection")
        print(f"- backup set: {result['backup_set']}")
        print(f"- ZIP members: {result['zip_members']}")
        print(f"- top-level entries: {', '.join(result['top_level_entries'])}")
        for key, value in result["categories"].items():
            print(f"- {key}: {value}")
        print("- checksums: PASS")
        print("- ZIP integrity: PASS")
        print("- live runtime modified: no")
        print("- container restarted: no")
    return 0

if __name__ == "__main__":
    sys.exit(main())
