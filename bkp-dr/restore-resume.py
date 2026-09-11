#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import dr
import dr_restore_all
import dr_restore_compat
import dr_restore_live
import dr_stack4_restore_verify


class ResumeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def require_ok(cp: subprocess.CompletedProcess[str], label: str) -> str:
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        if len(detail) > 2000:
            detail = "..." + detail[-2000:]
        raise ResumeError(f"{label} failed: {detail or 'no diagnostic output'}")
    return cp.stdout.strip()


def read_env_artifact(backup_set: Path) -> tuple[Path, dict[str, str]]:
    """Read the canonical global operational-env artifact from a backup set."""
    metadata = dr_restore_all.read_completed_backup_set(backup_set)
    matches = [
        artifact
        for artifact in metadata.get("global_artifacts", [])
        if artifact.get("resource_id") == "operational-env"
    ]
    if len(matches) != 1:
        raise ResumeError("backup set must contain exactly one operational-env global artifact")
    env_path = backup_set / matches[0]["relative_path"]
    if not env_path.is_file() or env_path.is_symlink():
        raise ResumeError("operational environment artifact is missing or invalid")
    return env_path, dr.read_dotenv_presence(env_path)


def verify_source(backup_set: Path, stacks_root: Path, source_commit: str) -> None:
    target = stacks_root / "install.py"
    if not target.is_file() or target.is_symlink():
        raise ResumeError("restored source is incomplete: install.py missing")

    # Compare exact bytes. The generic text helper intentionally strips stdout,
    # which is correct for scalar command results but corrupts file-content
    # comparison by removing the trailing newline from `git show <ref>:path`.
    cp = subprocess.run(
        ["git", "show", f"{source_commit}:install.py"],
        cwd=dr_restore_all.PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout).decode("utf-8", errors="replace").strip()
        if len(detail) > 2000:
            detail = "..." + detail[-2000:]
        raise ResumeError(f"recorded source lookup failed: {detail or 'no diagnostic output'}")

    expected = cp.stdout
    actual = target.read_bytes()
    if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
        raise ResumeError("restored source no longer matches backup source commit")


def verify_env(env_artifact: Path, stacks_root: Path) -> None:
    target = stacks_root / ".env"
    if not target.is_file() or target.is_symlink():
        raise ResumeError("restored operational .env missing")
    if sha256(target) != sha256(env_artifact):
        raise ResumeError("restored operational .env differs from recovery point")
    if (target.stat().st_mode & 0o777) != 0o600:
        raise ResumeError("restored operational .env mode is not 0600")


def verify_prepared(stacks_root: Path, resolved: list[int]) -> None:
    for sid in resolved:
        matches = list(stacks_root.glob(f"stack{sid}_-*/.lock"))
        if len(matches) != 1:
            raise ResumeError(f"stack{sid} is not unambiguously PREPARED")


def postgres_table_count(values: dict[str, str]) -> int:
    db = dr.require_env_value(values, "LITELLM_DB_NAME", label="LITELLM_DB_NAME")
    cp = run([
        "docker", "exec", "litellm-postgres", "psql", "-At", "-U", "postgres", "-d", db,
        "-c", "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');",
    ])
    text = require_ok(cp, "LiteLLM PostgreSQL verification")
    try:
        count = int(text)
    except ValueError as exc:
        raise ResumeError("invalid LiteLLM PostgreSQL table count") from exc
    if count <= 0:
        raise ResumeError("LiteLLM PostgreSQL restored state is empty")
    return count


def gitea_state(base_path: Path) -> tuple[int, int]:
    db = base_path / "service_-_gitea" / "data" / "gitea.db"
    if not db.is_file() or db.is_symlink():
        raise ResumeError("restored Gitea SQLite database missing")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = int(con.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0])
    finally:
        con.close()
    repo_root = base_path / "service_-_gitea" / "data" / "git" / "repositories"
    repos = dr_stack4_restore_verify.find_bare_repositories(repo_root)
    for repo in repos:
        dr_stack4_restore_verify.verify_repository(repo)
    if tables <= 0 or not repos:
        raise ResumeError("restored Gitea durable state is incomplete")
    return tables, len(repos)


def verify_memory(base_path: Path, values: dict[str, str]) -> str:
    service = dr.require_env_value(values, "HERMES_MEMORY_SERVICE", label="HERMES_MEMORY_SERVICE")
    branch = dr.require_env_value(values, "GITMEM_BRANCH", label="GITMEM_BRANCH")
    repo = base_path / service / "data"
    cp = run(["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", "HEAD"])
    head = require_ok(cp, "portable memory HEAD")
    cp2 = run(["git", "-c", f"safe.directory={repo}", "-C", str(repo), "status", "--porcelain"])
    if require_ok(cp2, "portable memory status"):
        raise ResumeError("portable memory working tree is not clean")
    cp3 = run(["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", f"refs/remotes/origin/{branch}"])
    if require_ok(cp3, "portable memory remote tracking HEAD") != head:
        raise ResumeError("portable memory is not aligned with remote tracking branch")
    return head


def verify_bootstrap(source: Path, base_path: Path, values: dict[str, str]) -> None:
    service = dr.require_env_value(values, "MEMORY_SYNC_SERVICE", label="MEMORY_SYNC_SERVICE")
    target = base_path / service / "ssh"
    for name in ("ssh_config", "id_ed25519", "known_hosts"):
        src = source / name
        dst = target / name
        if not src.is_file() or src.is_symlink() or not dst.is_file() or dst.is_symlink():
            raise ResumeError(f"memory-sync SSH material missing: {name}")
        if sha256(src) != sha256(dst):
            raise ResumeError(f"memory-sync SSH material differs from bootstrap: {name}")


