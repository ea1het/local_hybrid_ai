#!/usr/bin/env python3
"""Isolated restore verifier for the Stack0 archive DR milestone.

This command never restores into the live runtime path. It validates a completed
backup set, locates the Stack0 platform-pki archive even inside a multi-artifact
full backup set, extracts it into a private temporary directory, compares the
restored tree with an optional live source tree, and removes the temporary tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import dr_archive

DIR_MODE = 0o700
FILE_MODE = 0o600


class ArchiveRestoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreVerificationResult:
    backup_set: Path
    artifact: Path
    restored_root_name: str
    member_count: int
    compared_to_source: bool
    source_match: bool | None
    temporary_cleanup: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.backup_set),
            "artifact": str(self.artifact),
            "restored_root_name": self.restored_root_name,
            "member_count": self.member_count,
            "compared_to_source": self.compared_to_source,
            "source_match": self.source_match,
            "temporary_cleanup": self.temporary_cleanup,
            "live_runtime_modified": False,
        }


def sha256_file(path: Path) -> str:
    return dr_archive.sha256_file(path)


def safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise ArchiveRestoreError(f"unsafe archive member path: {name}")
    if path.parts[0] != "pki":
        raise ArchiveRestoreError(f"archive member is outside expected pki root: {name}")
    return path


def validate_symlink_target(member_path: PurePosixPath, target: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise ArchiveRestoreError(f"absolute symlink target is not allowed: {member_path}")
    combined = member_path.parent.joinpath(target_path)
    depth = 0
    for part in combined.parts:
        if part == ".":
            continue
        if part == "..":
            depth -= 1
        else:
            depth += 1
        if depth <= 0:
            raise ArchiveRestoreError(f"symlink escapes pki root: {member_path}")


def validate_completed_backup_set(backup_set: Path) -> tuple[dict, Path]:
    if not backup_set.is_dir():
        raise ArchiveRestoreError(f"backup set is not a directory: {backup_set}")
    metadata_path = backup_set / "backup.json"
    checksums_path = backup_set / "checksums.sha256"
    if not metadata_path.is_file() or not checksums_path.is_file():
        raise ArchiveRestoreError("backup set is missing metadata or checksum index")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        # dr_archive.validate_completed_metadata predates optional global
        # artifacts. Validate the original v1 stack-owned subset here while
        # preserving the real backup.json bytes/hash below. Full-set/global
        # validation belongs to the generic restore engine.
        legacy_view = dict(metadata)
        legacy_view.pop("global_artifacts", None)
        dr_archive.validate_completed_metadata(legacy_view)
    except (OSError, json.JSONDecodeError, dr_archive.ArchiveBackupError) as exc:
        raise ArchiveRestoreError(f"invalid backup metadata: {exc}") from exc

    artifacts = metadata.get("artifacts", [])
    candidates = [
        item for item in artifacts
        if item.get("stack_id") == 0
        and item.get("resource_id") == "platform-pki"
        and item.get("strategy") == "archive"
    ]
    if len(candidates) != 1:
        raise ArchiveRestoreError(
            "backup set must contain exactly one Stack0 platform-pki archive artifact"
        )
    artifact_meta = candidates[0]

    artifact = backup_set / artifact_meta["relative_path"]
    try:
        resolved_set = backup_set.resolve(strict=True)
        resolved_artifact_parent = artifact.parent.resolve(strict=True)
    except OSError as exc:
        raise ArchiveRestoreError(f"cannot resolve backup-set paths: {exc}") from exc
    if resolved_set not in (resolved_artifact_parent, *resolved_artifact_parent.parents):
        raise ArchiveRestoreError("artifact path resolves outside backup set")
    if not artifact.is_file():
        raise ArchiveRestoreError("archive artifact is missing")
    if artifact.stat().st_size != artifact_meta["size_bytes"]:
        raise ArchiveRestoreError("archive size does not match backup metadata")
    if sha256_file(artifact) != artifact_meta["sha256"]:
        raise ArchiveRestoreError("archive SHA-256 does not match backup metadata")

    expected = {}
    try:
        for raw in checksums_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            digest, rel = raw.split("  ", 1)
            expected[rel] = digest
    except (OSError, ValueError) as exc:
        raise ArchiveRestoreError(f"invalid checksum index: {exc}") from exc
    if expected.get(artifact_meta["relative_path"]) != artifact_meta["sha256"]:
        raise ArchiveRestoreError("checksum index does not match artifact metadata")
    metadata_hash = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    if expected.get("backup.json") != metadata_hash:
        raise ArchiveRestoreError("checksum index does not match backup.json")
    return metadata, artifact


def extract_archive_safely(artifact: Path, destination: Path) -> tuple[Path, int]:
    destination.mkdir(mode=DIR_MODE)
    os.chmod(destination, DIR_MODE)
    try:
        with tarfile.open(artifact, "r") as archive:
            members = archive.getmembers()
            if not members:
                raise ArchiveRestoreError("archive is empty")
            for member in members:
                rel = safe_member_name(member.name)
                target = destination.joinpath(*rel.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, stat.S_IMODE(member.mode))
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ArchiveRestoreError(f"cannot read archive member: {member.name}")
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
                    try:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            os.write(fd, chunk)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                        source.close()
                    os.chmod(target, stat.S_IMODE(member.mode))
                elif member.issym():
                    validate_symlink_target(rel, member.linkname)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, target)
                elif member.islnk():
                    link_rel = safe_member_name(member.linkname)
                    link_source = destination.joinpath(*link_rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not link_source.exists():
                        raise ArchiveRestoreError(f"hardlink source missing: {member.name}")
                    os.link(link_source, target)
                else:
                    raise ArchiveRestoreError(f"unsupported archive member type: {member.name}")
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveRestoreError(f"archive extraction failed: {exc}") from exc

    restored_root = destination / "pki"
    if not restored_root.is_dir():
        raise ArchiveRestoreError("restored archive does not contain pki root")
    return restored_root, len(members)


def tree_fingerprint(root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        item: dict[str, object] = {
            "path": str(path.relative_to(root)),
            "mode": stat.S_IMODE(st.st_mode),
            "type": "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file" if path.is_file() else "other",
        }
        if path.is_file() and not path.is_symlink():
            item["sha256"] = sha256_file(path)
        if path.is_symlink():
            item["target"] = os.readlink(path)
        result.append(item)
    return result


def verify_restore(backup_set: Path, *, compare_source: Path | None = None) -> RestoreVerificationResult:
    _, artifact = validate_completed_backup_set(backup_set)
    temp_parent = Path(tempfile.mkdtemp(prefix="local-hybrid-ai-restore-test-"))
    os.chmod(temp_parent, DIR_MODE)
    source_match: bool | None = None
    member_count = 0
    restored_root_name = "pki"
    try:
        restored_root, member_count = extract_archive_safely(artifact, temp_parent / "restore")
        restored_root_name = restored_root.name
        if compare_source is not None:
            if not compare_source.is_dir():
                raise ArchiveRestoreError(f"compare source is not a directory: {compare_source}")
            source_match = tree_fingerprint(restored_root) == tree_fingerprint(compare_source)
            if not source_match:
                raise ArchiveRestoreError("restored tree does not match comparison source")
    finally:
        shutil.rmtree(temp_parent, ignore_errors=False)
    return RestoreVerificationResult(
        backup_set=backup_set,
        artifact=artifact,
        restored_root_name=restored_root_name,
        member_count=member_count,
        compared_to_source=compare_source is not None,
        source_match=source_match,
        temporary_cleanup=not temp_parent.exists(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Stack0 archive restore in an isolated temporary directory")
    parser.add_argument("backup_set", help="completed backup-set directory containing Stack0 platform-pki")
    parser.add_argument("--compare-source", help="optional live source tree to compare without modifying it")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_restore(
            Path(args.backup_set),
            compare_source=Path(args.compare_source) if args.compare_source else None,
        )
    except (ArchiveRestoreError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print("DR Stack0 archive restore verification")
        print(f"- backup set: {result.backup_set}")
        print(f"- artifact: {result.artifact}")
        print(f"- restored root: {result.restored_root_name}")
        print(f"- archive members: {result.member_count}")
        print(f"- compared to source: {'yes' if result.compared_to_source else 'no'}")
        if result.compared_to_source:
            print(f"- restored/source fingerprint match: {'PASS' if result.source_match else 'FAIL'}")
        print(f"- temporary cleanup: {'PASS' if result.temporary_cleanup else 'FAIL'}")
        print("- live runtime modified: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
