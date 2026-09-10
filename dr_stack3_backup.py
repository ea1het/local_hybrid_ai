#!/usr/bin/env python3
"""Real DR backup adapter for Stack3 / LiteLLM.

This milestone creates a dependency-complete backup set for requested Stack3:
- Stack0 platform PKI archive
- Stack3 LiteLLM PostgreSQL custom-format logical dump
- Stack3 LITELLM_SALT_KEY recorded only as an external prerequisite

Gitea and generic `dr.py backup all` execution remain blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_archive
import dr_filesystem
import dr_postgres_verify

ROOT = Path(__file__).resolve().parent
STACK_ID = 3
DB_RESOURCE_ID = "litellm-database"
PKI_RESOURCE_ID = "platform-pki"
DB_RELATIVE_PATH = "artifacts/stack3/litellm-database.dump"
PKI_RELATIVE_PATH = "artifacts/stack0/platform-pki.tar"


class Stack3BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedStack3Backup:
    path: Path
    pki_sha256: str
    pki_size_bytes: int
    database_sha256: str
    database_size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.path),
            "artifacts": [
                {
                    "stack_id": 0,
                    "resource_id": PKI_RESOURCE_ID,
                    "relative_path": PKI_RELATIVE_PATH,
                    "sha256": self.pki_sha256,
                    "size_bytes": self.pki_size_bytes,
                },
                {
                    "stack_id": 3,
                    "resource_id": DB_RESOURCE_ID,
                    "relative_path": DB_RELATIVE_PATH,
                    "sha256": self.database_sha256,
                    "size_bytes": self.database_size_bytes,
                },
            ],
            "live_database_modified_by_tool": False,
            "container_restarted": False,
        }


def select_resources(manifests: dict[int, dict], plan: list[int]) -> tuple[dict, dict, dict]:
    if plan != [0, 3]:
        raise Stack3BackupError(f"unexpected Stack3 dependency plan: {plan}")

    stack0_resources = manifests[0]["recovery"].get("resources", [])
    pki = [r for r in stack0_resources if r.get("id") == PKI_RESOURCE_ID and r.get("strategy") == "archive"]
    if len(pki) != 1:
        raise Stack3BackupError("Stack0 must declare exactly one platform-pki archive resource")

    stack3_resources = manifests[3]["recovery"].get("resources", [])
    database = [r for r in stack3_resources if r.get("id") == DB_RESOURCE_ID and r.get("strategy") == "postgres-custom-dump"]
    salt = [r for r in stack3_resources if r.get("id") == "litellm-salt" and r.get("strategy") == "external-config"]
    if len(database) != 1:
        raise Stack3BackupError("Stack3 must declare exactly one litellm-database postgres-custom-dump resource")
    if len(salt) != 1:
        raise Stack3BackupError("Stack3 must declare exactly one litellm-salt external-config prerequisite")
    return pki[0], database[0], salt[0]


def create_postgres_dump(database: str, destination: Path) -> None:
    dr_postgres_verify.validate_identifier(database, "database")
    command = dr_postgres_verify.docker_admin_prefix() + [
        "pg_dump",
        "-h", "127.0.0.1",
        "-U", dr_postgres_verify.ADMIN_USER,
        "-d", database,
        "--format=custom",
        "--no-owner",
        "--no-acl",
    ]
    cp = dr_postgres_verify.run_binary_to_file(command, destination)
    if cp.returncode != 0:
        dr_postgres_verify.fail_command("pg_dump", cp)
    if destination.stat().st_size <= 0:
        raise Stack3BackupError("pg_dump produced an empty artifact")

    cp_list = dr_postgres_verify.run_binary_stdin(
        dr_postgres_verify.pg_restore_list_command(),
        destination,
    )
    if cp_list.returncode != 0:
        dr_postgres_verify.fail_command("pg_restore --list", cp_list)
    catalog_entries = [
        line for line in cp_list.stdout.decode("utf-8", errors="replace").splitlines()
        if line and not line.startswith(";")
    ]
    if not catalog_entries:
        raise Stack3BackupError("custom dump catalog is empty")


def execute_stack3_backup(backup_root: Path) -> CompletedStack3Backup:
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["3"])
    pki_resource, db_resource, salt_resource = select_resources(manifests, plan)

    # Read-only runtime/source correspondence check before creating anything.
    dr.preflight_runtime_sources(manifests, plan)
    dr_filesystem.validate_existing_root(backup_root)

    values = dr.read_dotenv_presence(ROOT / ".env")
    base_path = dr.resolve_base_path(values)
    source_db = dr_postgres_verify.validate_identifier(
        dr.require_env_value(values, db_resource["config"]["source"]["database_env"], label="LiteLLM database"),
        "database",
    )
    pki_source = dr.expand_runtime_path(pki_resource["config"]["source"]["path"], base_path)

    created_at, final_name = dr_archive.timestamp_parts(dr_archive.utc_now())
    final = backup_root / final_name
    if final.exists():
        raise Stack3BackupError(f"final backup-set name already exists: {final}")

    import secrets
    temp = backup_root / f".{final_name}.tmp-{secrets.token_hex(8)}"
    old_umask = os.umask(0o077)
    try:
        dr_archive.mkdir_private(temp)
        artifacts = temp / "artifacts"
        dr_archive.mkdir_private(artifacts)
        stack0_dir = artifacts / "stack0"
        stack3_dir = artifacts / "stack3"
        dr_archive.mkdir_private(stack0_dir)
        dr_archive.mkdir_private(stack3_dir)

        pki_path = temp / PKI_RELATIVE_PATH
        db_path = temp / DB_RELATIVE_PATH

        dr_archive.create_tar_archive(pki_source, pki_path)
        create_postgres_dump(source_db, db_path)

        pki_hash = dr_archive.sha256_file(pki_path)
        db_hash = dr_archive.sha256_file(db_path)
        pki_size = pki_path.stat().st_size
        db_size = db_path.stat().st_size

        metadata = {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": created_at,
            "source_commit": dr.git_head(),
            "requested": ["3"],
            "resolved_stacks": plan,
            "artifacts": [
                {
                    "stack_id": 0,
                    "resource_id": PKI_RESOURCE_ID,
                    "strategy": "archive",
                    "sensitive": bool(pki_resource["sensitive"]),
                    "restore_phase": pki_resource["config"].get("restore", {}).get("phase"),
                    "relative_path": PKI_RELATIVE_PATH,
                    "sha256": pki_hash,
                    "size_bytes": pki_size,
                },
                {
                    "stack_id": 3,
                    "resource_id": DB_RESOURCE_ID,
                    "strategy": "postgres-custom-dump",
                    "sensitive": bool(db_resource["sensitive"]),
                    "restore_phase": db_resource["config"].get("restore", {}).get("phase"),
                    "relative_path": DB_RELATIVE_PATH,
                    "sha256": db_hash,
                    "size_bytes": db_size,
                },
            ],
            "prerequisites": [
                {
                    "stack_id": 3,
                    "resource_id": salt_resource["id"],
                    "kind": "REQUIRE",
                    "strategy": "external-config",
                    "sensitive": bool(salt_resource["sensitive"]),
                }
            ],
        }
        dr_archive.validate_completed_metadata(metadata)

        metadata_path = temp / "backup.json"
        dr_archive.write_private(
            metadata_path,
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        metadata_hash = dr_archive.sha256_file(metadata_path)

        checksums_path = temp / "checksums.sha256"
        checksum_text = (
            f"{pki_hash}  {PKI_RELATIVE_PATH}\n"
            f"{db_hash}  {DB_RELATIVE_PATH}\n"
            f"{metadata_hash}  backup.json\n"
        ).encode("utf-8")
        dr_archive.write_private(checksums_path, checksum_text)

        # All integrity checks happen before publication. Publication is the
        # terminal commit point: no fallible verification is performed after it.
        for relative, expected in (
            (PKI_RELATIVE_PATH, pki_hash),
            (DB_RELATIVE_PATH, db_hash),
            ("backup.json", metadata_hash),
        ):
            if dr_archive.sha256_file(temp / relative) != expected:
                raise Stack3BackupError(f"pre-publication checksum mismatch: {relative}")

        for directory in (stack0_dir, stack3_dir, artifacts, temp):
            dr_archive.fsync_directory(directory)

        dr_archive.rename_noreplace(temp, final)
        dr_archive.fsync_directory(backup_root)

        return CompletedStack3Backup(
            path=final,
            pki_sha256=pki_hash,
            pki_size_bytes=pki_size,
            database_sha256=db_hash,
            database_size_bytes=db_size,
        )
    except Exception:
        dr_archive.cleanup_temp(temp)
        raise
    finally:
        os.umask(old_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a real dependency-complete Stack3 DR backup set")
    parser.add_argument("stack", choices=["3"])
    parser.add_argument("--destination", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        root, _ = dr.resolve_backup_root(args.destination)
        result = execute_stack3_backup(root)
    except (Stack3BackupError, dr.RecoveryError, dr_archive.ArchiveBackupError, dr_postgres_verify.PostgresVerifyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR Stack3 backup created")
        print(f"- backup set: {result.path}")
        print(f"- Stack0 PKI: {result.pki_size_bytes} bytes")
        print(f"- Stack3 database: {result.database_size_bytes} bytes")
        print("- LITELLM_SALT_KEY: required external prerequisite; value not copied")
        print("- live LiteLLM database modified by tool: no")
        print("- container restarted: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
