#!/usr/bin/env python3
"""Real DR backup adapter for Stack4 / Gitea.

Creates a dependency-complete backup set for Stack4 containing:
- Stack0 platform PKI archive
- Stack4 native Gitea dump ZIP

For consistency, the live Gitea container is stopped briefly. Before the stop,
the adapter inspects the deployed container and derives the execution context
needed by the dump helper: image, effective configured user, working path,
GITEA_CUSTOM and the actual app.ini path. The helper then uses the same image
and mounted Gitea volumes while the live instance is stopped.

Rootless operation is not part of the DR contract. A rootless deployment may
have an explicit uid/gid; a rootful deployment may rely on the image default
user. The adapter preserves whichever context is actually deployed and fails
closed if it cannot determine the active Gitea configuration path.

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
GITEA_TEMP_PATH = "/tmp"


class Stack4BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class GiteaExecutionContext:
    image: str
    user: str | None
    work_path: str | None
    custom_path: str | None
    config_path: str


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


def _env_map(values: object) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def _candidate_config_paths(config: dict, mounts: object) -> list[str]:
    env = _env_map(config.get("Env"))
    candidates: list[str] = []

    for key in ("GITEA_APP_INI", "GITEA_CONFIG", "GITEA_CONFIG_PATH"):
        value = env.get(key, "").strip()
        if value.startswith("/"):
            candidates.append(value)

    custom = env.get("GITEA_CUSTOM", "").strip()
    if custom.startswith("/"):
        candidates.extend([
            f"{custom.rstrip('/')}/app.ini",
            f"{custom.rstrip('/')}/conf/app.ini",
        ])

    if isinstance(mounts, list):
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            destination = str(mount.get("Destination") or "").strip()
            if destination.startswith("/"):
                destination = destination.rstrip("/")
                candidates.extend([
                    f"{destination}/app.ini",
                    f"{destination}/conf/app.ini",
                ])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def discover_gitea_execution_context(service: str = GITEA_SERVICE) -> GiteaExecutionContext:
    """Discover dump execution context from the live container.

    No secret-bearing file is read. app.ini discovery tests candidate paths for
    existence only. If the active config cannot be identified, backup aborts
    before the controlled stop rather than falling back to historical rootless
    assumptions.
    """
    cp = run_command(["docker", "inspect", service])
    if cp.returncode != 0:
        raise bounded_error("Gitea container inspection", cp)
    try:
        docs = json.loads(cp.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Stack4BackupError("Gitea container inspection returned invalid JSON") from exc
    if not isinstance(docs, list) or len(docs) != 1 or not isinstance(docs[0], dict):
        raise Stack4BackupError("Gitea container inspection returned an unexpected structure")

    doc = docs[0]
    config = doc.get("Config")
    if not isinstance(config, dict):
        raise Stack4BackupError("Gitea container inspection is missing Config")

    image = str(config.get("Image") or "").strip()
    if not image or any(ch.isspace() for ch in image):
        raise Stack4BackupError("Gitea container image could not be resolved safely")

    env = _env_map(config.get("Env"))
    user_value = str(config.get("User") or "").strip()
    user = user_value or None

    work_value = env.get("GITEA_WORK_DIR", "").strip()
    if not work_value:
        work_value = str(config.get("WorkingDir") or "").strip()
    work_path = work_value if work_value.startswith("/") else None

    custom_value = env.get("GITEA_CUSTOM", "").strip()
    custom_path = custom_value if custom_value.startswith("/") else None

    config_path = None
    for candidate in _candidate_config_paths(config, doc.get("Mounts")):
        cp_test = run_command(["docker", "exec", service, "test", "-f", candidate])
        if cp_test.returncode == 0:
            config_path = candidate
            break

    if config_path is None:
        raise Stack4BackupError(
            "active Gitea app.ini path could not be discovered safely; "
            "refusing to use hard-coded rootless/rootful defaults"
        )

    if custom_path is None:
        parent = PurePosixPath(config_path).parent
        custom_path = str(parent.parent if parent.name == "conf" else parent)

    return GiteaExecutionContext(
        image=image,
        user=user,
        work_path=work_path,
        custom_path=custom_path,
        config_path=config_path,
    )


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


def build_helper_create_command(context: GiteaExecutionContext, helper: str, helper_dump: str) -> list[str]:
    """Build a helper command from the currently deployed execution context."""
    command = [
        "docker", "create",
        "--name", helper,
        "--network", "none",
        "--volumes-from", GITEA_SERVICE,
    ]
    if context.user:
        command.extend(["--user", context.user])

    # Gitea packaging must run from the temp directory used by --tempdir.
    command.extend(["--workdir", GITEA_TEMP_PATH])
    if context.custom_path:
        command.extend(["--env", f"GITEA_CUSTOM={context.custom_path}"])

    # Use the image's PATH instead of assuming a rootless-specific binary path.
    command.extend(["--entrypoint", "gitea", context.image])
    if context.work_path:
        command.extend(["--work-path", context.work_path])
    if context.custom_path:
        command.extend(["--custom-path", context.custom_path])
    command.extend([
        "--config", context.config_path,
        "dump",
        "--tempdir", GITEA_TEMP_PATH,
        "--file", helper_dump,
        "--type", "zip",
    ])
    return command


def create_gitea_dump_offline(destination: Path) -> tuple[list[str], bool, bool]:
    """Create a native Gitea dump while the live container is stopped.

    Execution context is discovered while the service is still live. Cleanup
    ordering is deliberate: Gitea restart is attempted first in every post-stop
    path, then the helper is removed. Any dump/copy/validation error is reported
    only after service recovery and helper cleanup have been attempted.
    """
    if not container_running():
        raise Stack4BackupError("Gitea must be running before a controlled-offline backup")

    context = discover_gitea_execution_context()
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

        cp_create = run_command(build_helper_create_command(context, helper, helper_dump))
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
