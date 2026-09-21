#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared PostgreSQL DR primitives for Stack3 / LiteLLM dump and restore verification.

Identifier validation, admin-credential command construction and isolated
restore-database helpers used by both the backup dump path and the restore
verification path. Neither path modifies the production LiteLLM database or
restarts containers.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICE = "litellm-postgres"
ADMIN_USER = "postgres"
ADMIN_SECRET_IN_CONTAINER = "/run/secrets/postgres_admin_password"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresVerifyError(RuntimeError):
    pass


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
        "docker",
        "exec",
        "-i",
        SERVICE,
        "sh",
        "-c",
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
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            ADMIN_USER,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            sql,
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
        "pg_restore",
        "-h",
        "127.0.0.1",
        "-U",
        ADMIN_USER,
        "-d",
        database,
        "--no-owner",
        "--no-acl",
        "--role",
        app_owner,
        "--exit-on-error",
    ]
