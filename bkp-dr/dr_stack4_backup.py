#!/usr/bin/env python3
"""Real DR backup adapter for Stack4 / Gitea.

Creates a dependency-complete backup set for Stack4 containing:
- Stack0 platform PKI archive
- Stack4 native Gitea dump ZIP

For consistency, the live Gitea container is stopped briefly. A one-shot helper
container using the same image and mounted Gitea volumes performs `gitea dump`
while the live instance is stopped. The helper explicitly reproduces the
rootless runtime identity and Gitea paths and performs the dump from its temp
working directory, as required by Gitea's Docker backup guidance.

The live container is restarted immediately after the native dump command
completes, before copying/validating the ZIP. The helper has no network and is
always removed, including dump failure paths. The backup is validated before
atomic publication. Repositories and the live application database are never
modified intentionally by this tool.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import secrets
import subprocess
import sys
import time
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
HEALTH_TIMEOUT_SECONDS = 120
GITEA_ROOTLESS_USER = "1000:1000"
GITEA_WORK_PATH = "/var/lib/gitea"
GITEA_CUSTOM_PATH = "/etc/gitea"
GITEA_CONFIG_PATH = "/etc/gitea/app.ini"
GITEA_TEMP_PATH = "/tmp"
GITEA_BINARY = "/usr/local/bin/gitea"


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
    gitea_was_stopped: bool
    gitea_restarted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_set": str(self.path),
            "artifacts": [
                {"stack_id": 0, "resource_id": PKI_RESOURCE_ID, "relative_path": PKI_RELATIVE_PATH, "sha256": self.pki_sha256, "size_bytes": self.pki_size_bytes},
                {"stack_id": 4, "resource_id": GITEA_RESOURCE_ID, "relative_path": GITEA_RELATIVE_PATH, "sha256": self.gitea_sha256, "size_bytes": self.gitea_size_bytes, "zip_members": self.gitea_zip_members},
            ],
            "consistency_mode": "controlled-offline",
            "gitea_was_stopped": self.gitea_was_stopped,
            "gitea_restarted": self.gitea_restarted,
            "live_gitea_state_modified_by_tool": False,
        }


def select_resources(manifests: dict[int, dict], plan: list[int]) -> tuple[dict, dict]:
    if plan != [0, 4]:
        raise Stack4BackupError(f"unexpected Stack4 dependency plan: {plan}")
    pki = [r for r in manifests[0]["recovery"].get("resources", []) if r.get("id") == PKI_RESOURCE_ID and r.get("strategy") == "archive"]
    gitea = [r for r in manifests[4]["recovery"].get("resources", []) if r.get("id") == GITEA_RESOURCE_ID and r.get("strategy") == "gitea-native-dump"]
    if len(pki) != 1:
        raise Stack4BackupError("Stack0 must declare exactly one platform-pki archive resource")
    if len(gitea) != 1:
        raise Stack4BackupError("Stack4 must declare exactly one gitea-state native dump resource")
    return pki[0], gitea[0]


def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def bounded_error(label: str, cp: subprocess.CompletedProcess[bytes]) -> Stack4BackupError:
    detail = cp.stderr.decode("utf-8", errors="replace").strip()
    if len(detail) > 2400:
        # Keep the end of stderr: Gitea emits many informational storage lines
        # first and normally reports the actionable failure at the end.
        detail = "..." + detail[-2400:]
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


def container_image(service: str = GITEA_SERVICE) -> str:
    cp = run_command(["docker", "inspect", "-f", "{{.Config.Image}}", service])
    if cp.returncode != 0:
        raise bounded_error("Gitea image inspection", cp)
    image = cp.stdout.decode("utf-8", errors="replace").strip()
    if not image or any(ch.isspace() for ch in image):
        raise Stack4BackupError("Gitea container image could not be resolved safely")
    return image


def container_running(service: str = GITEA_SERVICE) -> bool:
    cp = run_command(["docker", "inspect", "-f", "{{.State.Running}}", service])
    if cp.returncode != 0:
        raise bounded_error("Gitea state inspection", cp)
    return cp.stdout.decode("utf-8", errors="replace").strip().lower() == "true"


def wait_gitea_healthy(timeout: int = HEALTH_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    last = "unknown"
    while time.monotonic() < deadline:
        cp = run_command(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", GITEA_SERVICE])
        if cp.returncode == 0:
            last = cp.stdout.decode("utf-8", errors="replace").strip().lower()
            if last in {"healthy", "running"}:
                return
        time.sleep(2)
    raise Stack4BackupError(f"Gitea did not become healthy/running after restart (last state: {last})")


def remove_helper(helper: str) -> None:
    cp = run_command(["docker", "rm", "-f", helper])
    if cp.returncode != 0:
        inspect = run_command(["docker", "inspect", helper])
        if inspect.returncode == 0:
            raise bounded_error("Gitea dump helper cleanup", cp)


def build_helper_create_command(image: str, helper: str, helper_dump: str) -> list[str]:
    """Build the rootless Gitea dump helper command.

    The live deployment is Gitea rootless (uid/gid 1000:1000), with work path
    /var/lib/gitea and config /etc/gitea/app.ini. Gitea's Docker backup guidance
    also requires running the dump command from the temporary directory used for
    packaging, so both container working directory and --tempdir are /tmp.
    """
    return [
        "docker", "create",
        "--name", helper,
        "--network", "none",
        "--volumes-from", GITEA_SERVICE,
        "--user", GITEA_ROOTLESS_USER,
        "--workdir", GITEA_TEMP_PATH,
        "--env", f"GITEA_CUSTOM={GITEA_CUSTOM_PATH}",
        "--entrypoint", GITEA_BINARY,
        image,
        "--work-path", GITEA_WORK_PATH,
        "--custom-path", GITEA_CUSTOM_PATH,
        "--config", GITEA_CONFIG_PATH,
        "dump",
        "--tempdir", GITEA_TEMP_PATH,
        "--file", helper_dump,
        "--type", "zip",
    ]


def create_gitea_dump_offline(destination: Path) -> tuple[list[str], bool, bool]:
    """Create a native Gitea dump while the live container is stopped.

    Cleanup ordering is deliberate: Gitea restart is attempted first in every
    post-stop path, then the helper is removed. Any dump/copy/validation error is
    reported only after service recovery and helper cleanup have been attempted.
    """
    if not container_running():
        raise Stack4BackupError("Gitea must be running before a controlled-offline backup")

    image = container_image()
    helper = f"local-hybrid-ai-gitea-dump-{secrets.token_hex(8)}"
    helper_dump = "/tmp/gitea-state.zip"
    stopped = False
    restarted = False
    helper_created = False
    pending_error: Exception | None = None

    try:
        cp_stop = run_command(["docker", "stop", "--time", "30", GITEA_SERVICE])
        if cp_stop.returncode != 0:
            raise bounded_error("controlled Gitea stop", cp_stop)
        stopped = True

        cp_create = run_command(build_helper_create_command(image, helper, helper_dump))
        if cp_create.returncode != 0:
            raise bounded_error("Gitea dump helper creation", cp_create)
        helper_created = True

        cp_start = run_command(["docker", "start", "-a", helper])
        if cp_start.returncode != 0:
            raise bounded_error("offline gitea dump", cp_start)
    except Exception as exc:
        pending_error = exc
    finally:
        if stopped:
            cp_restart = run_command(["docker", "start", GITEA_SERVICE])
            restarted = cp_restart.returncode == 0
            if restarted:
                try:
                    wait_gitea_healthy()
                except Exception as exc:
                    restarted = False
                    if pending_error is None:
                        pending_error = exc
            else:
                restart_error = bounded_error("Gitea restart", cp_restart)
                if pending_error is None:
                    pending_error = restart_error
                else:
                    print(f"CRITICAL: {restart_error}", file=sys.stderr)

    if helper_created and pending_error is None:
        try:
            cp_copy = run_command(["docker", "cp", f"{helper}:{helper_dump}", str(destination)])
            if cp_copy.returncode != 0:
                raise bounded_error("docker cp of Gitea dump", cp_copy)
            os.chmod(destination, 0o600)
            with destination.open("rb") as handle:
                os.fsync(handle.fileno())
            members = validate_gitea_dump(destination)
        except Exception as exc:
            pending_error = exc
            members = []
    else:
        members = []

    if helper_created:
        try:
            remove_helper(helper)
        except Exception as exc:
            if pending_error is None:
                pending_error = exc
            else:
                print(f"CRITICAL: helper cleanup also failed: {exc}", file=sys.stderr)

    if not restarted:
        raise Stack4BackupError("Gitea was stopped for backup but service recovery was not verified")
    if pending_error is not None:
        raise pending_error
    return members, stopped, restarted


def execute_stack4_backup(backup_root: Path) -> CompletedStack4Backup:
    manifests = dr.load_manifests()
    plan = dr.resolve_plan(["4"])
    pki_resource, gitea_resource = select_resources(manifests, plan)
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
        members, stopped, restarted = create_gitea_dump_offline(gitea_path)

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
                {"stack_id": 0, "resource_id": PKI_RESOURCE_ID, "strategy": "archive", "sensitive": bool(pki_resource["sensitive"]), "restore_phase": pki_resource["config"].get("restore", {}).get("phase"), "relative_path": PKI_RELATIVE_PATH, "sha256": pki_hash, "size_bytes": pki_size},
                {"stack_id": 4, "resource_id": GITEA_RESOURCE_ID, "strategy": "gitea-native-dump", "sensitive": bool(gitea_resource["sensitive"]), "restore_phase": gitea_resource["config"].get("restore", {}).get("phase"), "relative_path": GITEA_RELATIVE_PATH, "sha256": gitea_hash, "size_bytes": gitea_size},
            ],
            "prerequisites": [],
        }
        dr_archive.validate_completed_metadata(metadata)
        metadata_path = temp / "backup.json"
        dr_archive.write_private(metadata_path, (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        metadata_hash = dr_archive.sha256_file(metadata_path)
        dr_archive.write_private(temp / "checksums.sha256", (f"{pki_hash}  {PKI_RELATIVE_PATH}\n{gitea_hash}  {GITEA_RELATIVE_PATH}\n{metadata_hash}  backup.json\n").encode("utf-8"))

        for relative, expected in ((PKI_RELATIVE_PATH, pki_hash), (GITEA_RELATIVE_PATH, gitea_hash), ("backup.json", metadata_hash)):
            if dr_archive.sha256_file(temp / relative) != expected:
                raise Stack4BackupError(f"pre-publication checksum mismatch: {relative}")
        for directory in (stack0_dir, stack4_dir, artifacts, temp):
            dr_archive.fsync_directory(directory)

        dr_archive.rename_noreplace(temp, final)
        dr_archive.fsync_directory(backup_root)
        return CompletedStack4Backup(final, pki_hash, pki_size, gitea_hash, gitea_size, len(members), stopped, restarted)
    except Exception:
        dr_archive.cleanup_temp(temp)
        raise
    finally:
        os.umask(old_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a consistent dependency-complete Stack4 Gitea DR backup set")
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
        print("- consistency mode: controlled offline")
        print(f"- Gitea restarted/healthy: {'PASS' if result.gitea_restarted else 'FAIL'}")
        print("- live Gitea state modified intentionally by tool: no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
