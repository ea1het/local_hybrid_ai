#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only destination and runtime-source preflight for disaster recovery."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_BACKUP_ROOT = Path("/opt/local-hybrid-ai-backups")
BACKUP_ROOT_ENV = "DR_BACKUP_ROOT"
BACKUP_SET_NAME_PATTERN = "backup-YYYYMMDDTHHMMSSZ"
DOCKER_RUNTIME_STRATEGIES = {"postgres-custom-dump", "gitea-native-dump"}
ROOT = Path(__file__).resolve().parent


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DestinationPreflight:
    root: Path
    source: str
    root_exists: bool
    nearest_existing_parent: Path
    writable_parent: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "source": self.source,
            "root_exists": self.root_exists,
            "nearest_existing_parent": str(self.nearest_existing_parent),
            "writable_parent": self.writable_parent,
            "backup_set_name_pattern": BACKUP_SET_NAME_PATTERN,
            "creation_required": not self.root_exists,
        }


@dataclass(frozen=True)
class RuntimeCheck:
    stack_id: int | None
    resource_id: str | None
    check: str
    status: str
    blocking: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "check": self.check,
            "status": self.status,
            "blocking": self.blocking,
            "detail": self.detail,
        }


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def resolve_backup_root(cli_destination: str | None, *, environ: dict[str, str] | None = None) -> tuple[Path, str]:
    env = os.environ if environ is None else environ
    if cli_destination is not None:
        raw, source = cli_destination, "cli"
    elif env.get(BACKUP_ROOT_ENV):
        raw, source = env[BACKUP_ROOT_ENV], "environment"
    else:
        raw, source = str(DEFAULT_BACKUP_ROOT), "default"
    if not raw or not raw.strip():
        raise RecoveryError("backup destination cannot be empty")
    path = Path(raw)
    if not path.is_absolute():
        raise RecoveryError("backup destination must be an absolute path")
    normalized = Path(os.path.abspath(os.path.normpath(str(path))))
    if normalized == Path("/"):
        raise RecoveryError("backup destination cannot be filesystem root")
    return normalized, source


def nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def preflight_backup_destination(root: Path, source: str) -> DestinationPreflight:
    if root.exists() and not root.is_dir():
        raise RecoveryError(f"backup destination exists but is not a directory: {root}")
    parent = root if root.exists() else nearest_existing_parent(root.parent)
    if not parent.exists() or not parent.is_dir():
        raise RecoveryError(f"cannot resolve an existing parent for backup destination: {root}")
    writable = os.access(parent, os.W_OK | os.X_OK)
    if not writable:
        raise RecoveryError(f"backup destination parent is not writable by current user: {parent}")
    return DestinationPreflight(root, source, root.exists(), parent, writable)


