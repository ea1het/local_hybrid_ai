#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Clean-target destructive restore executor for a complete DR recovery point."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import planner
import restore_all
import restore_compat
import restore_managed
import restore_stage
import stack4_restore_verify


class RestoreLiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreLiveResult:
    backup_set: Path
    source_commit: str
    stacks_root: Path
    base_path: Path
    resolved_stacks: tuple[int, ...]
    postgres_tables: int
    gitea_tables: int
    gitea_repositories: int
    external_git_restored: int

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.backup_set),
            "source_commit": self.source_commit,
            "stacks_root": str(self.stacks_root),
            "base_path": str(self.base_path),
            "resolved_stacks": list(self.resolved_stacks),
            "postgres_tables": self.postgres_tables,
            "gitea_tables": self.gitea_tables,
            "gitea_repositories": self.gitea_repositories,
            "external_git_restored": self.external_git_restored,
            "clean_target_required": True,
        }


@dataclass(frozen=True)
class RestoreContext:
    backup_set: Path
    metadata: dict
    source_commit: str
    plan: tuple[int, ...]
    manifests: dict[int, dict]
    env_source: Path
    values: dict[str, str]
    stacks_root: Path
    base_path: Path


def _run(cmd: list[str], *, cwd: Path | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, cwd=cwd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _require_ok(cp: subprocess.CompletedProcess[bytes], label: str) -> None:
    if cp.returncode == 0:
        return
    detail = (cp.stderr or cp.stdout).decode("utf-8", errors="replace").strip()
    if len(detail) > 2000:
        detail = "..." + detail[-2000:]
    raise RestoreLiveError(f"{label} failed: {detail or 'no diagnostic output'}")


def _read_env_artifact(backup_set: Path, metadata: dict) -> tuple[Path, dict[str, str]]:
    matches = [a for a in metadata.get("global_artifacts", []) if a.get("resource_id", a.get("id")) == "operational-env"]
    if len(matches) != 1:
        raise RestoreLiveError("backup set must contain exactly one operational-env global artifact")
    env_path = backup_set / matches[0]["relative_path"]
    if not env_path.is_file() or env_path.is_symlink():
        raise RestoreLiveError("operational environment artifact is missing or invalid")
    return env_path, planner.read_dotenv_presence(env_path)


def _absolute_safe_path(values: dict[str, str], key: str) -> Path:
    path = Path(planner.require_env_value(values, key, label=key))
    if not path.is_absolute() or path == Path("/"):
        raise RestoreLiveError(f"{key} must be an absolute non-root path")
    return path


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and next(path.iterdir(), None) is None


def _require_clean_path(path: Path, label: str) -> None:
    if not path.exists() or _is_empty_dir(path):
        return
    raise RestoreLiveError(f"{label} must be absent or an empty real directory: {path}")


def _owned_objects(manifests: dict[int, dict], plan: list[int] | tuple[int, ...]) -> tuple[set[str], set[str], set[str]]:
    containers: set[str] = set()
    volumes: set[str] = set()
    networks: set[str] = set()
    for sid in plan:
        for owned in manifests[sid].get("owns", []):
            kind, _, name = owned.partition(":")
            if kind == "container":
                containers.add(name)
            elif kind == "volume":
                volumes.add(name)
            elif kind == "docker-network":
                networks.add(name)
    return containers, volumes, networks


def _require_absent_docker_objects(kind: str, names: set[str]) -> None:
    inspect = ["docker", "inspect"] if kind == "container" else ["docker", kind, "inspect"]
    for name in sorted(names):
        if _run([*inspect, name]).returncode == 0:
            raise RestoreLiveError(f"clean-target preflight found existing platform {kind}: {name}")


def require_clean_target(stacks_root: Path, base_path: Path, manifests: dict[int, dict], plan: list[int] | tuple[int, ...]) -> None:
    if stacks_root == base_path or stacks_root in base_path.parents or base_path in stacks_root.parents:
        raise RestoreLiveError("STACKS_ROOT and BASE_PATH must be disjoint paths")
    _require_clean_path(stacks_root, "STACKS_ROOT")
    _require_clean_path(base_path, "BASE_PATH")
    containers, volumes, networks = _owned_objects(manifests, plan)
    _require_absent_docker_objects("container", containers)
    _require_absent_docker_objects("volume", volumes)
    _require_absent_docker_objects("network", networks)


def _materialize_source(commit: str, stacks_root: Path) -> None:
    stacks_root.parent.mkdir(parents=True, exist_ok=True)
    if stacks_root.exists():
        os.chmod(stacks_root, 0o755)
    else:
        stacks_root.mkdir(mode=0o755)
    fd, tar_name = tempfile.mkstemp(prefix="restore-platform-source-", suffix=".tar", dir=stacks_root.parent)
    os.close(fd)
    tar_path = Path(tar_name)
    try:
        cp = _run(["git", "archive", "--format=tar", "--output", str(tar_path), commit], cwd=restore_all.PROJECT_ROOT)
        _require_ok(cp, "materialize recorded source commit")
        restore_stage._extract_tar_safely(tar_path, stacks_root)
    finally:
        tar_path.unlink(missing_ok=True)


def _copy_env(env_source: Path, stacks_root: Path) -> None:
    target = stacks_root / ".env"
    restore_stage._copy_private(env_source, target)
    if stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise RestoreLiveError("restored operational .env does not have mode 0600")


def _load_target_manifests(stacks_root: Path, plan: list[int] | tuple[int, ...]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for sid in plan:
        matches = list(stacks_root.glob(f"stack{sid}_-*/manifest.json"))
        if len(matches) != 1:
            raise RestoreLiveError(f"recorded source must contain exactly one manifest for stack{sid}")
        try:
            data = json.loads(matches[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RestoreLiveError(f"cannot read target stack{sid} manifest: {exc}") from exc
        if data.get("id") != sid:
            raise RestoreLiveError(f"target stack{sid} manifest id mismatch")
        result[sid] = data
    return result


def _load_target_lifecycle(stacks_root: Path) -> dict:
    try:
        data = json.loads((stacks_root / "installer" / "lifecycle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreLiveError(f"cannot read target lifecycle registry: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise RestoreLiveError("unsupported target lifecycle registry")
    return data


def _run_lifecycle_commands(stacks_root: Path, lifecycle: dict, manifests: dict[int, dict], plan: list[int], phase: str) -> None:
    for sid in plan:
        entry = lifecycle["stacks"].get(str(sid))
        if not isinstance(entry, dict) or entry.get("directory") != manifests[sid]["directory"]:
            raise RestoreLiveError(f"target lifecycle/manifest mismatch for stack{sid}")
        for command in entry.get(phase, []):
            if not isinstance(command, list) or not command:
                raise RestoreLiveError(f"invalid target lifecycle {phase} command for stack{sid}")
            actual = ["bash", command[0], *command[1:]] if command[0].startswith("./") else command
            _require_ok(_run(actual, cwd=stacks_root / manifests[sid]["directory"]), f"stack{sid} {phase}")


def _find_resource(manifests: dict[int, dict], sid: int, resource_id: str) -> dict:
    resource = next((r for r in manifests[sid].get("recovery", {}).get("resources", []) if r.get("id") == resource_id), None)
    if resource is None:
        raise RestoreLiveError(f"missing recovery resource for stack{sid}/{resource_id}")
    return resource


def _restore_preprepare_archives(backup_set: Path, metadata: dict, base_path: Path, manifests: dict[int, dict]) -> int:
    count = 0
    for artifact in metadata.get("artifacts", []):
        if artifact.get("restore_phase") != "pre-prepare":
            continue
        if artifact.get("strategy") != "archive":
            raise RestoreLiveError(f"unsupported pre-prepare strategy: {artifact.get('strategy')}")
        sid = artifact["stack_id"]
        resource = _find_resource(manifests, sid, artifact["resource_id"])
        target = planner.expand_runtime_path(resource["config"]["source"]["path"], base_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RestoreLiveError(f"pre-prepare archive target already exists: {target}")
        archive = backup_set / artifact["relative_path"]
        restored = restore_stage._extract_tar_safely(archive, target.parent, expected_root=target.name)
        if restored <= 0 or not target.is_dir():
            raise RestoreLiveError(f"archive restore produced no usable target: {target}")
        count += 1
    return count


def _restore_managed_archive(backup_set: Path, artifact: dict, resource: dict, base_path: Path) -> None:
    target = planner.expand_runtime_path(resource["config"]["source"]["path"], base_path)
    if target.is_symlink() or not target.is_dir():
        raise RestoreLiveError(f"managed archive target must be a prepared real directory: {target}")
    if next(target.iterdir(), None) is not None:
        raise RestoreLiveError(f"managed archive target must be empty before restore: {target}")
    parent = target.parent
    target.rmdir()
    restored = restore_stage._extract_tar_safely(backup_set / artifact["relative_path"], parent, expected_root=target.name)
    if restored <= 0 or not target.is_dir() or target.is_symlink():
        raise RestoreLiveError(f"managed archive restore produced no usable target: {target}")


def _wait_postgres(service: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _run(["docker", "exec", service, "pg_isready", "-U", "postgres", "-d", "postgres"]).returncode == 0:
            return
        time.sleep(2)
    raise RestoreLiveError(f"PostgreSQL service did not become ready: {service}")


def _restore_postgres(backup_set: Path, artifact: dict, resource: dict, stacks_root: Path, manifest: dict, values: dict[str, str]) -> int:
    source = resource["config"]["source"]
    service = source["service"]
    db_name = planner.require_env_value(values, source["database_env"], label="PostgreSQL database")
    user = planner.require_env_value(values, source["user_env"], label="PostgreSQL application role")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", db_name) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", user):
        raise RestoreLiveError("unsafe PostgreSQL database/role identifier")
    stack_dir = stacks_root / manifest["directory"]
    if not (stack_dir / "02-postgres.sh").is_file():
        raise RestoreLiveError("postgres-custom-dump restore requires stack-owned 02-postgres.sh bootstrap")
    _require_ok(_run(["bash", "./02-postgres.sh"], cwd=stack_dir), "PostgreSQL restore bootstrap")
    _wait_postgres(service)
    with (backup_set / artifact["relative_path"]).open("rb") as handle:
        cp = subprocess.run(
            ["docker", "exec", "-i", service, "pg_restore", "--no-owner", "--no-privileges", f"--role={user}", "-U", "postgres", "-d", db_name],
            stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    _require_ok(cp, "PostgreSQL pg_restore")
    count_cp = _run(["docker", "exec", "-i", service, "psql", "-At", "-U", "postgres", "-d", db_name, "-c", "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"])
    _require_ok(count_cp, "PostgreSQL restored table count")
    try:
        count = int(count_cp.stdout.decode().strip())
    except ValueError as exc:
        raise RestoreLiveError("invalid PostgreSQL restored table count") from exc
    if count <= 0:
        raise RestoreLiveError("PostgreSQL restore produced no application tables")
    return count


def _restore_gitea(backup_set: Path, artifact: dict, base_path: Path, values: dict[str, str]) -> tuple[int, int]:
    data = base_path / "service_-_gitea" / "data"
    if not data.is_dir() or data.is_symlink():
        raise RestoreLiveError("Gitea prepare did not create a valid runtime data directory")
    if any(data.iterdir()):
        raise RestoreLiveError("Gitea runtime data must be empty before native dump restore")
    with tempfile.TemporaryDirectory(prefix="gitea-restore-", dir=base_path) as tmp_name:
        extracted = Path(tmp_name)
        stack4_restore_verify.safe_extract_gitea_dump(backup_set / artifact["relative_path"], extracted)
        dump_data = extracted / "data"
        dump_repos = extracted / "repos"
        if not dump_data.is_dir() or not dump_repos.is_dir():
            raise RestoreLiveError("Gitea native dump is missing data/ or repos/")
        restore_managed._copy_tree_contents(dump_data, data, skip_names={"gitea.db"})
        repo_target = data / "git" / "repositories"
        repo_target.mkdir(parents=True, exist_ok=True)
        restore_managed._copy_tree_contents(dump_repos, repo_target)
        tables, _ = stack4_restore_verify.restore_sqlite(extracted / "gitea-db.sql", data / "gitea.db")
    repositories = stack4_restore_verify.find_bare_repositories(data / "git" / "repositories")
    for repo in repositories:
        stack4_restore_verify.verify_repository(repo)
    uid = int(planner.require_env_value(values, "GITEA_UID", label="GITEA_UID"))
    gid = int(planner.require_env_value(values, "GITEA_GID", label="GITEA_GID"))
    restore_managed._chown_tree(data, uid, gid)
    if tables <= 0 or not repositories:
        raise RestoreLiveError("Gitea restore produced incomplete durable state")
    return tables, len(repositories)


def _restore_managed(backup_set: Path, metadata: dict, stacks_root: Path, base_path: Path, manifests: dict[int, dict], values: dict[str, str]) -> tuple[int, int, int]:
    pg_tables = gitea_tables = gitea_repos = 0
    for artifact in metadata.get("artifacts", []):
        if artifact.get("restore_phase") != "post-prepare-pre-deploy":
            continue
        sid = artifact["stack_id"]
        resource = _find_resource(manifests, sid, artifact["resource_id"])
        strategy = artifact["strategy"]
        if strategy == "archive":
            _restore_managed_archive(backup_set, artifact, resource, base_path)
        elif strategy == "postgres-custom-dump":
            pg_tables += _restore_postgres(backup_set, artifact, resource, stacks_root, manifests[sid], values)
        elif strategy == "gitea-native-dump":
            tables, repos = _restore_gitea(backup_set, artifact, base_path, values)
            gitea_tables += tables
            gitea_repos += repos
        else:
            raise RestoreLiveError(f"unsupported managed restore strategy: {strategy}")
    return pg_tables, gitea_tables, gitea_repos


def _restore_external_git(metadata: dict, stacks_root: Path, manifests: dict[int, dict]) -> int:
    count = 0
    for prerequisite in metadata.get("prerequisites", []):
        if prerequisite.get("kind") != "EXTERNAL":
            continue
        if prerequisite.get("strategy") != "git":
            raise RestoreLiveError(f"unsupported external prerequisite strategy: {prerequisite.get('strategy')}")
        sid = prerequisite["stack_id"]
        stack_dir = stacks_root / manifests[sid]["directory"]
        if not (stack_dir / "04-gitmem.sh").is_file():
            raise RestoreLiveError("git externalization restore requires stack-owned 04-gitmem.sh hook")
        _require_ok(_run(["bash", "./04-gitmem.sh"], cwd=stack_dir), f"stack{sid} external Git restore")
        count += 1
    return count


def _install(stacks_root: Path, selectors: list[int] | tuple[int, ...], *, reconcile: bool = False, label: str) -> None:
    try:
        restore_compat.install_with_readiness_compat(stacks_root, selectors, reconcile=reconcile, label=label)
    except restore_compat.RestoreCompatibilityError as exc:
        raise RestoreLiveError(str(exc)) from exc


def _validate_execution_environment(confirm_clean_target: bool) -> None:
    if not confirm_clean_target:
        raise RestoreLiveError("real restore requires explicit clean-target confirmation")
    if os.geteuid() != 0:
        raise RestoreLiveError("real restore requires root")
    if shutil.which("docker") is None or shutil.which("git") is None:
        raise RestoreLiveError("docker and git are required")


def _prepare_restore_context(backup_set: Path) -> RestoreContext:
    plan_obj = restore_all.plan_restore_all(backup_set)
    metadata = restore_all.read_completed_backup_set(backup_set)
    manifests = planner.load_manifests()
    env_source, values = _read_env_artifact(backup_set, metadata)
    stacks_root = _absolute_safe_path(values, "STACKS_ROOT")
    base_path = _absolute_safe_path(values, "BASE_PATH")
    recovery_root = restore_all.PROJECT_ROOT.resolve()
    target_root = stacks_root.resolve()
    if recovery_root == target_root or target_root in recovery_root.parents or recovery_root in target_root.parents:
        raise RestoreLiveError("recovery tooling must run from a checkout outside STACKS_ROOT")
    return RestoreContext(backup_set, metadata, plan_obj.source_commit, tuple(plan_obj.resolved_stacks), manifests, env_source, values, stacks_root, base_path)


def _materialize_restore_target(context: RestoreContext) -> tuple[dict[int, dict], dict]:
    require_clean_target(context.stacks_root, context.base_path, context.manifests, context.plan)
    _materialize_source(context.source_commit, context.stacks_root)
    _copy_env(context.env_source, context.stacks_root)
    target_manifests = _load_target_manifests(context.stacks_root, context.plan)
    lifecycle = _load_target_lifecycle(context.stacks_root)
    for sid in context.plan:
        if target_manifests[sid].get("directory") != context.manifests[sid].get("directory"):
            raise RestoreLiveError(f"recorded source/current recovery contract directory drift for stack{sid}")
    context.base_path.mkdir(parents=True, exist_ok=True)
    _restore_preprepare_archives(context.backup_set, context.metadata, context.base_path, target_manifests)
    return target_manifests, lifecycle


def _partition_external_stacks(metadata: dict, plan: tuple[int, ...]) -> tuple[list[int], list[int]]:
    external = {p["stack_id"] for p in metadata.get("prerequisites", []) if p.get("kind") == "EXTERNAL"}
    return [sid for sid in plan if sid not in external], [sid for sid in plan if sid in external]


def _execute_restore_pipeline(context: RestoreContext, target_manifests: dict[int, dict], lifecycle: dict) -> tuple[int, int, int, int]:
    base_stacks, external_stacks = _partition_external_stacks(context.metadata, context.plan)
    _run_lifecycle_commands(context.stacks_root, lifecycle, target_manifests, base_stacks, "prepare")
    pg_tables, gitea_tables, gitea_repos = _restore_managed(context.backup_set, context.metadata, context.stacks_root, context.base_path, target_manifests, context.values)
    _install(context.stacks_root, base_stacks, label="base restore deployment")

    _run_lifecycle_commands(context.stacks_root, lifecycle, target_manifests, external_stacks, "prepare")
    external_restored = _restore_external_git(context.metadata, context.stacks_root, target_manifests)
    for sid in external_stacks:
        _install(context.stacks_root, [sid], label=f"stack{sid} restore deployment")
    _install(context.stacks_root, context.plan, reconcile=True, label="final restore READY/VERIFY/reconcile")
    return pg_tables, gitea_tables, gitea_repos, external_restored


def execute_restore_all(backup_set: Path, *, confirm_clean_target: bool = False) -> RestoreLiveResult:
    _validate_execution_environment(confirm_clean_target)
    context = _prepare_restore_context(backup_set)
    target_manifests, lifecycle = _materialize_restore_target(context)
    pg_tables, gitea_tables, gitea_repos, external_restored = _execute_restore_pipeline(context, target_manifests, lifecycle)
    return RestoreLiveResult(
        backup_set=context.backup_set,
        source_commit=context.source_commit,
        stacks_root=context.stacks_root,
        base_path=context.base_path,
        resolved_stacks=context.plan,
        postgres_tables=pg_tables,
        gitea_tables=gitea_tables,
        gitea_repositories=gitea_repos,
        external_git_restored=external_restored,
    )
