#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Create the shared host filesystem and PKI group for all stacks.

This operator-run entrypoint creates service directories below BASE_PATH with
the owners and modes expected by each container; individual prepare scripts
only verify and populate those directories. It also creates the
local-hybrid-pki group used to read HAProxy's private key. Existing PostgreSQL
data directories are never re-owned. Stack 0 is audited even with its .lock.
Other locked application stacks are left alone, but Stack 10's platform-owned
prerequisite paths are reconciled during --platform-only installation. The
Stack 0 installer selects only platform and Stack 10 prerequisite paths;
application installers can select their own directories with --stack. Use
--dry-run to inspect the plan. Importing this module performs no setup."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never create __pycache__ in the worktree

import argparse
import functools
import grp
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ROOT_DIR = STACK_DIR.parent
ENV_FILE = ROOT_DIR / ".env"

PLATFORM_PKI_GROUP = "local-hybrid-pki"
SERVICE_NAME_RE = re.compile(r"^service_-_[A-Za-z0-9._-]+$")

DRY_RUN = False


@dataclass(frozen=True)
class Dir:
    """Describe a directory's desired path, mode, and ownership."""

    path: Path
    mode: int
    uid: int | None = 0          # None: keep the current owner (created as root)
    gid: int | None = 0
    recursive: bool = False      # reconcile ownership of existing contents
    create_only: bool = False    # PGDATA: create if absent, never alter if present


def die(message: str, code: int = 1) -> None:
    """Print an error and exit with the requested status code."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def warn(message: str) -> None:
    """Print a warning without interrupting execution."""
    print(f"WARNING: {message}", file=sys.stderr)


def log(message: str) -> None:
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message: str) -> None:
    """Print a phase heading."""
    print(f"\n== {message}")


def load_env(env_file: Path) -> dict[str, str]:
    """Load the central .env using the same shell rules as the stack scripts."""
    if not env_file.is_file() or env_file.is_symlink():
        die(f"missing root environment: {env_file}")
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; set +a; env -0', "_", str(env_file)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        die(f"could not load {env_file}: {result.stderr.decode(errors='replace').strip()}")
    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            env[key.decode()] = value.decode(errors="replace")
    return env


def require(env: dict[str, str], key: str) -> str:
    """Return a nonempty environment value or exit with an error."""
    value = env.get(key, "")
    if not value:
        die(f"missing {key} in {ENV_FILE}")
    return value


def require_int(env: dict[str, str], key: str, default: str | None = None) -> int:
    """Read a nonnegative integer from the environment or its default."""
    raw = env.get(key) or default or ""
    if not raw.isdigit():
        die(f"{key} must be a nonnegative integer (value: {raw!r})")
    return int(raw)


def require_service_name(env: dict[str, str], key: str) -> str:
    """Validate and return a configured service directory name."""
    value = require(env, key)
    if not SERVICE_NAME_RE.match(value):
        die(f"{key} must match service_-_*: {value}")
    return value


def image_ref(env: dict[str, str], image_key: str, version_key: str) -> str:
    """Build an image:version reference when both components are present."""
    image, version = env.get(image_key, ""), env.get(version_key, "")
    return f"{image}:{version}" if image and version else ""


@functools.lru_cache(maxsize=None)
def image_owner(image: str) -> tuple[int, int] | None:
    """Return an image's UID/GID, or None if it cannot be determined."""
    if not image or shutil.which("docker") is None:
        return None
    ids = []
    for flag in ("-u", "-g"):
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "id", image, flag],
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit():
            return None
        ids.append(int(value))
    return ids[0], ids[1]


