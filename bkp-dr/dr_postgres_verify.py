#!/usr/bin/env python3
"""Isolated PostgreSQL DR verification for Stack3 / LiteLLM.

This milestone proves that the Stack3 logical database can be dumped with the
PostgreSQL administrator credential managed by Stack3 and restored into a
throw-away database in the same PostgreSQL service. It does not modify the
production LiteLLM database, does not create a completed backup-set and does
not restart containers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import dr

ROOT = Path(__file__).resolve().parent
STACK_ID = 3
RESOURCE_ID = "litellm-database"
SERVICE = "litellm-postgres"
ADMIN_USER = "postgres"
ADMIN_SECRET_IN_CONTAINER = "/run/secrets/postgres_admin_password"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresVerifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerificationResult:
    source_database: str
    restore_database: str
    application_owner: str
    dump_sha256: str
    dump_size_bytes: int
    dump_catalog_entries: int
    source_tables: int
    restored_tables: int
    table_set_match: bool
    restored_nonempty_tables: int
    restore_database_removed: bool
    temporary_dump_removed: bool
    live_database_modified_by_tool: bool = False
    container_restarted: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "source_database": self.source_database,
            "restore_database": self.restore_database,
            "application_owner": self.application_owner,
            "dump_sha256": self.dump_sha256,
            "dump_size_bytes": self.dump_size_bytes,
            "dump_catalog_entries": self.dump_catalog_entries,
            "source_tables": self.source_tables,
            "restored_tables": self.restored_tables,
            "table_set_match": self.table_set_match,
            "restored_nonempty_tables": self.restored_nonempty_tables,
            "restore_database_removed": self.restore_database_removed,
            "temporary_dump_removed": self.temporary_dump_removed,
            "live_database_modified_by_tool": self.live_database_modified_by_tool,
            "container_restarted": self.container_restarted,
        }


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise PostgresVerifyError(f"invalid PostgreSQL {label} identifier")
    return value


def quote_identifier(value: str) -> str:
    validate_identifier(value, "SQL")
    return '"' + value.replace('"', '""') + '"'


def docker_admin_prefix() -> list[str]:
    # -i is required because pg_restore reads the custom dump from stdin.
    # The password value never crosses the container boundary: the container
    # shell reads the Stack3-managed secret and exports it only to the child
    # PostgreSQL client process. TCP loopback forces password authentication.
    return [
        "docker", "exec", "-i", SERVICE, "sh", "-c",
        'export PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"; exec "$@"',
        "sh",
    ]


def run_text(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_binary_to_file(args: list[str], destination: Path) -> subprocess.CompletedProcess[bytes]:
    with destination.open("xb") as handle:
        cp = subprocess.run(
            args,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
        )
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(destination, 0o600)
    return cp


def run_binary_stdin(args: list[str], source: Path) -> subprocess.CompletedProcess[bytes]:
    with source.open("rb") as handle:
        return subprocess.run(
            args,
            cwd=ROOT,
            stdin=handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )


def fail_command(label: str, cp: subprocess.CompletedProcess) -> None:
    stderr = cp.stderr
    if isinstance(stderr, bytes):
        detail = stderr.decode("utf-8", errors="replace").strip()
    else:
        detail = (stderr or "").strip()
    if len(detail) > 1200:
        detail = detail[:1200] + "..."
    raise PostgresVerifyError(f"{label} failed (rc={cp.returncode}): {detail or 'no diagnostic output'}")


def admin_psql(database: str, sql: str) -> subprocess.CompletedProcess[str]:
    validate_identifier(database, "database")
    return run_text(
        docker_admin_prefix()
        + [
            "psql", "-h", "127.0.0.1", "-U", ADMIN_USER,
            "-d", database, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql,
        ]
    )


def database_exists(database: str) -> bool:
    validate_identifier(database, "database")
    cp = admin_psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{database}';")
    if cp.returncode != 0:
        fail_command("database existence check", cp)
    return cp.stdout.strip() == "1"


def list_user_tables(database: str) -> list[str]:
    sql = (
        "SELECT schemaname || '.' || tablename "
        "FROM pg_tables "
        "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
        "ORDER BY schemaname, tablename;"
    )
    cp = admin_psql(database, sql)
    if cp.returncode != 0:
        fail_command("table inventory", cp)
    return [line.strip() for line in cp.stdout.splitlines() if line.strip()]


def count_nonempty_tables(database: str, tables: list[str]) -> int:
    nonempty = 0
    for table in tables:
        if "." not in table:
            raise PostgresVerifyError("unexpected table inventory entry")
        schema, name = table.split(".", 1)
        validate_identifier(schema, "schema")
        validate_identifier(name, "table")
        sql = f"SELECT EXISTS (SELECT 1 FROM {quote_identifier(schema)}.{quote_identifier(name)} LIMIT 1)::int;"
        cp = admin_psql(database, sql)
        if cp.returncode != 0:
            fail_command("restored table data check", cp)
        if cp.stdout.strip() == "1":
            nonempty += 1
    return nonempty


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pg_restore_list_command() -> list[str]:
    return docker_admin_prefix() + ["pg_restore", "--list"]


def pg_restore_database_command(database: str, app_owner: str) -> list[str]:
    validate_identifier(database, "restore database")
    validate_identifier(app_owner, "role")
    return docker_admin_prefix() + [
        "pg_restore", "-h", "127.0.0.1", "-U", ADMIN_USER,
        "-d", database, "--no-owner", "--no-acl", "--role", app_owner,
        "--exit-on-error",
    ]


def verify_stack3_postgres_restore() -> VerificationResult:
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["3"])
    if plan != [0, 3]:
        raise PostgresVerifyError(f"unexpected Stack3 dependency plan: {plan}")

    manifest = manifests.get(STACK_ID)
    if not manifest:
        raise PostgresVerifyError("Stack3 manifest is missing")
    resources = manifest.get("recovery", {}).get("resources", [])
    matching = [r for r in resources if r.get("id") == RESOURCE_ID and r.get("strategy") == "postgres-custom-dump"]
    if len(matching) != 1:
        raise PostgresVerifyError("Stack3 must declare exactly one LiteLLM postgres-custom-dump resource")

    values = dr.read_dotenv_presence(ROOT / ".env")
    source_db = validate_identifier(dr.require_env_value(values, "LITELLM_DB_NAME", label="LITELLM_DB_NAME"), "database")
    app_owner = validate_identifier(dr.require_env_value(values, "LITELLM_DB_USER", label="LITELLM_DB_USER"), "role")

    checks = dr.preflight_runtime_sources(manifests, plan)
    if not any(c.stack_id == 3 and c.resource_id == RESOURCE_ID and c.check == "postgres-source" for c in checks):
        raise PostgresVerifyError("Stack3 PostgreSQL runtime preflight did not complete")

    temp_root = Path(tempfile.mkdtemp(prefix="local-hybrid-ai-pg-restore-test-"))
    os.chmod(temp_root, 0o700)
    dump_path = temp_root / "litellm-database.dump"
    restore_db = validate_identifier("dr_restore_" + secrets.token_hex(6), "restore database")
    restore_created = False
    dump_hash = ""
    dump_size = 0
    catalog_entries = 0
    source_tables: list[str] = []
    restored_tables: list[str] = []
    restored_nonempty = 0

    try:
        if database_exists(restore_db):
            raise PostgresVerifyError("generated restore database name already exists")

        source_tables = list_user_tables(source_db)
        if not source_tables:
            raise PostgresVerifyError("source LiteLLM database contains no user tables")

        dump_cmd = docker_admin_prefix() + [
            "pg_dump", "-h", "127.0.0.1", "-U", ADMIN_USER,
            "-d", source_db, "--format=custom", "--no-owner", "--no-acl",
        ]
        cp_dump = run_binary_to_file(dump_cmd, dump_path)
        if cp_dump.returncode != 0:
            fail_command("pg_dump", cp_dump)
        dump_size = dump_path.stat().st_size
        if dump_size <= 0:
            raise PostgresVerifyError("pg_dump produced an empty artifact")
        dump_hash = sha256_file(dump_path)

        cp_list = run_binary_stdin(pg_restore_list_command(), dump_path)
        if cp_list.returncode != 0:
            fail_command("pg_restore --list", cp_list)
        catalog_entries = len([
            line for line in cp_list.stdout.decode("utf-8", errors="replace").splitlines()
            if line and not line.startswith(";")
        ])
        if catalog_entries <= 0:
            raise PostgresVerifyError("custom dump catalog is empty")

        create_sql = f"CREATE DATABASE {quote_identifier(restore_db)} OWNER {quote_identifier(app_owner)};"
        cp_create = admin_psql("postgres", create_sql)
        if cp_create.returncode != 0:
            fail_command("restore database creation", cp_create)
        restore_created = True

        cp_restore = run_binary_stdin(
            pg_restore_database_command(restore_db, app_owner),
            dump_path,
        )
        if cp_restore.returncode != 0:
            fail_command("pg_restore", cp_restore)

        restored_tables = list_user_tables(restore_db)
        if restored_tables != source_tables:
            raise PostgresVerifyError("restored table inventory does not match source database")
        restored_nonempty = count_nonempty_tables(restore_db, restored_tables)

    finally:
        if restore_created:
            terminate_sql = (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{restore_db}' AND pid <> pg_backend_pid();"
            )
            cp_terminate = admin_psql("postgres", terminate_sql)
            if cp_terminate.returncode != 0:
                fail_command("restore database connection cleanup", cp_terminate)
            cp_drop = admin_psql("postgres", f"DROP DATABASE {quote_identifier(restore_db)};")
            if cp_drop.returncode != 0:
                fail_command("restore database removal", cp_drop)
        shutil.rmtree(temp_root, ignore_errors=False)

    removed = not database_exists(restore_db)
    if not removed:
        raise PostgresVerifyError("temporary restore database still exists after cleanup")
    temp_removed = not temp_root.exists()
    if not temp_removed:
        raise PostgresVerifyError("temporary dump directory still exists after cleanup")

    return VerificationResult(
        source_database=source_db,
        restore_database=restore_db,
        application_owner=app_owner,
        dump_sha256=dump_hash,
        dump_size_bytes=dump_size,
        dump_catalog_entries=catalog_entries,
        source_tables=len(source_tables),
        restored_tables=len(restored_tables),
        table_set_match=restored_tables == source_tables,
        restored_nonempty_tables=restored_nonempty,
        restore_database_removed=removed,
        temporary_dump_removed=temp_removed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Stack3 LiteLLM PostgreSQL dump and isolated restore")
    parser.add_argument("stack", choices=["3"], help="only Stack3 is enabled in this milestone")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    _ = args.stack

    try:
        result = verify_stack3_postgres_restore()
    except (PostgresVerifyError, dr.RecoveryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR Stack3 PostgreSQL isolated restore verification")
        print(f"- source database: {result.source_database}")
        print(f"- application owner: {result.application_owner}")
        print(f"- dump size: {result.dump_size_bytes} bytes")
        print(f"- dump sha256: {result.dump_sha256}")
        print(f"- dump catalog entries: {result.dump_catalog_entries}")
        print(f"- source/restored tables: {result.source_tables}/{result.restored_tables}")
        print(f"- table inventory match: {'PASS' if result.table_set_match else 'FAIL'}")
        print(f"- restored non-empty tables: {result.restored_nonempty_tables}")
        print(f"- temporary restore database removed: {'PASS' if result.restore_database_removed else 'FAIL'}")
        print(f"- temporary dump removed: {'PASS' if result.temporary_dump_removed else 'FAIL'}")
        print("- live LiteLLM database modified by tool: no")
        print("- container restarted: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
