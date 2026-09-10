#!/usr/bin/env python3
"""Read-only DR verifier for Stack6 portable user memory.

Stack6/Hermes is intentionally reconstructable. The only durable application
state is the user-owned Git-backed memory contract: MEMORY.md and USER.md.
Everything else produced by Hermes, including SOUL.md, SQLite databases,
caches, packages, sessions, logs and the entire sandbox runtime, is disposable.

This verifier does not fetch, pull, commit, push, reset or modify the working
tree. It proves that the local externalized memory checkout is clean and aligned
with its configured remote-tracking branch.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import dr

ROOT = Path(__file__).resolve().parent
REQUIRED_FILES = ("MEMORY.md", "USER.md")


class Stack6VerifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Stack6MemoryVerification:
    working_tree: Path
    branch: str
    head: str
    required_files: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "stack": 6,
            "resource": "agent-portable-memory",
            "strategy": "git",
            "status": "PASS",
            "working_tree": str(self.working_tree),
            "branch": self.branch,
            "head": self.head,
            "required_files": list(self.required_files),
            "remote_url_displayed": False,
            "runtime_hermes_state_required": False,
            "soul_md_required": False,
            "sandbox_state_required": False,
        }


def run_git(working_tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={working_tree}", "-C", str(working_tree), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def require_git(working_tree: Path, *args: str, label: str) -> str:
    cp = run_git(working_tree, *args)
    if cp.returncode != 0:
        detail = cp.stderr.strip()
        if len(detail) > 1000:
            detail = "..." + detail[-1000:]
        raise Stack6VerifyError(f"{label} failed: {detail or 'no diagnostic output'}")
    return cp.stdout.strip()


def resolve_memory_tree(values: dict[str, str], base_path: Path) -> Path:
    service = dr.require_env_value(values, "HERMES_MEMORY_SERVICE", label="HERMES_MEMORY_SERVICE")
    if not service.startswith("service_-") or "/" in service or service in {"service_-", ".", ".."}:
        raise Stack6VerifyError("HERMES_MEMORY_SERVICE has an unsafe value")
    path = (base_path / service / "data").resolve()
    expected_root = base_path.resolve()
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise Stack6VerifyError("Hermes memory working tree resolves outside BASE_PATH") from exc
    return path


def verify_stack6_memory(env_path: Path = ROOT / ".env") -> Stack6MemoryVerification:
    values = dr.read_dotenv_presence(env_path)
    base_path = dr.resolve_base_path(values)
    repository = dr.require_env_value(values, "GITMEM_REPOSITORY", label="GITMEM_REPOSITORY")
    branch = dr.require_env_value(values, "GITMEM_BRANCH", label="GITMEM_BRANCH")
    working_tree = resolve_memory_tree(values, base_path)

    if not working_tree.is_dir():
        raise Stack6VerifyError(f"Git-backed memory working tree is missing: {working_tree}")
    git_dir = working_tree / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise Stack6VerifyError("Git-backed memory .git directory is missing or invalid")

    origin = require_git(working_tree, "remote", "get-url", "origin", label="origin lookup")
    if origin != repository:
        raise Stack6VerifyError("Git-backed memory origin does not match configured GITMEM_REPOSITORY")

    current_branch = require_git(working_tree, "branch", "--show-current", label="branch lookup")
    if current_branch != branch:
        raise Stack6VerifyError("Git-backed memory branch does not match configured GITMEM_BRANCH")

    for name in REQUIRED_FILES:
        path = working_tree / name
        if not path.is_file() or path.is_symlink():
            raise Stack6VerifyError(f"required portable-memory file is missing or invalid: {name}")
        cp = run_git(working_tree, "ls-files", "--error-unmatch", "--", name)
        if cp.returncode != 0:
            raise Stack6VerifyError(f"required portable-memory file is not tracked by Git: {name}")

    status = require_git(working_tree, "status", "--porcelain", label="working-tree status")
    if status:
        raise Stack6VerifyError("Git-backed memory working tree is not clean")

    local_head = require_git(working_tree, "rev-parse", "HEAD", label="local HEAD lookup")
    remote_ref = f"refs/remotes/origin/{branch}"
    remote_head = require_git(working_tree, "rev-parse", remote_ref, label="remote-tracking HEAD lookup")
    if local_head != remote_head:
        raise Stack6VerifyError("Git-backed memory local HEAD differs from its remote-tracking branch")

    return Stack6MemoryVerification(working_tree, branch, local_head, REQUIRED_FILES)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Stack6 externalized portable user memory for DR")
    parser.add_argument("--env", default=str(ROOT / ".env"), help="operational .env path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = verify_stack6_memory(Path(args.env))
    except (Stack6VerifyError, dr.RecoveryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("Stack6 portable-memory DR verification: PASS")
        print(f"- working tree: {result.working_tree}")
        print(f"- branch: {result.branch}")
        print(f"- HEAD: {result.head}")
        print(f"- required files: {', '.join(result.required_files)}")
        print("- remote URL: verified but not displayed")
        print("- Hermes runtime/SOUL.md/sandbox: not DR resources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
