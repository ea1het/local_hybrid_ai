#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Isolated logical dump/restore upgrade path for a major PostgreSQL version bump.

PostgreSQL data directories are not compatible across major versions, so the
generic env-version swap-and-restart mechanism cannot upgrade a PostgreSQL
component in place: starting the new image against the existing data
directory simply refuses to boot. This module performs a real major upgrade
instead: dump with the running (old) server, stop the dependent application
and the database, move the old data directory aside (never deleted
automatically), start the new image against a fresh data directory, restore
the dump, verify the table inventory matches, and only then resume the
dependent application. Any failure after the dump exists leaves the old data
directory and the dump file in place for manual recovery; nothing is deleted
on a failure path.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from local_ai_cli.common import postgres as pg

TYPE = "postgres-major-upgrade"
REQUIRED_APPLY_KEYS = ("image_env_key", "database_env", "role_env", "data_path_env", "data_relative_path")


def _run(cmd: list[str], *, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )


def _container_state(name: str) -> str:
    cp = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        return "absent"
    status, _, health = cp.stdout.strip().partition("|")
    return f"{status}/{health}" if health else (status or "unknown")


def _wait_healthy(name: str, *, timeout_seconds: int = 180) -> None:
    from .engine import UpgradeExecutionError

    deadline = time.monotonic() + timeout_seconds
    while True:
        state = _container_state(name)
        if state in {"running", "running/healthy"}:
            return
        if state in {"absent", "dead", "exited"} or state.startswith("dead/") or state.startswith("exited/"):
            raise UpgradeExecutionError("UPGRADE_READY_FAILED", f"{name} failed before becoming healthy: {state}")
        if time.monotonic() >= deadline:
            raise UpgradeExecutionError("UPGRADE_READY_TIMEOUT", f"{name} did not become healthy in time: {state}")
        time.sleep(2)


def _timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def execute(
    *,
    root: Path,
    runtime_root: Path,
    stack_directory: str,
    component_key: str,
    apply: dict,
    container: str,
    target_image_ref: str,
    env_path: Path,
    env_values: dict,
    quiet: bool,
) -> None:
    from .engine import UpgradeExecutionError, _atomic_update_env

    missing = [key for key in REQUIRED_APPLY_KEYS if not isinstance(apply.get(key), str) or not apply.get(key)]
    deploy = apply.get("deploy")
    if missing or not isinstance(deploy, list) or not deploy:
        raise UpgradeExecutionError(
            "UPGRADE_INTERNAL_CONFIG", f"component has an incomplete postgres-major-upgrade recipe: {component_key}"
        )
    dependents = apply.get("dependent_containers", [])
    if not isinstance(dependents, list) or not all(isinstance(d, str) and d for d in dependents):
        raise UpgradeExecutionError(
            "UPGRADE_INTERNAL_CONFIG", f"component has an invalid dependent_containers list: {component_key}"
        )

    image_env_key, database_env, role_env, data_path_env, data_relative_path = (
        apply[key] for key in REQUIRED_APPLY_KEYS
    )
    database, role, base_path = env_values.get(database_env), env_values.get(role_env), env_values.get(data_path_env)
    if not database or not role or not base_path:
        raise UpgradeExecutionError(
            "UPGRADE_ENV_KEY_MISSING",
            f"postgres-major-upgrade requires {database_env}, {role_env} and {data_path_env} in the operational .env",
        )
    try:
        pg.validate_identifier(database, "database")
        pg.validate_identifier(role, "role")
    except pg.PostgresVerifyError as exc:
        raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", str(exc)) from exc

    data_dir = Path(base_path.rstrip("/")) / data_relative_path
    if not data_dir.is_dir():
        raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", f"postgres data directory not found: {data_dir}")
    if _container_state(container) not in {"running", "running/healthy"}:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_NOT_RUNNING", f"{container} must be running before a major-version migration"
        )

    # Read-only: capture the pre-migration table inventory while the old server is still live.
    source_tables = pg.list_user_tables(database)

    work_root = runtime_root / "platform" / "postgres-major-upgrade"
    work_root.mkdir(parents=True, exist_ok=True)
    working_dir = work_root / f"{component_key.replace('/', '_')}-{_timestamp()}"
    working_dir.mkdir(mode=0o700)
    dump_path = working_dir / "pre-upgrade.dump"

    cp = pg.run_binary_to_file(
        pg.docker_admin_prefix()
        + [
            "pg_dump",
            "-h",
            "127.0.0.1",
            "-U",
            pg.ADMIN_USER,
            "-d",
            database,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        ],
        dump_path,
    )
    if cp.returncode != 0:
        pg.fail_command("pg_dump", cp)
    if dump_path.stat().st_size <= 0:
        raise UpgradeExecutionError(
            "UPGRADE_BACKUP_INVALID", "postgres-major-upgrade dump is empty; aborting before any mutation"
        )

    for dependent in dependents:
        _run(["docker", "stop", dependent])
    _run(["docker", "stop", container])

    aside = data_dir.parent / f"{data_dir.name}.pre-upgrade-{_timestamp()}"
    try:
        data_dir.rename(aside)
    except OSError as exc:
        raise UpgradeExecutionError(
            "UPGRADE_COMMAND_FAILED",
            f"cannot move aside the old postgres data directory for {component_key}: {exc}; dump preserved at {dump_path}",
        ) from exc

    _atomic_update_env(env_path, {image_env_key: target_image_ref})

    compose_file = root / stack_directory / "docker-compose.yml"
    cp = _run(
        ["docker", "compose", "--env-file", str(env_path), "-f", str(compose_file), "up", "-d", container],
        cwd=root / stack_directory,
    )
    if cp.returncode != 0:
        raise UpgradeExecutionError(
            "UPGRADE_COMMAND_FAILED",
            f"cannot start {container} on the new major version for {component_key}; old data directory preserved at {aside}, dump preserved at {dump_path}: {(cp.stderr or '').strip()}",
        )
    _wait_healthy(container)

    deploy_cmd = list(deploy)
    if deploy_cmd and deploy_cmd[0].startswith("./"):
        deploy_cmd = ["bash", deploy_cmd[0], *deploy_cmd[1:]]
    cp = _run(deploy_cmd, cwd=root / stack_directory, capture=quiet)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip() if quiet else ""
        raise UpgradeExecutionError(
            "UPGRADE_COMMAND_FAILED",
            f"postgres-major-upgrade deploy step failed for {component_key}; old data directory preserved at {aside}, dump preserved at {dump_path}"
            + (f": {detail}" if detail else ""),
        )

    cp = pg.run_binary_stdin(pg.pg_restore_database_command(database, role), dump_path)
    if cp.returncode != 0:
        detail = (cp.stderr or b"").decode("utf-8", errors="replace").strip()[:1200]
        raise UpgradeExecutionError(
            "UPGRADE_COMMAND_FAILED",
            f"pg_restore failed for {component_key}; old data directory preserved at {aside}, dump preserved at {dump_path}: {detail}",
        )

    restored_tables = pg.list_user_tables(database)
    if restored_tables != source_tables:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_NOT_RUNNING",
            f"restored table inventory does not match the pre-upgrade source for {component_key}; old data directory preserved at {aside}, dump preserved at {dump_path}",
        )

    for dependent in dependents:
        cp = _run(["docker", "start", dependent])
        if cp.returncode != 0:
            raise UpgradeExecutionError(
                "UPGRADE_COMMAND_FAILED",
                f"postgres-major-upgrade succeeded for {component_key} but {dependent} did not restart; start it manually: {(cp.stderr or '').strip()}",
            )

    shutil.rmtree(working_dir, ignore_errors=True)
