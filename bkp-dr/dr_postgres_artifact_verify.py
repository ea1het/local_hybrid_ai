#!/usr/bin/env python3
"""Verify a stored Stack3 PostgreSQL custom dump by isolated restore.

Unlike the older dr_postgres_verify.py milestone, this verifier consumes the
artifact already present in a completed backup set. It never creates a fresh
backup and never modifies the live LiteLLM database.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import dr
import dr_archive
import dr_postgres_verify as pg


class PostgresArtifactVerifyError(RuntimeError):
    pass


def locate_artifact(backup_set: Path) -> tuple[dict, Path]:
    metadata_path = backup_set / "backup.json"
    if not metadata_path.is_file():
        raise PostgresArtifactVerifyError("backup.json is missing")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        dr_archive.validate_completed_metadata(metadata)
    except (OSError, json.JSONDecodeError, dr_archive.ArchiveBackupError) as exc:
        raise PostgresArtifactVerifyError(f"invalid backup metadata: {exc}") from exc
    matches = [a for a in metadata.get("artifacts", []) if a.get("stack_id") == 3 and a.get("resource_id") == "litellm-database" and a.get("strategy") == "postgres-custom-dump"]
    if len(matches) != 1:
        raise PostgresArtifactVerifyError("backup set must contain exactly one Stack3 litellm-database dump")
    artifact = backup_set / matches[0]["relative_path"]
    if not artifact.is_file() or artifact.stat().st_size != matches[0]["size_bytes"]:
        raise PostgresArtifactVerifyError("stored LiteLLM dump is missing or has wrong size")
    if dr_archive.sha256_file(artifact) != matches[0]["sha256"]:
        raise PostgresArtifactVerifyError("stored LiteLLM dump SHA-256 does not match metadata")
    return matches[0], artifact


def verify_backup_set(backup_set: Path) -> dict[str, object]:
    _, dump_path = locate_artifact(backup_set)
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["3"])
    dr.preflight_runtime_sources(manifests, plan)
    values = dr.read_dotenv_presence(Path(__file__).resolve().parent / ".env")
    source_db = pg.validate_identifier(dr.require_env_value(values, "LITELLM_DB_NAME", label="LITELLM_DB_NAME"), "database")
    app_owner = pg.validate_identifier(dr.require_env_value(values, "LITELLM_DB_USER", label="LITELLM_DB_USER"), "role")
    source_tables = pg.list_user_tables(source_db)
    if not source_tables:
        raise PostgresArtifactVerifyError("source LiteLLM database contains no user tables")

    cp_list = pg.run_binary_stdin(pg.pg_restore_list_command(), dump_path)
    if cp_list.returncode != 0:
        pg.fail_command("pg_restore --list", cp_list)
    catalog_entries = len([line for line in cp_list.stdout.decode("utf-8", errors="replace").splitlines() if line and not line.startswith(";")])
    if catalog_entries <= 0:
        raise PostgresArtifactVerifyError("stored dump catalog is empty")

    import secrets
    restore_db = pg.validate_identifier("dr_restore_" + secrets.token_hex(6), "restore database")
    restore_created = False
    restored_tables: list[str] = []
    nonempty = 0
    try:
        if pg.database_exists(restore_db):
            raise PostgresArtifactVerifyError("generated restore database already exists")
        cp = pg.admin_psql("postgres", f"CREATE DATABASE {pg.quote_identifier(restore_db)} OWNER {pg.quote_identifier(app_owner)};")
        if cp.returncode != 0:
            pg.fail_command("restore database creation", cp)
        restore_created = True
        cp = pg.run_binary_stdin(pg.pg_restore_database_command(restore_db, app_owner), dump_path)
        if cp.returncode != 0:
            pg.fail_command("pg_restore", cp)
        restored_tables = pg.list_user_tables(restore_db)
        if restored_tables != source_tables:
            raise PostgresArtifactVerifyError("restored table inventory does not match live source database")
        nonempty = pg.count_nonempty_tables(restore_db, restored_tables)
    finally:
        if restore_created:
            pg.admin_psql("postgres", "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s' AND pid <> pg_backend_pid();" % restore_db)
            cp_drop = pg.admin_psql("postgres", f"DROP DATABASE {pg.quote_identifier(restore_db)};")
            if cp_drop.returncode != 0:
                pg.fail_command("restore database removal", cp_drop)
    if pg.database_exists(restore_db):
        raise PostgresArtifactVerifyError("temporary restore database still exists")
    return {
        "backup_set": str(backup_set),
        "artifact": str(dump_path),
        "dump_sha256": dr_archive.sha256_file(dump_path),
        "dump_size_bytes": dump_path.stat().st_size,
        "dump_catalog_entries": catalog_entries,
        "source_tables": len(source_tables),
        "restored_tables": len(restored_tables),
        "table_inventory_match": True,
        "restored_nonempty_tables": nonempty,
        "temporary_restore_database_removed": True,
        "live_database_modified": False,
        "container_restarted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify stored Stack3 PostgreSQL artifact by isolated restore")
    parser.add_argument("backup_set")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_backup_set(Path(args.backup_set))
    except (PostgresArtifactVerifyError, pg.PostgresVerifyError, dr.RecoveryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("DR Stack3 stored artifact isolated restore verification")
        print(f"- backup set: {result['backup_set']}")
        print(f"- dump size: {result['dump_size_bytes']} bytes")
        print(f"- dump catalog entries: {result['dump_catalog_entries']}")
        print(f"- source/restored tables: {result['source_tables']}/{result['restored_tables']}")
        print("- table inventory match: PASS")
        print(f"- restored non-empty tables: {result['restored_nonempty_tables']}")
        print("- temporary restore database removed: PASS")
        print("- live LiteLLM database modified: no")
        print("- container restarted: no")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
