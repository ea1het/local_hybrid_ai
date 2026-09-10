#!/usr/bin/env python3
"""Manifest-driven disaster-recovery engine for local_hybrid_ai.

Current milestones:
- plan: read-only recovery classification and dependency closure.
- backup --dry-run: read-only backup-set planning, destination resolution,
  destination preflight and runtime/source correspondence checks.

No backup adapter executes yet. Runtime preflight may inspect Docker and presence of
protected configuration, but it never prints secret values or creates artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
BACKUP_SET_SCHEMA_VERSION = 1
DEFAULT_BACKUP_ROOT = Path("/opt/local-hybrid-ai-backups")
BACKUP_ROOT_ENV = "DR_BACKUP_ROOT"
BACKUP_SET_NAME_PATTERN = "backup-YYYYMMDDTHHMMSSZ"
ARTIFACT_EXTENSIONS = {
    "archive": ".tar",
    "postgres-custom-dump": ".dump",
    "gitea-native-dump": ".zip",
}


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryEntry:
    stack_id: int
    directory: str
    stack_mode: str
    resource_id: str | None
    resource_class: str | None
    strategy: str | None
    sensitive: bool | None
    restore_phase: str | None
    disposition: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "directory": self.directory,
            "stack_mode": self.stack_mode,
            "resource_id": self.resource_id,
            "resource_class": self.resource_class,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
            "restore_phase": self.restore_phase,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class BackupArtifactPlan:
    stack_id: int
    resource_id: str
    strategy: str
    sensitive: bool
    restore_phase: str | None
    relative_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
            "restore_phase": self.restore_phase,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True)
class BackupPrerequisitePlan:
    stack_id: int
    resource_id: str
    kind: str
    strategy: str
    sensitive: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "kind": self.kind,
            "strategy": self.strategy,
            "sensitive": self.sensitive,
        }


@dataclass(frozen=True)
class DestinationPreflight:
    root: Path
    source: str
    root_exists: bool
    nearest_existing_parent: Path
    writable_parent: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "source": self.source,
            "root_exists": self.root_exists,
            "nearest_existing_parent": str(self.nearest_existing_parent),
            "writable_parent": self.writable_parent,
            "backup_set_name_pattern": BACKUP_SET_NAME_PATTERN,
            "creation_required": not self.root_exists,
        }


@dataclass(frozen=True)
class RuntimeCheck:
    stack_id: int | None
    resource_id: str | None
    check: str
    status: str
    blocking: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stack_id": self.stack_id,
            "resource_id": self.resource_id,
            "check": self.check,
            "status": self.status,
            "blocking": self.blocking,
            "detail": self.detail,
        }


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_manifest_tool(*args: str) -> object:
    try:
        cp = subprocess.run(
            [sys.executable, str(MANIFEST_TOOL), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RecoveryError(f"manifest resolver failed: {detail}") from exc

    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RecoveryError("manifest resolver returned invalid JSON") from exc


def load_manifests() -> dict[int, dict]:
    raw = run_manifest_tool("list", "--json")
    if not isinstance(raw, list):
        raise RecoveryError("manifest list is not an array")
    manifests: dict[int, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise RecoveryError("manifest list contains an invalid entry")
        manifests[item["id"]] = item
    return manifests


def resolve_plan(selectors: list[str], *, target: bool = False) -> list[int]:
    args = ["plan", *selectors, "--json"]
    if target:
        args.append("--target")
    raw = run_manifest_tool(*args)
    if not isinstance(raw, list) or not all(isinstance(value, int) for value in raw):
        raise RecoveryError("manifest dependency plan is invalid")
    return raw


def git_head() -> str:
    cp = run_command(["git", "rev-parse", "HEAD"])
    if cp.returncode != 0:
        raise RecoveryError("cannot determine Git HEAD for backup-set provenance")
    head = cp.stdout.strip()
    if len(head) != 40:
        raise RecoveryError("unexpected Git HEAD format")
    return head


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
        raise RecoveryError("backup destination cannot be empty")

    path = Path(raw)
    if not path.is_absolute():
        raise RecoveryError("backup destination must be an absolute path")

    normalized = Path(os.path.abspath(os.path.normpath(str(path))))
    if normalized == Path("/"):
        raise RecoveryError("backup destination cannot be filesystem root")
    return normalized, source


def nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def preflight_backup_destination(root: Path, source: str) -> DestinationPreflight:
    if root.exists() and not root.is_dir():
        raise RecoveryError(f"backup destination exists but is not a directory: {root}")

    parent = root if root.exists() else nearest_existing_parent(root.parent)
    if not parent.exists() or not parent.is_dir():
        raise RecoveryError(f"cannot resolve an existing parent for backup destination: {root}")

    writable = os.access(parent, os.W_OK | os.X_OK)
    if not writable:
        raise RecoveryError(f"backup destination parent is not writable by current user: {parent}")

    return DestinationPreflight(
        root=root,
        source=source,
        root_exists=root.exists(),
        nearest_existing_parent=parent,
        writable_parent=writable,
    )


def read_dotenv_presence(path: Path) -> dict[str, str]:
    """Read dotenv names/values without shell evaluation.

    Values are retained only in-memory for path/config presence checks and are
    never included in recovery output. This parser intentionally supports the
    simple KEY=VALUE contract used by the platform and does not execute expansion.
    """
    if not path.is_file():
        raise RecoveryError(f"missing operational environment file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RecoveryError(f"cannot read operational environment file metadata: {exc}") from exc

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def require_env_value(values: dict[str, str], key: str, *, label: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise RecoveryError(f"required {label} is missing or empty in operational .env")
    return value


def resolve_base_path(values: dict[str, str]) -> Path:
    raw = require_env_value(values, "BASE_PATH", label="BASE_PATH")
    path = Path(raw)
    if not path.is_absolute():
        raise RecoveryError("BASE_PATH in operational .env must be an absolute path")
    normalized = Path(os.path.abspath(os.path.normpath(str(path))))
    if not normalized.is_dir():
        raise RecoveryError(f"BASE_PATH does not exist as a directory: {normalized}")
    return normalized


def expand_runtime_path(raw: str, base_path: Path) -> Path:
    token = "${BASE_PATH}"
    if raw == token:
        expanded = str(base_path)
    elif raw.startswith(token + "/"):
        expanded = str(base_path) + raw[len(token):]
    elif "$" in raw:
        raise RecoveryError("runtime recovery path contains unsupported variable expansion")
    else:
        expanded = raw
    path = Path(expanded)
    if not path.is_absolute():
        raise RecoveryError("runtime recovery path must resolve to an absolute path")
    return Path(os.path.abspath(os.path.normpath(str(path))))


def owned_container(manifest: dict, service: str) -> bool:
    return f"container:{service}" in manifest.get("owns", [])


def docker_state(service: str, runner: CommandRunner) -> str | None:
    cp = runner([
        "docker",
        "inspect",
        "-f",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
        service,
    ])
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


def gitea_help_flags(text: str) -> list[str]:
    return sorted(set(re.findall(r"(?<![A-Za-z0-9-])--[a-z0-9][a-z0-9-]*", text.lower())))


def preflight_runtime_sources(
    manifests: dict[int, dict],
    plan: list[int],
    *,
    env_path: Path = ROOT / ".env",
    runner: CommandRunner = run_command,
    docker_available: bool | None = None,
) -> list[RuntimeCheck]:
    values = read_dotenv_presence(env_path)
    base_path = resolve_base_path(values)
    checks: list[RuntimeCheck] = [
        RuntimeCheck(None, None, "operational-env", "OK", True, "present and readable"),
        RuntimeCheck(None, None, "base-path", "OK", True, f"resolved to {base_path}"),
    ]

    needs_docker = False
    for sid in plan:
        for resource in manifests[sid]["recovery"].get("resources", []):
            if resource["strategy"] in {"postgres-custom-dump", "gitea-native-dump"}:
                needs_docker = True
                break

    if docker_available is None:
        docker_available = shutil.which("docker") is not None
    if needs_docker and not docker_available:
        raise RecoveryError("Docker CLI is required for runtime recovery preflight")

    for sid in plan:
        manifest = manifests[sid]
        for resource in manifest["recovery"].get("resources", []):
            rid = resource["id"]
            strategy = resource["strategy"]
            source = resource["config"]["source"]

            if strategy == "archive":
                path = expand_runtime_path(source["path"], base_path)
                if not path.exists():
                    raise RecoveryError(f"stack{sid} {rid}: declared runtime source does not exist: {path}")
                if path.is_dir():
                    try:
                        nonempty = next(path.iterdir(), None) is not None
                    except OSError as exc:
                        raise RecoveryError(f"stack{sid} {rid}: cannot inspect runtime source: {exc}") from exc
                    if not nonempty:
                        raise RecoveryError(f"stack{sid} {rid}: declared runtime source directory is empty")
                    detail = f"runtime path exists and is non-empty: {path}"
                else:
                    if path.stat().st_size == 0:
                        raise RecoveryError(f"stack{sid} {rid}: declared runtime source file is empty")
                    detail = f"runtime path exists and is non-empty: {path}"
                checks.append(RuntimeCheck(sid, rid, "runtime-source", "OK", True, detail))
                continue

            if strategy == "external-config":
                key = source["key"]
                present = bool(values.get(key, "").strip())
                if not present:
                    raise RecoveryError(f"stack{sid} {rid}: required protected configuration is missing or empty")
                checks.append(
                    RuntimeCheck(
                        sid,
                        rid,
                        "external-config",
                        "OK",
                        True,
                        "required protected value is present; value not displayed",
                    )
                )
                continue

            if strategy == "git":
                repository_env = source.get("repository_env")
                if repository_env:
                    if not values.get(repository_env, "").strip():
                        raise RecoveryError(f"stack{sid} {rid}: declared Git repository configuration is missing")
                    detail = "declared Git repository configuration is present; value not displayed"
                    status = "OK"
                    blocking = True
                else:
                    detail = "externalized Git source declared without repository_env; contract presence only"
                    status = "DECLARED"
                    blocking = False
                checks.append(RuntimeCheck(sid, rid, "externalized-git", status, blocking, detail))
                continue

            if strategy in {"postgres-custom-dump", "gitea-native-dump"}:
                service = source["service"]
                if not owned_container(manifest, service):
                    raise RecoveryError(
                        f"stack{sid} {rid}: source service {service} is not declared as stack-owned container"
                    )
                state = docker_state(service, runner)
                if state is None:
                    raise RecoveryError(f"stack{sid} {rid}: declared Docker service is absent: {service}")
                if not state.startswith("running"):
                    raise RecoveryError(f"stack{sid} {rid}: declared Docker service is not running: {service} ({state})")
                checks.append(
                    RuntimeCheck(sid, rid, "docker-service", "OK", True, f"{service}={state}")
                )

            if strategy == "postgres-custom-dump":
                db = require_env_value(values, source["database_env"], label="database configuration")
                user_env = source.get("user_env")
                user = require_env_value(values, user_env, label="database user configuration") if user_env else "postgres"
                cp = runner(["docker", "exec", source["service"], "pg_isready", "-d", db, "-U", user])
                if cp.returncode != 0:
                    raise RecoveryError(f"stack{sid} {rid}: PostgreSQL source did not pass pg_isready")
                checks.append(
                    RuntimeCheck(
                        sid,
                        rid,
                        "postgres-source",
                        "OK",
                        True,
                        "configured database/user resolved and PostgreSQL accepts connections",
                    )
                )
                continue

            if strategy == "gitea-native-dump":
                service = source["service"]
                version_cp = runner(["docker", "exec", service, "gitea", "--version"])
                if version_cp.returncode != 0 or not version_cp.stdout.strip():
                    raise RecoveryError(f"stack{sid} {rid}: cannot determine Gitea version")
                help_cp = runner(["docker", "exec", service, "gitea", "dump", "--help"])
                if help_cp.returncode != 0:
                    raise RecoveryError(f"stack{sid} {rid}: gitea dump --help is unavailable")
                flags = gitea_help_flags(help_cp.stdout + "\n" + help_cp.stderr)
                version = version_cp.stdout.strip().splitlines()[0]
                checks.append(
                    RuntimeCheck(
                        sid,
                        rid,
                        "gitea-native-dump",
                        "OK",
                        True,
                        f"version={version}; dump help available; flags={','.join(flags) if flags else '(none parsed)'}",
                    )
                )
                continue

    return checks


def disposition_for(resource_class: str, strategy: str) -> str:
    if resource_class == "externalized":
        return "EXTERNAL"
    if strategy == "external-config":
        return "REQUIRE"
    return "BACKUP"


def resource_restore_phase(resource: dict) -> str | None:
    config = resource.get("config", {})
    if not isinstance(config, dict):
        return None
    restore = config.get("restore")
    if not isinstance(restore, dict):
        return None
    phase = restore.get("phase")
    return phase if isinstance(phase, str) else None


def build_plan_entries(plan: list[int], manifests: dict[int, dict]) -> list[RecoveryEntry]:
    entries: list[RecoveryEntry] = []
    for stack_id in plan:
        try:
            manifest = manifests[stack_id]
            recovery = manifest["recovery"]
            contract = recovery["contract"]
            mode = contract["mode"]
        except (KeyError, TypeError) as exc:
            raise RecoveryError(f"stack{stack_id}: invalid recovery contract: {exc}") from exc

        resources = recovery.get("resources")
        if not resources:
            entries.append(
                RecoveryEntry(
                    stack_id=stack_id,
                    directory=manifest["directory"],
                    stack_mode=mode,
                    resource_id=None,
                    resource_class=None,
                    strategy=None,
                    sensitive=None,
                    restore_phase=None,
                    disposition="RECONSTRUCT",
                )
            )
            continue

        for resource in resources:
            resource_class = resource["class"]
            strategy = resource["strategy"]
            entries.append(
                RecoveryEntry(
                    stack_id=stack_id,
                    directory=manifest["directory"],
                    stack_mode=mode,
                    resource_id=resource["id"],
                    resource_class=resource_class,
                    strategy=strategy,
                    sensitive=resource["sensitive"],
                    restore_phase=resource_restore_phase(resource),
                    disposition=disposition_for(resource_class, strategy),
                )
            )
    return entries


def artifact_relative_path(entry: RecoveryEntry) -> str:
    if entry.disposition != "BACKUP" or entry.resource_id is None or entry.strategy is None:
        raise RecoveryError("artifact path requested for non-backup recovery entry")
    extension = ARTIFACT_EXTENSIONS.get(entry.strategy)
    if extension is None:
        raise RecoveryError(f"strategy {entry.strategy} has no artifact extension contract")
    return f"artifacts/stack{entry.stack_id}/{entry.resource_id}{extension}"


def build_backup_plan(
    entries: list[RecoveryEntry],
) -> tuple[list[BackupArtifactPlan], list[BackupPrerequisitePlan]]:
    artifacts: list[BackupArtifactPlan] = []
    prerequisites: list[BackupPrerequisitePlan] = []
    for entry in entries:
        if entry.disposition == "BACKUP":
            if entry.resource_id is None or entry.strategy is None or entry.sensitive is None:
                raise RecoveryError("backup entry is missing normalized recovery fields")
            artifacts.append(
                BackupArtifactPlan(
                    stack_id=entry.stack_id,
                    resource_id=entry.resource_id,
                    strategy=entry.strategy,
                    sensitive=entry.sensitive,
                    restore_phase=entry.restore_phase,
                    relative_path=artifact_relative_path(entry),
                )
            )
        elif entry.disposition in {"REQUIRE", "EXTERNAL"}:
            if entry.resource_id is None or entry.strategy is None or entry.sensitive is None:
                raise RecoveryError("prerequisite entry is missing normalized recovery fields")
            prerequisites.append(
                BackupPrerequisitePlan(
                    stack_id=entry.stack_id,
                    resource_id=entry.resource_id,
                    kind=entry.disposition,
                    strategy=entry.strategy,
                    sensitive=entry.sensitive,
                )
            )
    return artifacts, prerequisites


def backup_plan_payload(
    selectors: list[str],
    resolved_stacks: list[int],
    artifacts: list[BackupArtifactPlan],
    prerequisites: list[BackupPrerequisitePlan],
    *,
    source_commit: str,
    destination: DestinationPreflight,
    runtime_checks: list[RuntimeCheck],
) -> dict[str, object]:
    return {
        "schema_version": BACKUP_SET_SCHEMA_VERSION,
        "kind": "local-hybrid-ai-backup-plan",
        "source_commit": source_commit,
        "requested": selectors,
        "resolved_stacks": resolved_stacks,
        "destination": destination.as_dict(),
        "runtime_preflight": [check.as_dict() for check in runtime_checks],
        "layout": {
            "metadata": "backup.json",
            "checksums": "checksums.sha256",
            "artifact_root": "artifacts/",
        },
        "artifacts": [artifact.as_dict() for artifact in artifacts],
        "prerequisites": [prerequisite.as_dict() for prerequisite in prerequisites],
        "changes_made": False,
    }


def print_human(selectors: list[str], plan: list[int], entries: list[RecoveryEntry]) -> None:
    print("Requested:", " ".join(selectors))
    print("Resolved dependency plan:", " -> ".join(f"stack{sid}" for sid in plan))
    print("Recovery plan:")
    for entry in entries:
        prefix = f"stack{entry.stack_id} {entry.directory}"
        if entry.disposition == "RECONSTRUCT":
            print(f"- {prefix}: RECONSTRUCT (mode={entry.stack_mode}; no recovery artifact)")
            continue
        sensitivity = "sensitive" if entry.sensitive else "non-sensitive"
        phase = f"; restore={entry.restore_phase}" if entry.restore_phase else ""
        print(
            f"- {prefix}: {entry.disposition} {entry.resource_id} "
            f"[{entry.resource_class}; strategy={entry.strategy}; {sensitivity}{phase}]"
        )
    print()
    print("No changes made.")
    print("Planning does not access secret values, Docker runtime, or backup artifacts.")


def print_json(selectors: list[str], plan: list[int], entries: list[RecoveryEntry]) -> None:
    payload = {
        "schema_version": 1,
        "requested": selectors,
        "resolved_stacks": plan,
        "entries": [entry.as_dict() for entry in entries],
        "changes_made": False,
    }
    print(json.dumps(payload, indent=2))


def print_backup_human(payload: dict[str, object]) -> None:
    print("Backup dry-run")
    print("Source commit:", payload["source_commit"])
    print("Requested:", " ".join(payload["requested"]))
    print(
        "Resolved dependency plan:",
        " -> ".join(f"stack{sid}" for sid in payload["resolved_stacks"]),
    )
    destination = payload["destination"]
    print("Destination preflight:")
    print(f"- root: {destination['root']}")
    print(f"- selected by: {destination['source']}")
    print(f"- root exists: {'yes' if destination['root_exists'] else 'no; would create during execution'}")
    print(f"- nearest existing parent: {destination['nearest_existing_parent']}")
    print(f"- writable by current user: {'yes' if destination['writable_parent'] else 'no'}")
    print(f"- backup-set directory pattern: {destination['backup_set_name_pattern']}")

    print("Runtime/source preflight:")
    for check in payload["runtime_preflight"]:
        scope = "platform"
        if check["stack_id"] is not None:
            scope = f"stack{check['stack_id']} {check['resource_id']}"
        blocking = "blocking" if check["blocking"] else "informational"
        print(f"- {scope}: {check['check']}={check['status']} [{blocking}] — {check['detail']}")

    print("Planned backup-set layout:")
    layout = payload["layout"]
    print(f"- metadata: {layout['metadata']}")
    print(f"- checksums: {layout['checksums']}")
    print(f"- artifacts: {layout['artifact_root']}")
    print("Artifacts:")
    for artifact in payload["artifacts"]:
        sensitivity = "sensitive" if artifact["sensitive"] else "non-sensitive"
        phase = f"; restore={artifact['restore_phase']}" if artifact["restore_phase"] else ""
        print(
            f"- stack{artifact['stack_id']} {artifact['resource_id']}: "
            f"{artifact['relative_path']} [{artifact['strategy']}; {sensitivity}{phase}]"
        )
    print("Prerequisites:")
    for prerequisite in payload["prerequisites"]:
        sensitivity = "sensitive" if prerequisite["sensitive"] else "non-sensitive"
        print(
            f"- stack{prerequisite['stack_id']} {prerequisite['resource_id']}: "
            f"{prerequisite['kind']} [{prerequisite['strategy']}; {sensitivity}]"
        )
    print()
    print("No changes made.")
    print("Destination and runtime/source preflight are read-only; no backup artifacts were created.")
    print("Protected values were checked only for presence and were not displayed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manifest-driven disaster-recovery engine")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="show effective recovery plan")
    plan_parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    plan_parser.add_argument("--target", action="store_true", help="use target dependency graph")
    plan_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    backup_parser = sub.add_parser("backup", help="plan a backup set; execution is not implemented yet")
    backup_parser.add_argument("stacks", nargs="+", help="stack ids, stackN, directory names, or all")
    backup_parser.add_argument("--target", action="store_true", help="use target dependency graph")
    backup_parser.add_argument(
        "--destination",
        help=(
            "backup root directory; precedence: --destination, DR_BACKUP_ROOT, "
            f"default {DEFAULT_BACKUP_ROOT}"
        ),
    )
    backup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="required in the current milestone; preflight destination/runtime and plan without writing",
    )
    backup_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    args = parser.parse_args()

    if args.command == "backup" and not args.dry_run:
        print("ERROR: backup execution is not implemented yet; use --dry-run", file=sys.stderr)
        return 2

    try:
        manifests = load_manifests()
        plan = resolve_plan(args.stacks, target=args.target)
        entries = build_plan_entries(plan, manifests)

        if args.command == "backup":
            backup_root, destination_source = resolve_backup_root(args.destination)
            destination = preflight_backup_destination(backup_root, destination_source)
            runtime_checks = preflight_runtime_sources(manifests, plan)
            artifacts, prerequisites = build_backup_plan(entries)
            payload = backup_plan_payload(
                args.stacks,
                plan,
                artifacts,
                prerequisites,
                source_commit=git_head(),
                destination=destination,
                runtime_checks=runtime_checks,
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print_backup_human(payload)
            return 0
    except RecoveryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print_json(args.stacks, plan, entries)
    else:
        print_human(args.stacks, plan, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())