def persist_git_memory_intent(base_path: Path, values: dict[str, str]) -> None:
    """Persist Stack6 operator intent independently of the Git provider implementation.

    The memory-sync sidecar may target local Gitea or any other configured Git
    service. Recovery therefore must not infer a Stack4 dependency merely to set
    the durable Stack6 desired-state marker.
    """
    service = dr.require_env_value(values, "MEMORY_SYNC_SERVICE", label="MEMORY_SYNC_SERVICE")
    uid_text = dr.require_env_value(values, "HERMES_UID", label="HERMES_UID")
    gid_text = dr.require_env_value(values, "HERMES_GID", label="HERMES_GID")
    try:
        uid = int(uid_text)
        gid = int(gid_text)
    except ValueError as exc:
        raise ResumeError("invalid HERMES_UID/HERMES_GID for Git-memory desired state") from exc
    if uid < 0 or gid < 0:
        raise ResumeError("invalid negative HERMES_UID/HERMES_GID")

    root = base_path / service
    if root.is_symlink():
        raise ResumeError("memory-sync runtime root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    target = root / "desired-state"
    if target.exists() and target.is_symlink():
        raise ResumeError("Git-memory desired-state must not be a symlink")

    temp = root / f".desired-state.restore-{os.getpid()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("enabled\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temp, uid, gid)
            os.chmod(temp, 0o640)
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()
    except OSError as exc:
        raise ResumeError(f"cannot persist Git-memory desired state: {exc}") from exc

    if target.read_text(encoding="utf-8") != "enabled\n":
        raise ResumeError("Git-memory desired-state verification failed")
    if (target.stat().st_mode & 0o777) != 0o640:
        raise ResumeError("Git-memory desired-state mode is not 0640")


def enable_memory_sync(stacks_root: Path, base_path: Path, values: dict[str, str]) -> None:
    persist_git_memory_intent(base_path, values)
    container = dr.require_env_value(values, "MEMORY_SYNC_CONTAINER", label="MEMORY_SYNC_CONTAINER")
    stack_dir = stacks_root / "stack6_-_hermes"
    cp = run(["docker", "compose", "--profile", "git-memory", "up", "-d", "--build", "hermes-memory-sync"], cwd=stack_dir)
    require_ok(cp, "Stack6 memory-sync profile restore")
    dr_restore_compat.wait_required_runtime(stacks_root, [6], timeout=240)
    inspect = run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    if require_ok(inspect, "memory-sync container status") != "true":
        raise ResumeError("memory-sync container is not running")


def resume(backup_set: Path, bootstrap: Path) -> dict[str, object]:
    plan = dr_restore_all.plan_restore_all(backup_set)
    env_artifact, values = read_env_artifact(backup_set)
    stacks_root = dr_restore_live._absolute_safe_path(values, "STACKS_ROOT")
    base_path = dr_restore_live._absolute_safe_path(values, "BASE_PATH")
    resolved = list(plan.resolved_stacks)

    verify_source(backup_set, stacks_root, plan.source_commit)
    verify_env(env_artifact, stacks_root)
    verify_prepared(stacks_root, resolved)
    pg_tables = postgres_table_count(values)
    gitea_tables, gitea_repos = gitea_state(base_path)
    memory_head = verify_memory(base_path, values)
    verify_bootstrap(bootstrap, base_path, values)

    # The failed clean restore stopped at the historical installer's transient
    # post-reconcile readiness race. First prove the already-created runtime can
    # converge, then perform the final generic reconcile/verify with a narrow
    # compatibility adapter that accepts only that exact historical failure.
    dr_restore_compat.wait_required_runtime(stacks_root, resolved, timeout=240)
    dr_restore_compat.install_with_readiness_compat(
        stacks_root, resolved, reconcile=True, label="final restore READY/VERIFY/reconcile"
    )
    enable_memory_sync(stacks_root, base_path, values)
    dr_restore_compat.install_with_readiness_compat(
        stacks_root, resolved, reconcile=False, label="post-resume final verification"
    )

    return {
        "backup_set": str(backup_set),
        "source_commit": plan.source_commit,
        "resolved_stacks": resolved,
        "postgres_tables": pg_tables,
        "gitea_tables": gitea_tables,
        "gitea_repositories": gitea_repos,
        "memory_head": memory_head,
        "memory_sync_enabled": True,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a clean-target restore stopped at the historical post-reconcile readiness race")
    parser.add_argument("backup_set")
    parser.add_argument("--memory-sync-ssh-bootstrap", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = resume(Path(args.backup_set), Path(args.memory_sync_ssh_bootstrap))
    except (ResumeError, dr_restore_compat.RestoreCompatibilityError, dr_restore_all.RestoreAllError, dr_restore_live.RestoreLiveError, dr.RecoveryError, OSError, ValueError) as exc:
        print(f"RESTORE RESUME ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("RESTORE ALL RESUME: PASS")
        print(f"- source commit: {result['source_commit']}")
        print(f"- resolved stacks: {','.join(str(v) for v in result['resolved_stacks'])}")
        print(f"- LiteLLM PostgreSQL tables: {result['postgres_tables']}")
        print(f"- Gitea SQLite tables: {result['gitea_tables']}")
        print(f"- Gitea repositories: {result['gitea_repositories']}")
        print(f"- portable memory HEAD: {result['memory_head']}")
        print("- Stack6 memory-sync profile: running")
        print("- Stack6 Git-memory desired state: enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