def ensure_group(name: str, gid: int) -> None:
    """Check or create the local group with the expected GID."""
    step(f"Group {name}")
    try:
        existing = grp.getgrnam(name)
    except KeyError:
        existing = None
    if existing is not None:
        if existing.gr_gid != gid:
            die(f"{name} has GID {existing.gr_gid}; expected {gid}")
        log(f"{name} ({gid}) already exists")
        return
    try:
        other = grp.getgrgid(gid)
    except KeyError:
        other = None
    if other is not None:
        die(f"GID {gid} is already used by group {other.gr_name}; choose another PLATFORM_PKI_GID")
    if DRY_RUN:
        log(f"[dry-run] groupadd --gid {gid} {name}")
        return
    subprocess.run(["groupadd", "--gid", str(gid), name], check=True)
    log(f"created {name} ({gid})")


def chown_tree(root: Path, uid: int, gid: int) -> None:
    """Reconcile ownership beneath a directory without following symlinks."""
    for current, dirs, files in os.walk(root):
        for name in dirs + files:
            child = os.path.join(current, name)
            child_stat = os.lstat(child)
            if (child_stat.st_uid, child_stat.st_gid) != (uid, gid):
                os.lchown(child, uid, gid)


def ensure_dir(spec: Dir) -> None:
    """Create or reconcile a directory according to its specification and dry-run mode."""
    path = spec.path
    if path.is_symlink():
        die(f"service path cannot be a symlink: {path}")
    if path.exists() and not path.is_dir():
        die(f"service path exists and is not a directory: {path}")

    owner = "unchanged" if spec.uid is None else f"{spec.uid}:{spec.gid}"
    description = f"{path} {spec.mode:04o} {owner}{' (recursive)' if spec.recursive else ''}"

    if spec.create_only and path.is_dir():
        log(f"{path}: existing PGDATA preserved")
        return

    if DRY_RUN:
        log(f"[dry-run] {description}")
        return

    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        os.chown(path, 0, 0)
    current = path.stat()
    if spec.uid is not None and spec.gid is not None:
        if (current.st_uid, current.st_gid) != (spec.uid, spec.gid):
            os.chown(path, spec.uid, spec.gid)
        if spec.recursive:
            chown_tree(path, spec.uid, spec.gid)
    if current.st_mode & 0o7777 != spec.mode:
        os.chmod(path, spec.mode)
    log(description)


