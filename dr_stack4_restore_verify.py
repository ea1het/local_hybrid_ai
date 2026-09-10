#!/usr/bin/env python3
"""Isolated restore verification for a completed Stack4 Gitea backup set.

The verifier never restores into the live Gitea runtime. It:
- validates backup metadata/checksums and ZIP integrity;
- safely extracts the native Gitea dump into a private temporary directory;
- imports gitea-db.sql into a brand-new temporary SQLite database;
- verifies the imported database contains user tables and data;
- runs `git fsck --full --no-dangling` on every restored bare repository;
- removes the complete temporary restore tree afterwards.

This proves the durable database and Git repositories can be reconstructed from
the stored backup artifact without modifying or restarting the live service.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import dr_archive
import dr_stack4_backup
import dr_stack4_inspect

MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024


class Stack4RestoreVerifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreVerification:
    backup_set: Path
    zip_members: int
    sqlite_tables: int
    sqlite_nonempty_tables: int
    repositories: int
    repositories_fsck_passed: int
    temporary_restore_removed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.backup_set),
            "zip_members": self.zip_members,
            "sqlite_tables": self.sqlite_tables,
            "sqlite_nonempty_tables": self.sqlite_nonempty_tables,
            "repositories": self.repositories,
            "repositories_fsck_passed": self.repositories_fsck_passed,
            "database_import": "PASS",
            "repository_integrity": "PASS",
            "temporary_restore_removed": self.temporary_restore_removed,
            "live_gitea_runtime_modified": False,
            "live_gitea_container_restarted": False,
        }


def safe_zip_kind(info: zipfile.ZipInfo) -> str:
    mode = (info.external_attr >> 16) & 0xFFFF
    if info.is_dir() or info.filename.endswith("/"):
        return "directory"
    if mode and stat.S_ISLNK(mode):
        raise Stack4RestoreVerifyError("Gitea dump contains a symbolic link; isolated verifier fails closed")
    if mode and not stat.S_ISREG(mode):
        raise Stack4RestoreVerifyError("Gitea dump contains a non-regular special file")
    return "file"


def safe_extract_gitea_dump(archive_path: Path, destination: Path) -> list[str]:
    names = dr_stack4_backup.validate_gitea_dump(archive_path)
    total = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            dr_stack4_backup.validate_zip_member(info.filename)
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise Stack4RestoreVerifyError("Gitea dump exceeds isolated restore size limit")
            kind = safe_zip_kind(info)
            relative = PurePosixPath(info.filename)
            target = destination.joinpath(*relative.parts)
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise Stack4RestoreVerifyError("Gitea dump extraction escaped temporary root") from exc
            if kind == "directory":
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with zf.open(info, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(target, 0o600)
    return names


def restore_sqlite(sql_path: Path, sqlite_path: Path) -> tuple[int, int]:
    if not sql_path.is_file() or sql_path.stat().st_size <= 0:
        raise Stack4RestoreVerifyError("gitea-db.sql is missing or empty")
    sql = sql_path.read_text(encoding="utf-8")
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.executescript(sql)
        connection.commit()
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        if not tables:
            raise Stack4RestoreVerifyError("restored Gitea SQLite database contains no application tables")
        nonempty = 0
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            row = connection.execute(f"SELECT EXISTS(SELECT 1 FROM {quoted} LIMIT 1)").fetchone()
            if row and row[0]:
                nonempty += 1
        return len(tables), nonempty
    except sqlite3.DatabaseError as exc:
        raise Stack4RestoreVerifyError(f"Gitea SQL import failed: {exc}") from exc
    finally:
        connection.close()


def find_bare_repositories(repos_root: Path) -> list[Path]:
    if not repos_root.is_dir():
        raise Stack4RestoreVerifyError("repos/ is missing from Gitea native dump")
    repositories = sorted(path for path in repos_root.rglob("*.git") if path.is_dir() and (path / "HEAD").is_file())
    if not repositories:
        raise Stack4RestoreVerifyError("restored Gitea dump contains no Git repositories")
    return repositories


def verify_repository(repo: Path) -> None:
    cp = subprocess.run(
        ["git", "--git-dir", str(repo), "fsck", "--full", "--no-dangling"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        detail = cp.stderr.decode("utf-8", errors="replace").strip()
        if len(detail) > 1000:
            detail = detail[:1000] + "..."
        raise Stack4RestoreVerifyError(f"git fsck failed for restored repository {repo.name}: {detail or 'no diagnostic output'}")


def verify_backup_restore(backup_set: Path) -> RestoreVerification:
    metadata = dr_stack4_inspect.read_metadata(backup_set)
    dr_stack4_inspect.verify_checksums(backup_set)
    artifact = next(
        a for a in metadata["artifacts"]
        if a.get("stack_id") == 4
        and a.get("resource_id") == dr_stack4_backup.GITEA_RESOURCE_ID
        and a.get("strategy") == "gitea-native-dump"
    )
    archive_path = backup_set / artifact["relative_path"]

    temp_root = Path(tempfile.mkdtemp(prefix="local-hybrid-ai-gitea-restore-test-"))
    os.chmod(temp_root, 0o700)
    extracted = temp_root / "dump"
    extracted.mkdir(mode=0o700)
    sqlite_path = temp_root / "restored-gitea.db"
    members: list[str] = []
    table_count = 0
    nonempty_tables = 0
    repositories: list[Path] = []
    passed = 0
    try:
        members = safe_extract_gitea_dump(archive_path, extracted)
        table_count, nonempty_tables = restore_sqlite(extracted / "gitea-db.sql", sqlite_path)
        repositories = find_bare_repositories(extracted / "repos")
        for repo in repositories:
            verify_repository(repo)
            passed += 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=False)

    removed = not temp_root.exists()
    if not removed:
        raise Stack4RestoreVerifyError("temporary Gitea restore directory remains after verification")
    return RestoreVerification(
        backup_set=backup_set,
        zip_members=len(members),
        sqlite_tables=table_count,
        sqlite_nonempty_tables=nonempty_tables,
        repositories=len(repositories),
        repositories_fsck_passed=passed,
        temporary_restore_removed=removed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Stack4 Gitea backup by isolated database/repository reconstruction")
    parser.add_argument("backup_set")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_backup_restore(Path(args.backup_set))
    except (Stack4RestoreVerifyError, dr_stack4_inspect.Stack4InspectError, dr_stack4_backup.Stack4BackupError, dr_archive.ArchiveBackupError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR Stack4 Gitea isolated restore verification")
        print(f"- backup set: {result.backup_set}")
        print(f"- ZIP members restored: {result.zip_members}")
        print(f"- SQLite tables restored: {result.sqlite_tables}")
        print(f"- non-empty SQLite tables: {result.sqlite_nonempty_tables}")
        print(f"- Git repositories restored/fsck: {result.repositories}/{result.repositories_fsck_passed}")
        print("- database import: PASS")
        print("- repository integrity: PASS")
        print(f"- temporary restore removed: {'PASS' if result.temporary_restore_removed else 'FAIL'}")
        print("- live Gitea runtime modified: no")
        print("- live Gitea container restarted by restore verifier: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
