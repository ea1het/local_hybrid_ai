#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Adopt an existing Git working tree as Hermes persistent memory.

The entrypoint validates the prepared stack and environment, examines
existing data for conflicts, and configures the dedicated memory checkout
without silently replacing divergent user content. It detects concurrent
changes to .env and .lock before committing modifications. Importing the
module does not touch Git or the filesystem."""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
from pathlib import Path, PurePosixPath

if __package__:
    from .stack_env import load_env
else:
    from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
MEMORY_FILES = ("MEMORY.md", "USER.md")


def log(message: str) -> None:
    """Print an indented progress message."""
    print(f"  {message}")


def step(message: str) -> None:
    """Print a section heading."""
    print(f"\n== {message}")


def fail(message: str) -> None:
    """Report a Git memory preparation error and exit."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*args: str, capture: bool = False, quiet: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run a command, with optional stdout capture or output suppression."""
    return subprocess.run(args, check=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None)


def git(tree: Path, *args: str, capture: bool = False, quiet: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run Git against a tree while explicitly marking it as safe."""
    return run("git", "-c", f"safe.directory={tree}", "-C", str(tree), *args, capture=capture, quiet=quiet)


def git_text(tree: Path, *args: str) -> str:
    """Return trimmed text output from a Git command."""
    return git(tree, *args, capture=True).stdout.decode().strip()


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path) -> bool:
    """Check that a path is a nonsymlink regular file."""
    return path.is_file() and not path.is_symlink()


def same_content(first: Path, second: Path) -> bool:
    """Compare the bytes of two files."""
    return first.read_bytes() == second.read_bytes()


def tracked_paths(tree: Path) -> list[str]:
    """List tracked paths using NUL-delimited Git output."""
    entries = git(tree, "ls-files", "-z", capture=True).stdout.split(b"\0")
    return sorted(os.fsdecode(entry) for entry in entries if entry)


def validate_static_path(tree: Path, relative: str) -> Path:
    """Reject unsafe or nonregular tracked paths before copying static content."""
    parts = PurePosixPath(relative).parts
    if not parts or any(part in (".", "..", ".git") for part in parts) or PurePosixPath(relative).is_absolute():
        fail(f"unsupported tracked static file: {relative} must be a regular file")
    current = tree
    for part in parts[:-1]:
        current /= part
        if not current.is_dir() or current.is_symlink():
            fail(f"unsupported tracked static file: {relative} must be a regular file")
    target = current / parts[-1]
    if not regular(target):
        fail(f"unsupported tracked static file: {relative} must be a regular file")
    return target


def validate_identity(tree: Path, repository: str, expected_branch: str) -> tuple[str, str]:
    """Verify remote, branch, and both tracked memory files."""
    origin = git_text(tree, "remote", "get-url", "origin")
    if not origin:
        fail("the working tree has no origin remote")
    if origin != repository:
        fail(f"unexpected origin: '{origin}' (expected '{repository}')")
    branch = git_text(tree, "branch", "--show-current")
    if branch != expected_branch:
        fail(f"unexpected active branch: '{branch}' (expected '{expected_branch}')")
    for name in MEMORY_FILES:
        if subprocess.run(["git", "-c", f"safe.directory={tree}", "-C", str(tree),
                           "ls-files", "--error-unmatch", "--", name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            fail(f"Git memory must track {name}")
        if not regular(tree / name):
            fail(f"the repository must contain {name} as a regular file")
    return origin, branch


def adopt(memory_root: Path, data: Path, legacy: Path, repository: str, branch: str, uid: int, gid: int) -> None:
    """Adopt validated Git metadata while preserving the persistent memory directory."""
    if (data / ".git").is_dir() and not (data / ".git").is_symlink():
        log("Existing working tree preserved")
        return
    if (data / ".git").exists() or (data / ".git").is_symlink():
        fail(f"{data}/.git exists but is not a regular directory")
    unexpected = sorted(entry.name for entry in data.iterdir() if entry.name not in MEMORY_FILES)
    if unexpected:
        fail(f"local memory contains unmanaged entries before Git adoption: {chr(10).join(unexpected)}")

    with tempfile.TemporaryDirectory(prefix=".gitmem-adopt.", dir=memory_root) as temporary:
        # Validate the clone and every content conflict before copying into persistent memory.
        clone = Path(temporary)
        log(f"Temporarily cloning {repository} ({branch}) to validate adoption")
        run("git", "clone", "--single-branch", "--branch", branch, "--", repository, str(clone))
        validate_identity(clone, repository, branch)
        static_files = []
        for relative in tracked_paths(clone):
            if relative in MEMORY_FILES:
                continue
            source = validate_static_path(clone, relative)
            target = data / relative
            if target.exists() or target.is_symlink():
                fail(f"unexpected local file conflicts with remote static file: {relative}")
            static_files.append((relative, source, target))

        actions = []
        for name in MEMORY_FILES:
            local = data / name
            remote = clone / name
            if same_content(local, remote):
                actions.append((name, "same"))
            elif local.stat().st_size == 0 and remote.stat().st_size > 0:
                actions.append((name, "copy"))
            elif local.stat().st_size > 0 and remote.stat().st_size == 0:
                actions.append((name, "preserve"))
            else:
                fail(f"{name}: local and remote content differ; resolve manually before enabling Git memory")
            active = remote if actions[-1][1] == "copy" else local
            old = legacy / name
            if old.is_file() and old.stat().st_size and not same_content(old, active):
                fail(f"{old} contains different memory. Resolve it deliberately before rerunning Git memory preparation")

        for relative, source, target in static_files:
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            os.chown(target.parent, uid, gid)
            shutil.copy2(source, target)
            log(f"{relative}: static file adopted from Git")
        for name, action in actions:
            if action == "copy":
                shutil.copyfile(clone / name, data / name)
                log(f"{name}: empty local file; remote content adopted")
            elif action == "same":
                log(f"{name}: local and remote content match")
            else:
                log(f"{name}: empty remote file; local content preserved as a pending change")
        shutil.move(str(clone / ".git"), str(data / ".git"))
        log("Git metadata adopted without replacing the persistent memory directory")


def changed_paths(tree: Path) -> list[str]:
    """List staged, unstaged, and untracked paths in a working tree."""
    changes = set()
    for args in (("diff", "--name-only", "-z"), ("diff", "--cached", "--name-only", "-z"),
                 ("ls-files", "--others", "--exclude-standard", "-z")):
        changes.update(os.fsdecode(path) for path in git(tree, *args, capture=True).stdout.split(b"\0") if path)
    return sorted(changes)


def main() -> None:
    """Validate prerequisites, adopt memory, and audit the resulting working tree."""
    if os.geteuid() != 0:
        fail("run this command as root")
    for command in ("git", "docker"):
        if shutil.which(command) is None:
            fail(f"missing required command: {command}")
    if not ENV_FILE.is_file():
        fail(f"missing {ENV_FILE}")
    if not LOCK_FILE.is_file():
        fail(f"Stack 60 is not prepared: missing {LOCK_FILE}; run ./local-ai stack-60 install first")
    env_before, lock_before = sha256(ENV_FILE), sha256(LOCK_FILE)
    env = load_env(ENV_FILE)
    required = ("BASE_PATH", "HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "HERMES_CONTAINER",
                "HERMES_UID", "HERMES_GID", "GITMEM_REPOSITORY", "GITMEM_BRANCH")
    for key in required:
        if not env.get(key):
            fail(f"missing {key} in {ENV_FILE}")
    base = env["BASE_PATH"]
    if not base.startswith("/"):
        fail("BASE_PATH must be an absolute path")
    if base.rstrip("/") == "":
        fail("BASE_PATH cannot be /")
    service, memory_service = env["HERMES_SERVICE"], env["HERMES_MEMORY_SERVICE"]
    for key, value in (("HERMES_SERVICE", service), ("HERMES_MEMORY_SERVICE", memory_service)):
        if not re.fullmatch(r"service_-_[A-Za-z0-9._-]+", value):
            fail(f"{key} must match service_-_*")
    if service == memory_service:
        fail("HERMES_MEMORY_SERVICE must differ from HERMES_SERVICE")
    branch, repository = env["GITMEM_BRANCH"], env["GITMEM_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        fail("GITMEM_BRANCH contains unsupported characters")
    if re.match(r"https?://[^/]*@", repository):
        fail("GITMEM_REPOSITORY must not embed credentials; use external Git credentials or SSH")
    uid, gid = int(env["HERMES_UID"]), int(env["HERMES_GID"])
    base_path = Path(base).resolve()
    memory_root = base_path / memory_service
    data = memory_root / "data"
    legacy = base_path / service / "data/memories"

    step("Hermes status")
    if subprocess.run(["docker", "inspect", env["HERMES_CONTAINER"]], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        running = run("docker", "inspect", "-f", "{{.State.Running}}", env["HERMES_CONTAINER"], capture=True).stdout.decode().strip()
        if running == "true":
            fail(f"container {env['HERMES_CONTAINER']} is still running; stop Hermes before preparing Git memory")
        log(f"{env['HERMES_CONTAINER']}: stopped")
    else:
        log(f"{env['HERMES_CONTAINER']}: absent")

    step("Persistent memory directory")
    for path in (memory_root, data):
        if path.is_symlink():
            fail(f"{path} cannot be a symlink")
        if path.exists() and not path.is_dir():
            fail(f"{path} is not a directory")
        path.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(path, uid, gid)
        path.chmod(0o750)
    for name in MEMORY_FILES:
        path = data / name
        if path.is_symlink():
            fail(f"{path} cannot be a symlink")
        if path.exists() and not path.is_file():
            fail(f"{path} exists but is not a regular file")
        if not path.exists():
            path.touch(mode=0o640)
            os.chown(path, uid, gid)
            log(f"Created empty local file: {name}")

    step("Git working tree")
    adopt(memory_root, data, legacy, repository, branch, uid, gid)
    origin, actual_branch = validate_identity(data, repository, branch)

    step("Legacy memory")
    for name in MEMORY_FILES:
        old = legacy / name
        if old.is_file() and old.stat().st_size:
            if not same_content(old, data / name):
                fail(f"{old} contains different memory. Resolve it deliberately before rerunning Git memory preparation")
            log(f"{name}: legacy memory matches active memory")
        else:
            log(f"{name}: no nonempty legacy memory")

    for root, directories, files in os.walk(data, followlinks=False):
        os.chown(root, uid, gid)
        for name in directories + files:
            os.chown(Path(root) / name, uid, gid, follow_symlinks=False)
    data.chmod(0o750)
    for name in MEMORY_FILES:
        (data / name).chmod(0o640)

    step("Audit")
    if not (data / ".git").is_dir() or (data / ".git").is_symlink():
        fail("missing or invalid .git directory")
    for path, mode in ((data, 0o750), *((data / name, 0o640) for name in MEMORY_FILES)):
        info = path.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
            fail(f"unexpected owner or permissions for {path}")
    changes = changed_paths(data)
    for path in changes:
        if path not in MEMORY_FILES:
            fail(f"unauthorized change after adoption: {path}")
    if sha256(ENV_FILE) != env_before:
        fail(".env changed during Git memory preparation")
    if sha256(LOCK_FILE) != lock_before:
        fail(".lock changed during Git memory preparation")
    log(f"working tree: {data}")
    log(f"origin: {origin}")
    log(f"branch: {actual_branch}")
    log("MEMORY.md / USER.md: tracked and valid")
    log("Tracked static files are allowed only while unchanged")
    log("Local memory changes preserved for conservative sidecar synchronization" if changes else "Working tree matches Git")
    log(".env and .lock unchanged: OK")
    print("\nGit-backed memory prepared and audited.\n\nNo pull, merge, rebase, commit, push, or reset was performed.\nSynchronization is enabled separately with the git-memory profile.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        fail(str(error))