def build_layout(env: dict[str, str]) -> list[tuple[str, Callable[[], list[Dir]]]]:
    """Return stack/layout-builder pairs for unlocked stacks and Stack 0.

    Other locked stacks do not invoke Docker or validate settings they will
    not change. The caller still audits Stack 0 when it has a lock.
    """
    base = Path(env["BASE_PATH"].rstrip("/"))

    def svc(name: str) -> Path:
        """Return a service directory beneath BASE_PATH."""
        return base / name

    def stack0() -> list[Dir]:
        """Define platform state and log directories."""
        platform = svc("service_-_platform")
        return [
            Dir(base, 0o750),
            Dir(platform, 0o750),
            Dir(platform / "state", 0o700),
            Dir(platform / "logs", 0o750),
        ]

    def stack1() -> list[Dir]:
        """Define HAProxy and web directories with PKI group access."""
        pki_gid = require_int(env, "PLATFORM_PKI_GID", "1999")
        haproxy = svc("service_-_haproxy")
        return [
            Dir(haproxy, 0o750, 0, pki_gid),
            Dir(haproxy / "config", 0o750, 0, pki_gid),
            Dir(svc("service_-_web"), 0o755),
        ]

    def stack2() -> list[Dir]:
        """Define persistent SearXNG and Firecrawl directories."""
        def image_dir(path: Path, image: str, label: str) -> Dir:
            """Use the image UID/GID or preserve ownership when unknown."""
            owner = image_owner(image)
            if owner is None:
                warn(f"{label}: could not determine image UID/GID for '{image}'; preserving ownership")
                return Dir(path, 0o755, None, None)
            uid, gid = owner
            if uid == 0:
                return Dir(path, 0o755)
            return Dir(path, 0o755, uid, gid, recursive=True)

        searxng = svc("service_-_searxng")
        redis = svc("service_-_firecrawl-redis")
        rabbitmq = svc("service_-_firecrawl-rabbitmq")
        fc_postgres = svc("service_-_firecrawl-postgres")
        searxng_image = env.get("SEARXNG_IMAGE", "")
        redis_image = image_ref(env, "FIRECRAWL_REDIS_IMAGE", "FIRECRAWL_REDIS_VERSION")
        rabbitmq_image = image_ref(env, "FIRECRAWL_RABBITMQ_IMAGE", "FIRECRAWL_RABBITMQ_VERSION")
        return [
            Dir(searxng, 0o750),
            image_dir(searxng / "config", searxng_image, "searxng"),
            image_dir(searxng / "data", searxng_image, "searxng"),
            Dir(redis, 0o750),
            image_dir(redis / "data", redis_image, "firecrawl-redis"),
            Dir(rabbitmq, 0o750),
            image_dir(rabbitmq / "data", rabbitmq_image, "firecrawl-rabbitmq"),
            Dir(fc_postgres, 0o750),
            Dir(fc_postgres / "data", 0o700, create_only=True),
        ]

    def stack3() -> list[Dir]:
        """Describe LiteLLM configuration and PostgreSQL data directories."""
        litellm = svc("service_-_litellm")
        litellm_postgres = svc("service_-_litellm-postgres")
        return [
            Dir(litellm, 0o750),
            Dir(litellm / "config", 0o750),
            Dir(litellm_postgres, 0o750),
            Dir(litellm_postgres / "data", 0o700, create_only=True),
        ]

    def stack4() -> list[Dir]:
        """Define Gitea and runner directories."""
        gitea_uid = require_int(env, "GITEA_UID")
        gitea_gid = require_int(env, "GITEA_GID")
        gitea = svc("service_-_gitea")
        runner = svc("service_-_gitea-runner")
        return [
            Dir(gitea, 0o750),
            Dir(gitea / "config", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(gitea / "config" / "conf", 0o750, gitea_uid, gitea_gid),
            Dir(gitea / "data", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(runner, 0o750),
            Dir(runner / "data", 0o750, gitea_uid, gitea_gid, recursive=True),
            Dir(runner / "secret", 0o750, 0, gitea_gid),
        ]

    def stack6() -> list[Dir]:
        """Define Hermes, memory, and sandbox directories."""
        hermes_owner = (require_int(env, "HERMES_UID"), require_int(env, "HERMES_GID"))
        sandbox_owner = (require_int(env, "SANDBOX_UID"), require_int(env, "SANDBOX_GID"))
        names = {
            key: require_service_name(env, key)
            for key in ("HERMES_SERVICE", "HERMES_MEMORY_SERVICE", "MEMORY_SYNC_SERVICE", "SANDBOX_SERVICE")
        }
        if len(set(names.values())) != len(names):
            die("HERMES_SERVICE, HERMES_MEMORY_SERVICE, MEMORY_SYNC_SERVICE, and SANDBOX_SERVICE must differ")
        hermes = svc(names["HERMES_SERVICE"])
        memory = svc(names["HERMES_MEMORY_SERVICE"])
        memory_sync = svc(names["MEMORY_SYNC_SERVICE"])
        sandbox = svc(names["SANDBOX_SERVICE"])
        return [
            Dir(hermes, 0o750, *hermes_owner),
            Dir(hermes / "config", 0o750, *hermes_owner),
            Dir(hermes / "config" / "ssh", 0o700, *hermes_owner),
            Dir(hermes / "data", 0o750, *hermes_owner),
            Dir(hermes / "logs", 0o750, *hermes_owner),
            Dir(memory, 0o750, *hermes_owner),
            Dir(memory / "data", 0o750, *hermes_owner),
            Dir(memory_sync, 0o750, *hermes_owner),
            Dir(memory_sync / "ssh", 0o700, *hermes_owner),
            Dir(sandbox, 0o750),
            Dir(sandbox / "config", 0o750),
            Dir(sandbox / "config" / "ssh-host", 0o750),
            Dir(sandbox / "data", 0o750),
            Dir(sandbox / "data" / "home", 0o750, *sandbox_owner),
            Dir(sandbox / "data" / "home" / ".ssh", 0o700, *sandbox_owner),
            Dir(sandbox / "data" / "workspace", 0o750, *sandbox_owner),
            Dir(sandbox / "data" / "state", 0o700),
            Dir(sandbox / "logs", 0o750, *sandbox_owner),
        ]

    def stack7() -> list[Dir]:
        """Define the Open WebUI data directory."""
        openwebui = svc("service_-_open-webui")
        return [
            Dir(openwebui, 0o750),
            Dir(openwebui / "data", 0o750),
        ]

    return [
        ("stack-00_-_platform", stack0),
        ("stack-10_-_haproxy_web", stack1),
        ("stack-20_-_searxng_firecrawl", stack2),
        ("stack-30_-_litellm", stack3),
        ("stack-40_-_gitea", stack4),
        ("stack-60_-_hermes", stack6),
        ("stack-70_-_open-webui", stack7),
    ]


def parse_args() -> argparse.Namespace:
    """Parse bootstrap scope and dry-run options."""
    parser = argparse.ArgumentParser(
        description="Create service directories and set their permissions.",
    )
    parser.add_argument("--dry-run", action="store_true", help="show actions without applying them")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--platform-only", action="store_true", help="limit changes to Stack 0 and Stack 10 prerequisites")
    scope.add_argument("--stack", choices=("20", "30", "40", "60", "70"),
                       help="reconcile only the selected application stack directories")
    return parser.parse_args()


def main() -> None:
    """Validate the environment and reconcile Stack 0 plus unlocked stacks."""
    global DRY_RUN
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    DRY_RUN = args.dry_run

    if os.geteuid() != 0 and not DRY_RUN:
        die("run this script as root")
    if shutil.which("groupadd") is None and not DRY_RUN:
        die("missing required command: groupadd")

    env = load_env(ENV_FILE)
    stacks_root = require(env, "STACKS_ROOT").rstrip("/")
    base_path = require(env, "BASE_PATH").rstrip("/")
    if not stacks_root.startswith("/") or not base_path.startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute paths")
    if not base_path or base_path == "/":
        die("BASE_PATH cannot be /")
    if str(ROOT_DIR) != stacks_root:
        die(f"worktree must be at {stacks_root}; current path: {ROOT_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")

    pki_gid = require_int(env, "PLATFORM_PKI_GID", "1999")
    if pki_gid <= 0:
        die("PLATFORM_PKI_GID must be a positive integer")

    ensure_group(PLATFORM_PKI_GROUP, pki_gid)

    skipped: list[str] = []
    for stack, build in build_layout(env):
        if args.platform_only and stack not in ("stack-00_-_platform", "stack-10_-_haproxy_web"):
            continue
        if args.stack and not stack.startswith(f"stack-{args.stack}_-_"):
            continue
        step(f"Directories for {stack}")
        lock = ROOT_DIR / stack / ".lock"
        platform_prerequisite = args.platform_only and stack == "stack-10_-_haproxy_web"
        if lock.exists() and stack != "stack-00_-_platform" and not platform_prerequisite:
            log(f"PREPARED ({lock}): directories and permissions left unchanged")
            skipped.append(stack)
            continue
        for spec in build():
            ensure_dir(spec)

    step("Base directory layout complete" if not DRY_RUN else "Dry run complete; no changes made")
    log(f"BASE_PATH: {base_path}")
    if skipped:
        log("prepared stacks skipped (remove their .lock before reconciling): " + ", ".join(skipped))


if __name__ == "__main__":
    main()