def read_dotenv_presence(path: Path) -> dict[str, str]:
    """Read dotenv names/values without shell evaluation or outputting protected values."""
    if not path.is_file():
        raise RecoveryError(f"missing operational environment file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RecoveryError(f"cannot read operational environment file metadata: {exc}") from exc
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def require_env_value(values: dict[str, str], key: str, *, label: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise RecoveryError(f"required {label} is missing or empty in operational .env")
    return value


def resolve_base_path(values: dict[str, str]) -> Path:
    raw = require_env_value(values, "BASE_PATH", label="BASE_PATH")
    path = Path(raw)
    if not path.is_absolute():
        raise RecoveryError("BASE_PATH in operational .env must be an absolute path")
    normalized = Path(os.path.abspath(os.path.normpath(str(path))))
    if not normalized.is_dir():
        raise RecoveryError(f"BASE_PATH does not exist as a directory: {normalized}")
    return normalized


def expand_runtime_path(raw: str, base_path: Path) -> Path:
    token = "${BASE_PATH}"
    if raw == token:
        expanded = str(base_path)
    elif raw.startswith(token + "/"):
        expanded = str(base_path) + raw[len(token) :]
    elif "$" in raw:
        raise RecoveryError("runtime recovery path contains unsupported variable expansion")
    else:
        expanded = raw
    path = Path(expanded)
    if not path.is_absolute():
        raise RecoveryError("runtime recovery path must resolve to an absolute path")
    return Path(os.path.abspath(os.path.normpath(str(path))))


def owned_container(manifest: dict, service: str) -> bool:
    return f"container:{service}" in manifest.get("owns", [])


def docker_state(service: str, runner: CommandRunner) -> str | None:
    cp = runner(
        ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", service]
    )
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


def gitea_help_flags(text: str) -> list[str]:
    return sorted(set(re.findall(r"(?<![A-Za-z0-9-])--[a-z0-9][a-z0-9-]*", text.lower())))


def runtime_resources(manifests: dict[int, dict], plan: list[int]):
    for sid in plan:
        manifest = manifests[sid]
        for resource in manifest["recovery"].get("resources", []):
            yield sid, manifest, resource


def ensure_docker_preflight(manifests: dict[int, dict], plan: list[int], docker_available: bool | None) -> None:
    needs_docker = any(
        resource["strategy"] in DOCKER_RUNTIME_STRATEGIES for _, _, resource in runtime_resources(manifests, plan)
    )
    available = shutil.which("docker") is not None if docker_available is None else docker_available
    if needs_docker and not available:
        raise RecoveryError("Docker CLI is required for runtime recovery preflight")


def preflight_archive_source(sid: int, rid: str, source: dict, base_path: Path) -> RuntimeCheck:
    path = expand_runtime_path(source["path"], base_path)
    if not path.exists():
        raise RecoveryError(f"stack{sid} {rid}: declared runtime source does not exist: {path}")
    if path.is_dir():
        try:
            nonempty = next(path.iterdir(), None) is not None
        except OSError as exc:
            raise RecoveryError(f"stack{sid} {rid}: cannot inspect runtime source: {exc}") from exc
        if not nonempty:
            raise RecoveryError(f"stack{sid} {rid}: declared runtime source directory is empty")
    elif path.stat().st_size == 0:
        raise RecoveryError(f"stack{sid} {rid}: declared runtime source file is empty")
    return RuntimeCheck(sid, rid, "runtime-source", "OK", True, f"runtime path exists and is non-empty: {path}")


def preflight_external_config_source(sid: int, rid: str, source: dict, values: dict[str, str]) -> RuntimeCheck:
    if not values.get(source["key"], "").strip():
        raise RecoveryError(f"stack{sid} {rid}: required protected configuration is missing or empty")
    return RuntimeCheck(
        sid, rid, "external-config", "OK", True, "required protected value is present; value not displayed"
    )


def preflight_git_source(sid: int, rid: str, source: dict, values: dict[str, str]) -> RuntimeCheck:
    repository_env = source.get("repository_env")
    if repository_env:
        if not values.get(repository_env, "").strip():
            raise RecoveryError(f"stack{sid} {rid}: declared Git repository configuration is missing")
        return RuntimeCheck(
            sid,
            rid,
            "externalized-git",
            "OK",
            True,
            "declared Git repository configuration is present; value not displayed",
        )
    return RuntimeCheck(
        sid,
        rid,
        "externalized-git",
        "DECLARED",
        False,
        "externalized Git source declared without repository_env; contract presence only",
    )


def preflight_docker_service(sid: int, rid: str, manifest: dict, source: dict, runner: CommandRunner) -> RuntimeCheck:
    service = source["service"]
    if not owned_container(manifest, service):
        raise RecoveryError(f"stack{sid} {rid}: source service {service} is not declared as stack-owned container")
    state = docker_state(service, runner)
    if state is None:
        raise RecoveryError(f"stack{sid} {rid}: declared Docker service is absent: {service}")
    if not state.startswith("running"):
        raise RecoveryError(f"stack{sid} {rid}: declared Docker service is not running: {service} ({state})")
    return RuntimeCheck(sid, rid, "docker-service", "OK", True, f"{service}={state}")


def preflight_postgres_source(
    sid: int, rid: str, source: dict, values: dict[str, str], runner: CommandRunner
) -> RuntimeCheck:
    db = require_env_value(values, source["database_env"], label="database configuration")
    user_env = source.get("user_env")
    user = require_env_value(values, user_env, label="database user configuration") if user_env else "postgres"
    cp = runner(["docker", "exec", source["service"], "pg_isready", "-d", db, "-U", user])
    if cp.returncode != 0:
        raise RecoveryError(f"stack{sid} {rid}: PostgreSQL source did not pass pg_isready")
    return RuntimeCheck(
        sid, rid, "postgres-source", "OK", True, "configured database/user resolved and PostgreSQL accepts connections"
    )


def preflight_gitea_source(sid: int, rid: str, source: dict, runner: CommandRunner) -> RuntimeCheck:
    service = source["service"]
    version_cp = runner(["docker", "exec", service, "gitea", "--version"])
    if version_cp.returncode != 0 or not version_cp.stdout.strip():
        raise RecoveryError(f"stack{sid} {rid}: cannot determine Gitea version")
    help_cp = runner(["docker", "exec", service, "gitea", "dump", "--help"])
    if help_cp.returncode != 0:
        raise RecoveryError(f"stack{sid} {rid}: gitea dump --help is unavailable")
    flags = gitea_help_flags(help_cp.stdout + "\n" + help_cp.stderr)
    version = version_cp.stdout.strip().splitlines()[0]
    return RuntimeCheck(
        sid,
        rid,
        "gitea-native-dump",
        "OK",
        True,
        f"version={version}; dump help available; flags={','.join(flags) if flags else '(none parsed)'}",
    )


def preflight_runtime_resource(
    sid: int, manifest: dict, resource: dict, *, values: dict[str, str], base_path: Path, runner: CommandRunner
) -> list[RuntimeCheck]:
    rid, strategy, source = resource["id"], resource["strategy"], resource["config"]["source"]
    if strategy == "archive":
        return [preflight_archive_source(sid, rid, source, base_path)]
    if strategy == "external-config":
        return [preflight_external_config_source(sid, rid, source, values)]
    if strategy == "git":
        return [preflight_git_source(sid, rid, source, values)]
    if strategy == "postgres-custom-dump":
        return [
            preflight_docker_service(sid, rid, manifest, source, runner),
            preflight_postgres_source(sid, rid, source, values, runner),
        ]
    if strategy == "gitea-native-dump":
        return [
            preflight_docker_service(sid, rid, manifest, source, runner),
            preflight_gitea_source(sid, rid, source, runner),
        ]
    return []


def preflight_runtime_sources(
    manifests: dict[int, dict],
    plan: list[int],
    *,
    env_path: Path = ROOT / ".env",
    runner: CommandRunner = run_command,
    docker_available: bool | None = None,
) -> list[RuntimeCheck]:
    values = read_dotenv_presence(env_path)
    base_path = resolve_base_path(values)
    checks = [
        RuntimeCheck(None, None, "operational-env", "OK", True, "present and readable"),
        RuntimeCheck(None, None, "base-path", "OK", True, f"resolved to {base_path}"),
    ]
    ensure_docker_preflight(manifests, plan, docker_available)
    for sid, manifest, resource in runtime_resources(manifests, plan):
        checks.extend(
            preflight_runtime_resource(sid, manifest, resource, values=values, base_path=base_path, runner=runner)
        )
    return checks
