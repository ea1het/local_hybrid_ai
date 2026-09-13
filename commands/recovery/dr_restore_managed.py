#!/usr/bin/env python3
"""Isolated managed-state recovery drill for restore-all.

This module consumes a previously created restore staging tree and restores the
managed Stack3 PostgreSQL and Stack4 Gitea artifacts into disposable, isolated
Docker containers. It never uses live service container names, never publishes
ports, never attaches the drill containers to platform networks, and never
writes under the live BASE_PATH.

The resulting reconstructed files remain under the staging destination for
inspection. Drill containers are always removed before returning.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import dr
import dr_restore_all
import dr_stack4_restore_verify

POSTGRES_PREFIX = "local-hybrid-ai-dr-postgres-"
GITEA_PREFIX = "local-hybrid-ai-dr-gitea-"


class RestoreManagedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedRestoreResult:
    stage: Path
    postgres_tables: int
    postgres_nonempty_tables: int
    gitea_tables: int
    gitea_nonempty_tables: int
    gitea_repositories: int
    gitea_health: bool
    drill_containers_removed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": str(self.stage),
            "postgres_tables": self.postgres_tables,
            "postgres_nonempty_tables": self.postgres_nonempty_tables,
            "gitea_tables": self.gitea_tables,
            "gitea_nonempty_tables": self.gitea_nonempty_tables,
            "gitea_repositories": self.gitea_repositories,
            "gitea_health": self.gitea_health,
            "drill_containers_removed": self.drill_containers_removed,
            "ports_published": False,
            "platform_network_attached": False,
            "live_runtime_modified": False,
        }


def _run(cmd: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _docker_exists(name: str) -> bool:
    return _run(["docker", "inspect", name]).returncode == 0


def _remove_container(name: str) -> None:
    if _docker_exists(name):
        cp = _run(["docker", "rm", "-f", name])
        if cp.returncode != 0:
            raise RestoreManagedError(f"failed to remove drill container {name}")


def _require_stage(stage: Path) -> tuple[Path, Path, dict[str, str]]:
    if not stage.is_absolute() or not stage.is_dir() or stage.is_symlink():
        raise RestoreManagedError("restore stage must be an existing absolute real directory")
    source = stage / "source"
    runtime = stage / "runtime"
    staged_env = source / ".env"
    if not source.is_dir() or not runtime.is_dir() or not staged_env.is_file() or staged_env.is_symlink():
        raise RestoreManagedError("restore stage is incomplete; run restore-stage first")
    values = dr.read_dotenv_presence(staged_env)
    live_base_raw = values.get("BASE_PATH", "").strip()
    if live_base_raw:
        live_base = Path(live_base_raw)
        if stage == live_base or live_base in stage.parents:
            raise RestoreManagedError("restore stage overlaps configured live BASE_PATH")
    return source, runtime, values


def _stage_source_commit(source: Path) -> str:
    marker = source / ".restore-source-commit"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            return value
    if not (source / "install.py").is_file():
        raise RestoreManagedError("staged source tree is incomplete")
    return "legacy-stage"


def _verify_legacy_stage_source(source: Path, commit: str) -> None:
    cp = subprocess.run(
        ["git", "show", f"{commit}:install.py"],
        cwd=dr_restore_all.PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        raise RestoreManagedError("cannot read install.py from recorded source commit")
    if (source / "install.py").read_bytes() != cp.stdout:
        raise RestoreManagedError("legacy staged source does not match recorded commit")


def _artifact(metadata: dict, *, strategy: str, resource_id: str) -> dict:
    matches = [item for item in metadata.get("artifacts", []) if item.get("strategy") == strategy and item.get("resource_id") == resource_id]
    if len(matches) != 1:
        raise RestoreManagedError(f"expected exactly one {strategy} artifact for {resource_id}")
    return matches[0]


def _postgres_image(source_root: Path) -> str:
    compose = (source_root / "stack3_-_litellm" / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s*image:\s*(postgres:[^\s]+)\s*$", compose, flags=re.MULTILINE)
    if not match:
        raise RestoreManagedError("cannot determine pinned Stack3 PostgreSQL image from staged source")
    return match.group(1)


def _wait_postgres(name: str, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _run(["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "postgres"]).returncode == 0:
            return
        time.sleep(1)
    raise RestoreManagedError("isolated PostgreSQL did not become ready")


def _pg_exec(name: str, database: str, sql: str) -> str:
    cp = _run(["docker", "exec", "-i", name, "psql", "-v", "ON_ERROR_STOP=1", "-At", "-U", "postgres", "-d", database], input_bytes=sql.encode())
    if cp.returncode != 0:
        detail = cp.stderr.decode("utf-8", errors="replace").strip()
        raise RestoreManagedError(f"isolated PostgreSQL command failed: {detail[:1000]}")
    return cp.stdout.decode("utf-8", errors="replace").strip()


def _validate_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise RestoreManagedError(f"invalid {label} identifier")
    return value


def restore_postgres(backup_set: Path, stage: Path, source_root: Path, values: dict[str, str], metadata: dict) -> tuple[int, int]:
    artifact = _artifact(metadata, strategy="postgres-custom-dump", resource_id="litellm-database")
    dump = backup_set / artifact["relative_path"]
    image = _postgres_image(source_root)
    db_name = _validate_identifier(dr.require_env_value(values, "LITELLM_DB_NAME", label="LITELLM_DB_NAME"), "database")
    app_user = _validate_identifier(dr.require_env_value(values, "LITELLM_DB_USER", label="LITELLM_DB_USER"), "role")
    root = stage / "managed" / "postgres"
    data = root / "data"
    data.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(root, 0o700)
    os.chmod(data, 0o700)
    name = POSTGRES_PREFIX + secrets.token_hex(5)
    admin_password = secrets.token_urlsafe(32)
    started = False
    try:
        cp = _run(["docker", "run", "-d", "--name", name, "--network", "none", "-e", f"POSTGRES_PASSWORD={admin_password}", "-e", "POSTGRES_USER=postgres", "-e", "POSTGRES_DB=postgres", "-v", f"{data}:/var/lib/postgresql/data", image])
        if cp.returncode != 0:
            raise RestoreManagedError("cannot start isolated PostgreSQL: " + cp.stderr.decode("utf-8", errors="replace").strip()[:1000])
        started = True
        _wait_postgres(name)
        _pg_exec(name, "postgres", f'CREATE ROLE "{app_user}" LOGIN;')
        _pg_exec(name, "postgres", f'CREATE DATABASE "{db_name}" OWNER "{app_user}";')
        with dump.open("rb") as handle:
            cp = subprocess.run(["docker", "exec", "-i", name, "pg_restore", "--no-owner", "--no-privileges", "-U", "postgres", "-d", db_name], stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0:
            raise RestoreManagedError("isolated PostgreSQL pg_restore failed: " + cp.stderr.decode("utf-8", errors="replace").strip()[:1000])
        rows = _pg_exec(name, db_name, "SELECT schemaname||'.'||tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1;").splitlines()
        tables = [row for row in rows if row.strip()]
        if not tables:
            raise RestoreManagedError("isolated PostgreSQL restore produced no application tables")
        nonempty = 0
        for table in tables:
            schema, rel = table.split(".", 1)
            schema = _validate_identifier(schema, "schema")
            rel = _validate_identifier(rel, "table")
            if _pg_exec(name, db_name, f'SELECT EXISTS(SELECT 1 FROM "{schema}"."{rel}" LIMIT 1);') == "t":
                nonempty += 1
        return len(tables), nonempty
    finally:
        if started or _docker_exists(name):
            _remove_container(name)


def _copy_tree_contents(source: Path, destination: Path, *, skip_names: set[str] | None = None) -> None:
    skip = skip_names or set()
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name in skip:
            continue
        target = destination / child.name
        if target.exists() or target.is_symlink():
            raise RestoreManagedError(f"Gitea reconstructed target already exists: {target}")
        if child.is_dir():
            shutil.copytree(child, target, symlinks=False)
        elif child.is_file():
            shutil.copy2(child, target)
        else:
            raise RestoreManagedError(f"unsupported extracted Gitea entry: {child}")


def _render_gitea_config(source_root: Path, values: dict[str, str], target: Path) -> None:
    rendered = (source_root / "stack4_-_gitea" / "config" / "gitea" / "app.ini").read_text(encoding="utf-8")
    replacements = {
        "GITEA_DOMAIN": dr.require_env_value(values, "GITEA_DOMAIN", label="GITEA_DOMAIN"),
        "GITEA_ROOT_URL": dr.require_env_value(values, "GITEA_ROOT_URL", label="GITEA_ROOT_URL"),
        "GITEA_SSH_DOMAIN": dr.require_env_value(values, "GITEA_SSH_DOMAIN", label="GITEA_SSH_DOMAIN"),
        "GITEA_SSH_PORT": dr.require_env_value(values, "GITEA_SSH_PORT", label="GITEA_SSH_PORT"),
        "GITEA_INTERNAL_TOKEN": dr.require_env_value(values, "GITEA_INTERNAL_TOKEN", label="GITEA_INTERNAL_TOKEN"),
        "GITEA_JWT_SECRET": dr.require_env_value(values, "GITEA_JWT_SECRET", label="GITEA_JWT_SECRET"),
    }
    for key, value in replacements.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    if re.search(r"@@[A-Za-z0-9_]+@@", rendered):
        raise RestoreManagedError("unresolved placeholder remains in isolated Gitea config")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    os.chmod(target, 0o640)


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid)
    for item in path.rglob("*"):
        os.lchown(item, uid, gid) if item.is_symlink() else os.chown(item, uid, gid)


def _wait_gitea(name: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _run(["docker", "exec", name, "wget", "-q", "--spider", "http://127.0.0.1:3000/api/healthz"]).returncode == 0:
            return
        state = _run(["docker", "inspect", "-f", "{{.State.Status}}", name])
        if state.returncode == 0 and state.stdout.decode().strip() in {"exited", "dead"}:
            logs = _run(["docker", "logs", "--tail", "80", name])
            detail = (logs.stdout + logs.stderr).decode("utf-8", errors="replace")
            raise RestoreManagedError(f"isolated Gitea exited before health: {detail[:1500]}")
        time.sleep(1)
    raise RestoreManagedError("isolated Gitea did not become healthy")


def restore_gitea(backup_set: Path, stage: Path, source_root: Path, values: dict[str, str], metadata: dict) -> tuple[int, int, int, bool]:
    artifact = _artifact(metadata, strategy="gitea-native-dump", resource_id="gitea-state")
    archive = backup_set / artifact["relative_path"]
    managed = stage / "managed" / "gitea"
    extracted = managed / "dump"
    runtime = managed / "runtime"
    config = runtime / "config"
    data = runtime / "data"
    extracted.mkdir(parents=True, exist_ok=False, mode=0o700)
    data.mkdir(parents=True, exist_ok=False, mode=0o700)
    config.mkdir(parents=True, exist_ok=False, mode=0o700)
    dr_stack4_restore_verify.safe_extract_gitea_dump(archive, extracted)
    dump_data = extracted / "data"
    dump_repos = extracted / "repos"
    if not dump_data.is_dir() or not dump_repos.is_dir():
        raise RestoreManagedError("Gitea native dump is missing data/ or repos/")
    _copy_tree_contents(dump_data, data, skip_names={"gitea.db"})
    repo_target = data / "git" / "repositories"
    repo_target.mkdir(parents=True, exist_ok=True)
    _copy_tree_contents(dump_repos, repo_target)
    db_path = data / "gitea.db"
    tables, nonempty = dr_stack4_restore_verify.restore_sqlite(extracted / "gitea-db.sql", db_path)
    repositories = dr_stack4_restore_verify.find_bare_repositories(repo_target)
    for repo in repositories:
        dr_stack4_restore_verify.verify_repository(repo)
    app_ini = config / "app.ini"
    _render_gitea_config(source_root, values, app_ini)
    (config / "conf").mkdir(mode=0o750)
    os.symlink("../app.ini", config / "conf" / "app.ini")
    image = dr.require_env_value(values, "GITEA_IMAGE", label="GITEA_IMAGE")
    uid = int(dr.require_env_value(values, "GITEA_UID", label="GITEA_UID"))
    gid = int(dr.require_env_value(values, "GITEA_GID", label="GITEA_GID"))
    if uid < 1 or gid < 1:
        raise RestoreManagedError("isolated Gitea UID/GID must be positive")
    _chown_tree(data, uid, gid)
    _chown_tree(config, uid, gid)
    name = GITEA_PREFIX + secrets.token_hex(5)
    started = False
    try:
        cp = _run(["docker", "run", "-d", "--name", name, "--network", "none", "--user", f"{uid}:{gid}", "-e", "GITEA_CUSTOM=/etc/gitea", "-v", f"{config}:/etc/gitea", "-v", f"{data}:/var/lib/gitea", image, "gitea", "web", "--config", "/etc/gitea/app.ini"])
        if cp.returncode != 0:
            raise RestoreManagedError("cannot start isolated Gitea: " + cp.stderr.decode("utf-8", errors="replace").strip()[:1000])
        started = True
        _wait_gitea(name)
        return tables, nonempty, len(repositories), True
    finally:
        if started or _docker_exists(name):
            _remove_container(name)


def run_managed_restore(backup_set: Path, stage: Path) -> ManagedRestoreResult:
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    plan = dr_restore_all.plan_restore_all(backup_set)
    source_root, _, values = _require_stage(stage)
    staged_commit = _stage_source_commit(source_root)
    if staged_commit == "legacy-stage":
        _verify_legacy_stage_source(source_root, plan.source_commit)
    elif staged_commit != plan.source_commit:
        raise RestoreManagedError("staged source commit marker does not match recovery point")
    managed = stage / "managed"
    if managed.exists():
        raise RestoreManagedError("managed restore target already exists; inspect/remove the previous drill explicitly before retrying")
    managed.mkdir(mode=0o700)
    os.chmod(managed, 0o700)
    pg_tables, pg_nonempty = restore_postgres(backup_set, stage, source_root, values, metadata)
    g_tables, g_nonempty, repos, health = restore_gitea(backup_set, stage, source_root, values, metadata)
    cp = _run(["docker", "ps", "-a", "--format", "{{.Names}}"])
    leftovers = [] if cp.returncode != 0 else [name for name in cp.stdout.decode().splitlines() if name.startswith(POSTGRES_PREFIX) or name.startswith(GITEA_PREFIX)]
    if leftovers:
        raise RestoreManagedError("drill container cleanup incomplete: " + ", ".join(leftovers))
    return ManagedRestoreResult(stage, pg_tables, pg_nonempty, g_tables, g_nonempty, repos, health, True)
