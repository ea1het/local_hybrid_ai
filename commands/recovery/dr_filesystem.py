#!/usr/bin/env python3
"""Filesystem execution contract for disaster-recovery backup sets.

This milestone deliberately does not create backup artifacts. It prepares the
configured backup root with restrictive permissions and performs a transient,
non-secret probe of the same-parent atomic publication primitive that the future
backup engine will use.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BACKUP_ROOT = Path("/opt/local-hybrid-ai-backups")
BACKUP_ROOT_ENV = "DR_BACKUP_ROOT"
ROOT_MODE = 0o700
SET_MODE = 0o700
FILE_MODE = 0o600


class FilesystemContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilesystemContractResult:
    root: Path
    source: str
    root_created: bool
    root_mode: int
    owner_uid: int
    probe_temp_mode: int
    probe_file_mode: int
    atomic_rename_ok: bool
    probe_cleaned: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "source": self.source,
            "root_created": self.root_created,
            "root_mode": format(self.root_mode, "04o"),
            "owner_uid": self.owner_uid,
            "probe_temp_mode": format(self.probe_temp_mode, "04o"),
            "probe_file_mode": format(self.probe_file_mode, "04o"),
            "atomic_rename_ok": self.atomic_rename_ok,
            "probe_cleaned": self.probe_cleaned,
            "final_backup_set_created": False,
            "backup_artifact_created": False,
        }


def resolve_backup_root(
    cli_destination: str | None,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[Path, str]:
    env = os.environ if environ is None else environ
    if cli_destination is not None:
        raw = cli_destination
        source = "cli"
    elif env.get(BACKUP_ROOT_ENV):
        raw = env[BACKUP_ROOT_ENV]
        source = "environment"
    else:
        raw = str(DEFAULT_BACKUP_ROOT)
        source = "default"

    if not raw or not raw.strip():
        raise FilesystemContractError("backup destination cannot be empty")
    path = Path(raw)
    if not path.is_absolute():
        raise FilesystemContractError("backup destination must be an absolute path")
    normalized = Path(os.path.abspath(os.path.normpath(str(path))))
    if normalized == Path("/"):
        raise FilesystemContractError("backup destination cannot be filesystem root")
    return normalized, source


def nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_existing_root(root: Path) -> None:
    if not root.is_dir():
        raise FilesystemContractError(f"backup root exists but is not a directory: {root}")
    st = root.stat()
    actual_mode = stat.S_IMODE(st.st_mode)
    if st.st_uid != os.geteuid():
        raise FilesystemContractError(
            f"backup root must be owned by the executing uid {os.geteuid()}: {root}"
        )
    if actual_mode != ROOT_MODE:
        raise FilesystemContractError(
            f"backup root must have mode 0700; found {actual_mode:04o}: {root}"
        )
    if not os.access(root, os.W_OK | os.X_OK):
        raise FilesystemContractError(f"backup root is not writable/executable: {root}")


def ensure_backup_root(root: Path) -> bool:
    """Create the engine-owned backup root if absent, otherwise validate it.

    Existing roots are never chmod/chowned implicitly. A non-conforming existing
    root fails closed so the operator can inspect it deliberately.
    """
    if root.exists():
        validate_existing_root(root)
        return False

    parent = nearest_existing_parent(root.parent)
    if not parent.exists() or not parent.is_dir():
        raise FilesystemContractError(f"cannot resolve existing parent for backup root: {root}")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise FilesystemContractError(f"backup root parent is not writable/executable: {parent}")

    old_umask = os.umask(0o077)
    try:
        root.mkdir(parents=True, mode=ROOT_MODE)
    except OSError as exc:
        raise FilesystemContractError(f"cannot create backup root {root}: {exc}") from exc
    finally:
        os.umask(old_umask)

    validate_existing_root(root)
    fsync_directory(root)
    fsync_directory(root.parent)
    return True


def create_private_file(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


def cleanup_probe(root: Path, temp: Path, published: Path, marker_name: str) -> bool:
    """Remove only paths created by this probe; never recurse into arbitrary data."""
    cleaned = True
    for directory in (published, temp):
        marker = directory / marker_name
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                cleaned = False
        if directory.exists():
            try:
                directory.rmdir()
            except OSError:
                cleaned = False
    try:
        fsync_directory(root)
    except OSError:
        cleaned = False
    return cleaned


def probe_atomic_publication(root: Path) -> tuple[int, int, bool, bool]:
    """Exercise the future publication primitive without publishing a backup set."""
    token = secrets.token_hex(8)
    temp = root / f".backup-fs-probe-{token}.tmp"
    published = root / f".backup-fs-probe-{token}.published"
    marker_name = ".probe"
    marker = temp / marker_name

    try:
        temp.mkdir(mode=SET_MODE)
        if mode_of(temp) != SET_MODE:
            raise FilesystemContractError("temporary backup-set probe directory is not mode 0700")
        create_private_file(marker, b"local-hybrid-ai-dr-filesystem-probe\n")
        temp_mode = mode_of(temp)
        file_mode = mode_of(marker)
        if file_mode != FILE_MODE:
            raise FilesystemContractError("probe file is not mode 0600")

        fsync_directory(temp)
        before_inode = temp.stat().st_ino
        if published.exists():
            raise FilesystemContractError("unexpected publication probe collision")
        os.replace(temp, published)
        fsync_directory(root)

        atomic_ok = (
            published.is_dir()
            and (published / marker_name).is_file()
            and published.stat().st_ino == before_inode
        )
        if not atomic_ok:
            raise FilesystemContractError("same-parent atomic publication probe failed")

        cleaned = cleanup_probe(root, temp, published, marker_name)
        if not cleaned:
            raise FilesystemContractError("publication probe succeeded but cleanup was incomplete")
        return temp_mode, file_mode, True, True
    except Exception:
        cleanup_probe(root, temp, published, marker_name)
        raise


def prepare_filesystem_contract(root: Path, source: str) -> FilesystemContractResult:
    root_created = ensure_backup_root(root)
    temp_mode, file_mode, atomic_ok, cleaned = probe_atomic_publication(root)
    st = root.stat()
    return FilesystemContractResult(
        root=root,
        source=source,
        root_created=root_created,
        root_mode=stat.S_IMODE(st.st_mode),
        owner_uid=st.st_uid,
        probe_temp_mode=temp_mode,
        probe_file_mode=file_mode,
        atomic_rename_ok=atomic_ok,
        probe_cleaned=cleaned,
    )


def print_human(result: FilesystemContractResult) -> None:
    action = "created" if result.root_created else "already present and validated"
    print("DR execution filesystem contract")
    print(f"- root: {result.root}")
    print(f"- selected by: {result.source}")
    print(f"- root: {action}")
    print(f"- root mode: {result.root_mode:04o}")
    print(f"- root owner uid: {result.owner_uid}")
    print(f"- temporary backup-set mode: {result.probe_temp_mode:04o}")
    print(f"- private file mode: {result.probe_file_mode:04o}")
    print(f"- same-parent atomic rename: {'PASS' if result.atomic_rename_ok else 'FAIL'}")
    print(f"- transient probe cleanup: {'PASS' if result.probe_cleaned else 'FAIL'}")
    print("- final backup set created: no")
    print("- backup artifact created: no")
    print()
    print("The backup root is persistent. The atomicity probe is transient and contains no secrets.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and validate the DR backup filesystem contract")
    parser.add_argument(
        "--destination",
        help=(
            "backup root directory; precedence: --destination, DR_BACKUP_ROOT, "
            f"default {DEFAULT_BACKUP_ROOT}"
        ),
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="explicitly create/validate the backup root and run the transient atomicity probe",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    if not args.prepare:
        print("ERROR: filesystem execution requires explicit --prepare", file=sys.stderr)
        return 2

    try:
        root, source = resolve_backup_root(args.destination)
        result = prepare_filesystem_contract(root, source)
    except FilesystemContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: filesystem contract failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
