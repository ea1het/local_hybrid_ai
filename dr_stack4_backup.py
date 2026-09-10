#!/usr/bin/env python3
"""Real DR backup adapter for Stack4 / Gitea.

Creates a dependency-complete backup set for Stack4 containing:
- Stack0 platform PKI archive
- Stack4 native Gitea dump ZIP

The Gitea dump is created by the running Gitea 1.27.x application itself. This
adapter validates ZIP integrity and path safety before atomically publishing the
backup set. It does not stop/restart Gitea and does not modify repositories or
the application database.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import secrets
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import dr
import dr_archive
import dr_filesystem

ROOT = Path(__file__).resolve().parent
STACK_ID = 4
GITEA_RESOURCE_ID = "gitea-state"
PKI_RESOURCE_ID = "platform-pki"
GITEA_SERVICE = "gitea"
GITEA_RELATIVE_PATH = "artifacts/stack4/gitea-state.zip"
PKI_RELATIVE_PATH = "artifacts/stack0/platform-pki.tar"


class Stack4BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedStack4Backup:
    path: Path
    pki_sha256: str
    pki_size_bytes: int
    gitea_sha256: str
    gitea_size_bytes: int
    gitea_zip_members: int

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.path),
            "artifacts": [
                {
                    "stack_id": 0,
                    "resource_id": PKI_RESOURCE_ID,
                    "relative_path": PKI_RELATIVE_PATH,
                    "sha256": self.pki_sha256,
                    "size_bytes": self.pki_size_bytes,
                },
                {
                    "stack_id": 4,
                    "resource_id": GITEA_RESOURCE_ID,
                    "relative_path": GITEA_RELATIVE_PATH,
                    "sha256": self.gitea_sha256,
                    "size_bytes": self.gitea_size_bytes,
                    "zip_members": self.gitea_zip_members,
                },
            ],
            "container_restarted": False,
            "live_gitea_state_modified_by_tool": False,
        }


def select_resources(manifests: dict[int, dict], plan: list[int]) -> tuple[dict, dict]:
    if plan != [0, 4]:
        raise Stack4BackupError(f"unexpected Stack4 dependency plan: {plan}")

    pki = [
        r for r in manifests[0]["recovery"].get("resources", [])
        if r.get("id") == PKI_RESOURCE_ID and r.get("strategy") == "archive"
    ]
    gitea = [
        r for r in manifests[4]["recovery"].get("resources", [])
        if r.get("id") == GITEA_RESOURCE_ID and r.get("strategy") == "gitea-native-dump"
    ]
    if len(pki) != 1:
        raise Stack4BackupError("Stack0 must declare exactly one platform-pki archive resource")
    if len(gitea) != 1:
        raise Stack4BackupError("Stack4 must declare exactly one gitea-state native dump resource")
    return pki[0], gitea[0]


def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def bounded_error(label: str, cp: subprocess.CompletedProcess[bytes]) -> Stack4BackupError:
    detail = cp.stderr.decode("utf-8", errors="replace").strip()
    if len(detail) > 1200:
        detail = detail[:1200] + "..."
    return Stack4BackupError(f"{label} failed (rc={cp.returncode}): {detail or 'no diagnostic output'}")


def validate_zip_member(name: str) -> None:
    if not name or "\\" in name:
        raise Stack4BackupError("Gitea dump contains an invalid ZIP member path")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise Stack4BackupError("Gitea dump contains an absolute ZIP member path")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise Stack4BackupError("Gitea dump contains a parent-traversal ZIP member path")


def validate_gitea_dump(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise Stack4BackupError("Gitea native dump is missing or empty")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if not names:
                raise Stack4BackupError("Gitea native dump ZIP contains no members")
            for name in names:
                validate_zip_member(name)
            bad = archive.testzip()
            if bad is not None:
                raise Stack4BackupError(f"Gitea native dump ZIP CRC validation failed: {bad}")
    except zipfile.BadZipFile as exc:
        raise Stack4BackupError("Gitea native dump is not a valid ZIP archive") from exc
    return names


def create_gitea_dump(destination: Path) -> list[str]:
    token = secrets.token_hex(8)
    container_path = f"/tmp/local-hybrid-ai-gitea-dump-{token}.zip"
    created_in_container = False
    try:
        cp_dump = run_command([
            "docker", "exec", GITEA_SERVICE,
            "gitea", "dump",
            "--file", container_path,
            "--type", "zip",
        ])
        if cp_dump.returncode != 0:
            raise bounded_error("gitea dump", cp_dump)
        created_in_container = True

        cp_copy = run_command([
            "docker", "cp",
            f"{GITEA_SERVICE}:{container_path}",
            str(destination),
        ])
        if cp_copy.returncode != 0:
            raise bounded_error("docker cp of Gitea dump", cp_copy)
        os.chmod(destination, 0o600)
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
        return validate_gitea_dump(destination)
    finally:
        if created_in_container:
            # Remove only the unique file created by this invocation.
            run_command(["docker", "exec", GITEA_SERVICE, "rm", "-f", container_path])


def execute_stack4_backup(backup_root: Path) -> CompletedStack4Backup:
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["4"])
    pki_resource, gitea_resource = select_resources(manifests, plan)

    # Read-only correspondence check before creating backup artifacts.
    dr.preflight_runtime_sources(manifests, plan)
    dr_filesystem.validate_existing_root(backup_root)

    values = dr.read_dotenv_presence(ROOT / ".env")
    base_path = dr.resolve_base_path(values)
    pki_source = dr.expand_runtime_path(pki_resource["config"]["source"]["path"], base_path)

    created_at, final_name = dr_archive.timestamp_parts(dr_archive.utc_now())
    final = backup_root / final_name
    if final.exists():
        raise Stack4BackupError(f"final backup-set name already exists: {final}")

    temp = backup_root / f".{final_name}.tmp-{secrets.token_hex(8)}"
    old_umask = os.umask(0o077)
    try:
        dr_archive.mkdir_private(temp)
        artifacts = temp / "artifacts"
        stack0_dir = artifacts / "stack0"
        stack4_dir = artifacts / "stack4"
        dr_archive.mkdir_private(artifacts)
        dr_archive.mkdir_private(stack0_dir)
        dr_archive.mkdir_private(stack4_dir)

        pki_path = temp / PKI_RELATIVE_PATH
        gitea_path = temp / GITEA_RELATIVE_PATH
        dr_archive.create_tar_archive(pki_source, pki_path)
        members = create_gitea_dump(gitea_path)

        pki_hash = dr_archive.sha256_file(pki_path)
        gitea_hash = dr_archive.sha256_file(gitea_path)
        pki_size = pki_path.stat().st_size
        gitea_size = gitea_path.stat().st_size

        metadata = {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": created_at,
            "source_commit": dr.git_head(),
            "requested": ["4"],
            "resolved_stacks": plan,
            "artifacts": [
                {
                    "stack_id": 0,
                    "resource_id": PKI_RESOURCE_ID,
                    "strategy": "archive",
                    "sensitive": bool(pki_resource["sensitive"]),
                    "restore_phase": pki_resource["config"].get("restore", {}).get("phase"),
                    "relative_path": PKI_RELATIVE_PATH,
                    "sha256": pki_hash,
                    "size_bytes": pki_size,
                },
                {
                    "stack_id": 4,
                    "resource_id": GITEA_RESOURCE_ID,
                    "strategy": "gitea-native-dump",
                    "sensitive": bool(gitea_resource["sensitive"]),
                    "restore_phase": gitea_resource["config"].get("restore", {}).get("phase"),
                    "relative_path": GITEA_RELATIVE_PATH,
                    "sha256": gitea_hash,
                    "size_bytes": gitea_size,
                },
            ],
            "prerequisites": [],
        }
        dr_archive.validate_completed_metadata(metadata)

        metadata_path = temp / "backup.json"
        dr_archive.write_private(
            metadata_path,
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        metadata_hash = dr_archive.sha256_file(metadata_path)

        checksum_text = (
            f"{pki_hash}  {PKI_RELATIVE_PATH}\n"
            f"{gitea_hash}  {GITEA_RELATIVE_PATH}\n"
            f"{metadata_hash}  backup.json\n"
        ).encode("utf-8")
        dr_archive.write_private(temp / "checksums.sha256", checksum_text)

        for relative, expected in (
            (PKI_RELATIVE_PATH, pki_hash),
            (GITEA_RELATIVE_PATH, gitea_hash),
            ("backup.json", metadata_hash),
        ):
            if dr_archive.sha256_file(temp / relative) != expected:
                raise Stack4BackupError(f"pre-publication checksum mismatch: {relative}")

        for directory in (stack0_dir, stack4_dir, artifacts, temp):
            dr_archive.fsync_directory(directory)

        dr_archive.rename_noreplace(temp, final)
        dr_archive.fsync_directory(backup_root)

        return CompletedStack4Backup(
            path=final,
            pki_sha256=pki_hash,
            pki_size_bytes=pki_size,
            gitea_sha256=gitea_hash,
            gitea_size_bytes=gitea_size,
            gitea_zip_members=len(members),
        )
    except Exception:
        dr_archive.cleanup_temp(temp)
        raise
    finally:
        os.umask(old_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a real dependency-complete Stack4 Gitea DR backup set")
    parser.add_argument("stack", choices=["4"])
    parser.add_argument("--destination", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        root, _ = dr.resolve_backup_root(args.destination)
        result = execute_stack4_backup(root)
    except (Stack4BackupError, dr.RecoveryError, dr_archive.ArchiveBackupError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print("DR Stack4 backup created")
        print(f"- backup set: {result.path}")
        print(f"- Stack0 PKI: {result.pki_size_bytes} bytes")
        print(f"- Gitea native dump: {result.gitea_size_bytes} bytes")
        print(f"- Gitea ZIP members: {result.gitea_zip_members}")
        print("- live Gitea state modified by tool: no")
        print("- container restarted: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
