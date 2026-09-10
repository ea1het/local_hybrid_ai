#!/usr/bin/env python3
"""Verify a completed Stack3 DR backup set by restoring its PostgreSQL dump.

The verifier never restores into the live LiteLLM database. It creates a
throw-away database in the existing Stack3 PostgreSQL service, compares the
restored table inventory with the live source database, and removes the test DB.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

import dr
import dr_archive
import dr_postgres_verify

ROOT = Path(__file__).resolve().parent
STACK_ID = 3
RESOURCE_ID = "litellm-database"


class Stack3RestoreVerifyError(RuntimeError):
    pass


def read_metadata(backup_set: Path) -> dict:
    metadata_path = backup_set / "backup.json"
    if not metadata_path.is_file():
        raise Stack3RestoreVerifyError("backup.json is missing")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stack3RestoreVerifyError(f"cannot read backup metadata: {exc}") from exc
    dr_archive.validate_completed_metadata(metadata)
    return metadata


def verify_checksums(backup_set: Path, metadata: dict) -> None:
    checksums_path = backup_set / "checksums.sha256"
    if not checksums_path.is_file():
        raise Stack3RestoreVerifyError("checksums.sha256 is missing")

    expected: dict[str, str] = {
        artifact["relative_path"]: artifact["sha256"]
        for artifact in metadata["artifacts"]
    }
    expected["backup.json"] = dr_archive.sha256_file(backup_set / "backup.json")

    try:
        lines = checksums_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Stack3RestoreVerifyError(f"cannot read checksums.sha256: {exc}") from exc

    parsed: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise Stack3RestoreVerifyError("invalid checksums.sha256 entry")
        digest, relative = parts[0], parts[1].strip()
        parsed[relative] = digest

    if parsed != expected:
        raise Stack3RestoreVerifyError("checksums.sha256 does not match backup metadata")

    for relative, digest in expected.items():
        path = backup_set / relative
        if not path.is_file():
            raise Stack3RestoreVerifyError(f"backup file is missing: {relative}")
        if dr_archive.sha256_file(path) != digest:
            raise Stack3RestoreVerifyError(f"checksum mismatch: {relative}")


def select_database_artifact(backup_set: Path, metadata: dict) -> Path:
    matches = [
        artifact for artifact in metadata["artifacts"]
        if artifact["stack_id"] == STACK_ID
        and artifact["resource_id"] == RESOURCE_ID
        and artifact["strategy"] == "postgres-custom-dump"
    ]
    if len(matches) != 1:
        raise Stack3RestoreVerifyError("backup set must contain exactly one Stack3 LiteLLM database artifact")
    path = backup_set / matches[0]["relative_path"]
    if path.stat().st_size != matches[0]["size_bytes"]:
        raise Stack3RestoreVerifyError("database artifact size does not match backup metadata")
    return path


def verify_restore(backup_set: Path) -> dict[str, object]:
    if not backup_set.is_dir():
        raise Stack3RestoreVerifyError(f"backup set is not a directory: {backup_set}")

    metadata = read_metadata(backup_set)
    verify_checksums(backup_set, metadata)
    dump_path = select_database_artifact(backup_set, metadata)

    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["3"])
    if plan != [0, 3]:
        raise Stack3RestoreVerifyError(f"unexpected Stack3 dependency plan: {plan}")
    dr.preflight_runtime_sources(manifests, plan)

    values = dr.read_dotenv_presence(ROOT / ".env")
    source_db = dr_postgres_verify.validate_identifier(
        dr.require_env_value(values, "LITELLM_DB_NAME", label="LITELLM_DB_NAME"),
        "database",
    )
    app_owner = dr_postgres_verify.validate_identifier(
        dr.require_env_value(values, "LITELLM_DB_USER", label="LITELLM_DB_USER"),
        "role",
    )

    cp_list = dr_postgres_verify.run_binary_stdin(
        dr_postgres_verify.pg_restore_list_command(),
        dump_path,
    )
    if cp_list.returncode != 0:
        dr_postgres_verify.fail_command("pg_restore --list", cp_list)
    catalog_entries = len([
        line for line in cp_list.stdout.decode("utf-8", errors="replace").splitlines()
        if line and not line.startswith(";")
    ])
    if catalog_entries <= 0:
        raise Stack3RestoreVerifyError("custom dump catalog is empty")

    source_tables = dr_postgres_verify.list_user_tables(source_db)
    if not source_tables:
        raise Stack3RestoreVerifyError("source LiteLLM database contains no user tables")

    restore_db = dr_postgres_verify.validate_identifier(
        "dr_restore_" + secrets.token_hex(6),
        "restore database",
    )
    created = False
    restored_tables: list[str] = []
    restored_nonempty = 0

    try:
        if dr_postgres_verify.database_exists(restore_db):
            raise Stack3RestoreVerifyError("generated restore database already exists")

        create_sql = (
            f"CREATE DATABASE {dr_postgres_verify.quote_identifier(restore_db)} "
            f"OWNER {dr_postgres_verify.quote_identifier(app_owner)};"
        )
        cp_create = dr_postgres_verify.admin_psql("postgres", create_sql)
        if cp_create.returncode != 0:
            dr_postgres_verify.fail_command("restore database creation", cp_create)
        created = True

        cp_restore = dr_postgres_verify.run_binary_stdin(
            dr_postgres_verify.pg_restore_database_command(restore_db, app_owner),
            dump_path,
        )
        if cp_restore.returncode != 0:
            dr_postgres_verify.fail_command("pg_restore", cp_restore)

        restored_tables = dr_postgres_verify.list_user_tables(restore_db)
        if restored_tables != source_tables:
            raise Stack3RestoreVerifyError("restored table inventory does not match source database")
        restored_nonempty = dr_postgres_verify.count_nonempty_tables(restore_db, restored_tables)
    finally:
        if created:
            terminate_sql = (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{restore_db}' AND pid <> pg_backend_pid();"
            )
            cp_terminate = dr_postgres_verify.admin_psql("postgres", terminate_sql)
            if cp_terminate.returncode != 0:
                dr_postgres_verify.fail_command("restore database connection cleanup", cp_terminate)
            cp_drop = dr_postgres_verify.admin_psql(
                "postgres",
                f"DROP DATABASE {dr_postgres_verify.quote_identifier(restore_db)};",
            )
            if cp_drop.returncode != 0:
                dr_postgres_verify.fail_command("restore database removal", cp_drop)

    removed = not dr_postgres_verify.database_exists(restore_db)
    if not removed:
        raise Stack3RestoreVerifyError("temporary restore database still exists")

    return {
        "backup_set": str(backup_set),
        "database_artifact": str(dump_path),
        "dump_sha256": dr_archive.sha256_file(dump_path),
        "dump_size_bytes": dump_path.stat().st_size,
        "dump_catalog_entries": catalog_entries,
        "source_database": source_db,
        "application_owner": app_owner,
        "source_tables": len(source_tables),
        "restored_tables": len(restored_tables),
        "table_set_match": restored_tables == source_tables,
        "restored_nonempty_tables": restored_nonempty,
        "temporary_restore_database_removed": removed,
        "live_database_modified_by_tool": False,
        "container_restarted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify restore from a completed Stack3 DR backup set")
    parser.add_argument("backup_set")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = verify_restore(Path(args.backup_set))
    except (Stack3RestoreVerifyError, dr.RecoveryError, dr_archive.ArchiveBackupError, dr_postgres_verify.PostgresVerifyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("DR Stack3 persistent backup restore verification")
        print(f"- backup set: {result['backup_set']}")
        print(f"- dump size: {result['dump_size_bytes']} bytes")
        print(f"- dump catalog entries: {result['dump_catalog_entries']}")
        print(f"- source/restored tables: {result['source_tables']}/{result['restored_tables']}")
        print(f"- table inventory match: {'PASS' if result['table_set_match'] else 'FAIL'}")
        print(f"- restored non-empty tables: {result['restored_nonempty_tables']}")
        print(f"- temporary restore database removed: {'PASS' if result['temporary_restore_database_removed'] else 'FAIL'}")
        print("- live LiteLLM database modified by tool: no")
        print("- container restarted: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
