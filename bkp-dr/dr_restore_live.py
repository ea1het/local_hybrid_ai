#!/usr/bin/env python3
"""Clean-target destructive restore executor for a complete DR recovery point.

This module does not wipe anything. It refuses to run unless the target encoded
in the protected operational environment is clean. A separate operator step is
responsible for stopping/removing the previous platform.

Recovery tooling runs from a separate checkout. The recorded source commit is
materialized into STACKS_ROOT and becomes the platform being recovered.
"""
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

import dr
import dr_restore_all
import dr_restore_managed
import dr_restore_stage
import dr_stack4_restore_verify


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


def _run(cmd: list[str], *, cwd: Path | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _require_ok(cp: subprocess.CompletedProcess[bytes], label: str) -> None:
    if cp.returncode == 0:
        return
    detail = (cp.stderr or cp.stdout).decode("utf-8", errors="replace").strip()
    if len(detail) > 2000:
        detail = "..." + detail[-2000:]
    raise RestoreLiveError(f"{label} failed: {detail or 'no diagnostic output'}")


def _read_env_artifact(backup_set: Path, metadata: dict) -> tuple[Path, dict[str, str]]:
    matches = [
        a for a in metadata.get("global_artifacts", [])
        if a.get("resource_id", a.get("id")) == "operational-env"
    ]
    if len(matches) != 1:
        raise RestoreLiveError("backup set must contain exactly one operational-env global artifact")
    env_path = backup_set / matches[0]["relative_path"]
    if not env_path.is_file() or env_path.is_symlink():
        raise RestoreLiveError("operational environment artifact is missing or invalid")
    values = dr.read_dotenv_presence(env_path)
    return env_path, values


def _absolute_safe_path(values: dict[str, str], key: str) -> Path:
    value = dr.require_env_value(values, key, label=key)
    path = Path(value)
    if not path.is_absolute() or path == Path("/"):
        raise RestoreLiveError(f"{key} must be an absolute non-root path")
    return path


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and next(path.iterdir(), None) is None


def _require_clean_path(path: Path, label: str) -> None:
    if not path.exists():
        return
    if _is_empty_dir(path):
        return
    raise RestoreLiveError(f"{label} must be absent or an empty real directory: {path}")


def _owned_objects(manifests: dict[int, dict], plan: list[int]) -> tuple[set[str], set[str], set[str]]:
    containers: set[str] = set()
    volumes: set[str] = set()
    networks: set[str] = set()
    for sid in plan:
        for owned in manifests[sid].get("owns", []):
            if owned.startswith("container:"):
                containers.add(owned.split(":", 1)[1])
            elif owned.startswith("volume:"):
                volumes.add(owned.split(":", 1)[1])
            elif owned.startswith("docker-network:"):
                networks.add(owned.split(":", 1)[1])
    return containers, volumes, networks


def require_clean_target(stacks_root: Path, base_path: Path, manifests: dict[int, dict], plan: list[int]) -> None:
    if stacks_root == base_path or stacks_root in base_path.parents or base_path in stacks_root.parents:
        raise RestoreLiveError("STACKS_ROOT and BASE_PATH must be disjoint paths")
    _require_clean_path(stacks_root, "STACKS_ROOT")
    _require_clean_path(base_path, "BASE_PATH")
    containers, volumes, networks = _owned_objects(manifests, plan)
    for name in sorted(containers):
        if _run(["docker", "inspect", name]).returncode == 0:
            raise RestoreLiveError(f"clean-target preflight found existing platform container: {name}")
    for name in sorted(volumes):
        if _run(["docker", "volume", "inspect", name]).returncode == 0:
            raise RestoreLiveError(f"clean-target preflight found existing platform volume: {name}")
    for name in sorted(networks):
        if _run(["docker", "network", "inspect", name]).returncode == 0:
            raise RestoreLiveError(f"clean-target preflight found existing platform network: {name}")


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
        cp = _run([
            "git", "archive", "--format=tar", "--output", str(tar_path), commit
        ], cwd=dr_restore_all.PROJECT_ROOT)
        _require_ok(cp, "materialize recorded source commit")
        dr_restore_stage._extract_tar_safely(tar_path, stacks_root)
    finally:
        tar_path.unlink(missing_ok=True)


def _copy_env(env_source: Path, stacks_root: Path) -> None:
    target = stacks_root / ".env"
    dr_restore_stage._copy_private(env_source, target)
    if stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise RestoreLiveError("restored operational .env does not have mode 0600")


def _load_target_manifests(stacks_root: Path, plan: list[int]) -> dict[int, dict]:
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
            cp = _run(actual, cwd=stacks_root / manifests[sid]["directory"])
            _require_ok(cp, f"stack{sid} {phase}")


def _restore_preprepare_archives(backup_set: Path, metadata: dict, base_path: Path, manifests: dict[int, dict]) -> int:
    count = 0
    for artifact in metadata.get("artifacts", []):
        if artifact.get("restore_phase") != "pre-prepare":
            continue
        if artifact.get("strategy") != "archive":
            raise RestoreLiveError(f"unsupported pre-prepare strategy: {artifact.get('strategy')}")
        sid = artifact["stack_id"]
        resource = next((r for r in manifests[sid].get("recovery", {}).get("resources", []) if r.get("id") == artifact["resource_id"]), None)
        if resource is None:
            raise RestoreLiveError(f"missing target recovery resource stack{sid}/{artifact['resource_id']}")
        raw = resource["config"]["source"]["path"]
        target = dr.expand_runtime_path(raw, base_path)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RestoreLiveError(f"pre-prepare archive target already exists: {target}")
        archive = backup_set / artifact["relative_path"]
        restored = dr_restore_stage._extract_tar_safely(archive, parent, expected_root=target.name)
        if restored <= 0 or not target.is_dir():
            raise RestoreLiveError(f"archive restore produced no usable target: {target}")
        count += 1
    return count


def _restore_managed_archive(backup_set: Path, artifact: dict, resource: dict, base_path: Path) -> None:
    raw = resource["config"]["source"]["path"]
    target = dr.expand_runtime_path(raw, base_path)
    if target.is_symlink() or not target.is_dir():
        raise RestoreLiveError(f"managed archive target must be a prepared real directory: {target}")
    if next(target.iterdir(), None) is not None:
        raise RestoreLiveError(f"managed archive target must be empty before restore: {target}")
    parent = target.parent
    target.rmdir()
    archive = backup_set / artifact["relative_path"]
    restored = dr_restore_stage._extract_tar_safely(archive, parent, expected_root=target.name)
    if restored <= 0 or not target.is_dir() or target.is_symlink():
        raise RestoreLiveError(f"managed archive restore produced no usable target: {target}")


def _wait_postgres(service: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cp = _run(["docker", "exec", service, "pg_isready", "-U", "postgres", "-d", "postgres"])
        if cp.returncode == 0:
            return
        time.sleep(2)
    raise RestoreLiveError(f"PostgreSQL service did not become ready: {service}")


def _restore_postgres(backup_set: Path, artifact: dict, resource: dict, stacks_root: Path, manifest: dict, values: dict[str, str]) -> int:
    source = resource["config"]["source"]
    service = source["service"]
    db_name = dr.require_env_value(values, source["database_env"], label="PostgreSQL database")
    user = dr.require_env_value(values, source["user_env"], label="PostgreSQL application role")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", db_name) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", user):
        raise RestoreLiveError("unsafe PostgreSQL database/role identifier")
    stack_dir = stacks_root / manifest["directory"]
    bootstrap = stack_dir / "02-postgres.sh"
    if not bootstrap.is_file():
        raise RestoreLiveError("postgres-custom-dump restore requires stack-owned 02-postgres.sh bootstrap")
    cp = _run(["bash", "./02-postgres.sh"], cwd=stack_dir)
    _require_ok(cp, "PostgreSQL restore bootstrap")
    _wait_postgres(service)
    dump = backup_set / artifact["relative_path"]
    with dump.open("rb") as handle:
        cp2 = subprocess.run(
            [
                "docker", "exec", "-i", service,
                "pg_restore", "--no-owner", "--no-privileges", f"--role={user}",
                "-U", "postgres", "-d", db_name,
            ],
            stdin=handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    _require_ok(cp2, "PostgreSQL pg_restore")
    cp3 = _run([
        "docker", "exec", "-i", service, "psql", "-At", "-U", "postgres", "-d", db_name,
        "-c", "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"
    ])
    _require_ok(cp3, "PostgreSQL restored table count")
    try:
        count = int(cp3.stdout.decode().strip())
    except ValueError as exc:
        raise RestoreLiveError("invalid PostgreSQL restored table count") from exc
    if count <= 0:
        raise RestoreLiveError("PostgreSQL restore produced no application tables")
    return count


def _restore_gitea(backup_set: Path, artifact: dict, base_path: Path, values: dict[str, str]) -> tuple[int, int]:
    service_root = base_path / "service_-_gitea"
    data = service_root / "data"
    if not data.is_dir() or data.is_symlink():
        raise RestoreLiveError("Gitea prepare did not create a valid runtime data directory")
    if any(data.iterdir()):
        raise RestoreLiveError("Gitea runtime data must be empty before native dump restore")
    archive = backup_set / artifact["relative_path"]
    with tempfile.TemporaryDirectory(prefix="gitea-restore-", dir=base_path) as tmp_name:
        extracted = Path(tmp_name)
        dr_stack4_restore_verify.safe_extract_gitea_dump(archive, extracted)
        dump_data = extracted / "data"
        dump_repos = extracted / "repos"
        if not dump_data.is_dir() or not dump_repos.is_dir():
            raise RestoreLiveError("Gitea native dump is missing data/ or repos/")
        dr_restore_managed._copy_tree_contents(dump_data, data, skip_names={"gitea.db"})
        repo_target = data / "git" / "repositories"
        repo_target.mkdir(parents=True, exist_ok=True)
        dr_restore_managed._copy_tree_contents(dump_repos, repo_target)
        db_path = data / "gitea.db"
        tables, _ = dr_stack4_restore_verify.restore_sqlite(extracted / "gitea-db.sql", db_path)
    repositories = dr_stack4_restore_verify.find_bare_repositories(data / "git" / "repositories")
    for repo in repositories:
        dr_stack4_restore_verify.verify_repository(repo)
    uid = int(dr.require_env_value(values, "GITEA_UID", label="GITEA_UID"))
    gid = int(dr.require_env_value(values, "GITEA_GID", label="GITEA_GID"))
    dr_restore_managed._chown_tree(data, uid, gid)
    if tables <= 0 or not repositories:
        raise RestoreLiveError("Gitea restore produced incomplete durable state")
    return tables, len(repositories)


def _restore_managed(backup_set: Path, metadata: dict, stacks_root: Path, base_path: Path, manifests: dict[int, dict], values: dict[str, str]) -> tuple[int, int, int]:
    pg_tables = 0
    gitea_tables = 0
    gitea_repos = 0
    for artifact in metadata.get("artifacts", []):
        if artifact.get("restore_phase") != "post-prepare-pre-deploy":
            continue
        sid = artifact["stack_id"]
        resource = next((r for r in manifests[sid].get("recovery", {}).get("resources", []) if r.get("id") == artifact["resource_id"]), None)
        if resource is None:
            raise RestoreLiveError(f"missing recovery resource for stack{sid}/{artifact['resource_id']}")
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
        hook = stack_dir / "04-gitmem.sh"
        if not hook.is_file():
            raise RestoreLiveError("git externalization restore requires stack-owned 04-gitmem.sh hook")
        cp = _run(["bash", "./04-gitmem.sh"], cwd=stack_dir)
        _require_ok(cp, f"stack{sid} external Git restore")
        count += 1
    return count


def _install(stacks_root: Path, selectors: list[int], *, reconcile: bool = False, label: str) -> None:
    if not selectors:
        return
    cmd = ["python3", "install.py", *[str(sid) for sid in selectors]]
    if reconcile:
        cmd.append("--reconcile")
    cmd.append("--yes")
    cp = _run(cmd, cwd=stacks_root)
    _require_ok(cp, label)


def execute_restore_all(backup_set: Path, *, confirm_clean_target: bool = False) -> RestoreLiveResult:
    if not confirm_clean_target:
        raise RestoreLiveError("real restore requires explicit clean-target confirmation")
    if os.geteuid() != 0:
        raise RestoreLiveError("real restore requires root")
    if shutil.which("docker") is None or shutil.which("git") is None:
        raise RestoreLiveError("docker and git are required")

    plan_obj = dr_restore_all.plan_restore_all(backup_set)
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    manifests = dr.load_manifests()
    plan = list(plan_obj.resolved_stacks)
    env_source, values = _read_env_artifact(backup_set, metadata)
    stacks_root = _absolute_safe_path(values, "STACKS_ROOT")
    base_path = _absolute_safe_path(values, "BASE_PATH")

    recovery_root = dr_restore_all.PROJECT_ROOT.resolve()
    target_root = stacks_root.resolve()
    if recovery_root == target_root or target_root in recovery_root.parents or recovery_root in target_root.parents:
        raise RestoreLiveError("recovery tooling must run from a checkout outside STACKS_ROOT")

    require_clean_target(stacks_root, base_path, manifests, plan)

    _materialize_source(plan_obj.source_commit, stacks_root)
    _copy_env(env_source, stacks_root)
    target_manifests = _load_target_manifests(stacks_root, plan)
    lifecycle = _load_target_lifecycle(stacks_root)

    for sid in plan:
        if target_manifests[sid].get("directory") != manifests[sid].get("directory"):
            raise RestoreLiveError(f"recorded source/current recovery contract directory drift for stack{sid}")

    base_path.mkdir(parents=True, exist_ok=True)
    _restore_preprepare_archives(backup_set, metadata, base_path, target_manifests)

    external_stack_ids = {
        p["stack_id"] for p in metadata.get("prerequisites", []) if p.get("kind") == "EXTERNAL"
    }
    base_stack_ids = [sid for sid in plan if sid not in external_stack_ids]
    external_ordered = [sid for sid in plan if sid in external_stack_ids]

    # Prepare and recover durable state for the base closure first. Keeping the
    # external consumer unprepared prevents provider reconciliation from starting
    # it before its externalized state has been adopted.
    _run_lifecycle_commands(stacks_root, lifecycle, target_manifests, base_stack_ids, "prepare")
    pg_tables, gitea_tables, gitea_repos = _restore_managed(
        backup_set, metadata, stacks_root, base_path, target_manifests, values
    )
    _install(stacks_root, base_stack_ids, label="base restore deployment")

    _run_lifecycle_commands(stacks_root, lifecycle, target_manifests, external_ordered, "prepare")
    external_restored = _restore_external_git(metadata, stacks_root, target_manifests)
    for sid in external_ordered:
        _install(stacks_root, [sid], label=f"stack{sid} restore deployment")

    _install(stacks_root, plan, reconcile=True, label="final restore READY/VERIFY/reconcile")

    return RestoreLiveResult(
        backup_set=backup_set,
        source_commit=plan_obj.source_commit,
        stacks_root=stacks_root,
        base_path=base_path,
        resolved_stacks=tuple(plan),
        postgres_tables=pg_tables,
        gitea_tables=gitea_tables,
        gitea_repositories=gitea_repos,
        external_git_restored=external_restored,
    )
