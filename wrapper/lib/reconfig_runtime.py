"""Shared filesystem and read-only preflight helpers for stack reconfiguration."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

from wrapper.stubs.bootstrap_env import BootstrapError, assignments, protected_text


class ReconfigError(RuntimeError):
    """Report an unsafe or incomplete reconfiguration prerequisite."""


def environment(stack_dir: Path) -> dict[str, str]:
    """Require a prepared stack and return the protected central environment."""
    lock = stack_dir / ".lock"
    env_link = stack_dir / ".env"
    if os.geteuid() != 0:
        raise ReconfigError("reconfiguration requires root privileges")
    if lock.is_symlink() or not lock.is_file():
        raise ReconfigError(f"stack is not prepared: {lock}")
    if not env_link.is_symlink() or os.readlink(env_link) != "../.env":
        raise ReconfigError(f"missing managed environment link: {env_link}")
    try:
        return assignments(protected_text(env_link.resolve()))
    except BootstrapError as error:
        raise ReconfigError(f"cannot read protected .env: {error}") from error


def compose_config(stack_dir: Path) -> None:
    """Validate Compose syntax without creating or changing containers."""
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml", "config", "--quiet"],
        cwd=stack_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ReconfigError(f"Docker Compose configuration is invalid: {result.stderr.strip()}")


def container_running(name: str) -> bool:
    """Inspect a container without changing its lifecycle."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        if "No such object" in result.stderr or "No such container" in result.stderr:
            return False
        raise ReconfigError(f"cannot inspect Docker container {name}: {result.stderr.strip()}")
    state = result.stdout.strip()
    if state not in {"true", "false"}:
        raise ReconfigError(f"unexpected Docker state for {name}: {state}")
    return state == "true"


def sync_managed(source: Path, target: Path) -> bool:
    """Back up and atomically replace one stack-owned runtime file if changed."""
    validate_managed(source, target)
    return sync_content(source.read_bytes(), target)


def validate_managed(source: Path, target: Path) -> None:
    """Reject an unsafe managed source or destination before any stack writes."""
    if source.is_symlink() or not source.is_file() or target.parent.is_symlink() or not target.parent.is_dir():
        raise ReconfigError(f"unsafe managed configuration path: {target}")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ReconfigError(f"unsafe managed configuration target: {target}")
    if not source.stat().st_size:
        raise ReconfigError(f"empty managed configuration source: {source}")


def sync_content(content: bytes, target: Path) -> bool:
    """Install already-rendered bytes with the target's ownership and mode."""
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ReconfigError(f"unsafe managed configuration path: {target}")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ReconfigError(f"unsafe managed configuration target: {target}")
    if not content:
        raise ReconfigError(f"empty managed configuration for: {target}")
    if target.exists() and target.read_bytes() == content:
        return False
    metadata = target.stat() if target.exists() else target.parent.stat()
    mode = stat.S_IMODE(metadata.st_mode) if target.exists() else 0o644
    if target.exists():
        backup = target.with_name(f"{target.name}-backup-{time.time_ns()}")
        with backup.open("xb") as output:
            output.write(target.read_bytes())
        os.chown(backup, metadata.st_uid, metadata.st_gid)
        backup.chmod(0o600)
        print(f"Backup: {backup}")
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        temporary.chmod(mode)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def lifecycle_hint(number: str) -> None:
    """Tell the operator how to apply staged configuration without doing it."""
    print("No containers were stopped or started.")
    print("To apply changes when ready, run from the repository root:")
    print(f"  ./local-ai stack-{number} stop")
    print(f"  ./local-ai stack-{number} start")
