# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public command dispatcher behind the root ``./local-ai`` entry point."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from commands import completion, doctor, install_entry, inventory, runtime_lifecycle, status, upgrade_adopt, upgrade_entry

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "commands" / "recovery"
SCHEMA_VERSION = "1"
DEFAULT_BACKUP_ROOT = Path("/opt/local-hybrid-ai-backups")
BACKUP_ROOT_ENV = "DR_BACKUP_ROOT"
BACKUP_SET_RE = re.compile(r"^backup-\d{8}T\d{6}Z$")


def _run_internal(path: Path, args: list[str]) -> int:
    return subprocess.run([sys.executable, str(path), *args], cwd=ROOT).returncode


def _json_error(code: str, message: str, *, command: str | None = None) -> None:
    payload = {"schema_version": SCHEMA_VERSION, "success": False, "error": {"code": code, "message": message}}
    if command:
        payload["command"] = command
    print(json.dumps(payload, indent=2, sort_keys=True))


def _stack_selector_error(token: str, *, json_output: bool, command: str) -> int:
    message = f"stack selector must be a numeric id such as 7, not {token!r}"
    if json_output:
        _json_error("STACK_SELECTOR_INVALID", message, command=command)
    else:
        print(f"ERROR [STACK_SELECTOR_INVALID]: {message}", file=sys.stderr)
    return 2


def _upgrade_public_args(args: list[str]) -> tuple[list[str] | None, str | None]:
    """Translate the numeric public stack selector to the internal manifest id."""
    if not args or args[0] in {"--offline", "--yes", "check", "adopt"}:
        return list(args), None
    translated = list(args)
    stack_pos = 1 if translated[0] == "policy" else 0
    if len(translated) <= stack_pos:
        return translated, None
    token = translated[stack_pos]
    if not token.isdigit():
        return None, token
    translated[stack_pos] = f"stack{int(token)}"
    return translated, None


def _run_internal_json(path: Path, args: list[str], *, command: str) -> int:
    cp = subprocess.run([sys.executable, str(path), *args, "--json"], cwd=ROOT, text=True, capture_output=True, check=False)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or f"{command} failed").strip()
        _json_error("INTERNAL_COMMAND_FAILED", detail, command=command)
        return cp.returncode
    try:
        result = json.loads(cp.stdout)
    except json.JSONDecodeError:
        _json_error("INTERNAL_JSON_INVALID", f"private implementation for {command} returned invalid JSON", command=command)
        return 1
    print(json.dumps({"schema_version": SCHEMA_VERSION, "command": command, "success": True, "result": result}, indent=2, sort_keys=True))
    return 0


def build_backup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-ai backup", description="Create one atomic disaster-recovery backup set")
    parser.add_argument("--destination", help=f"backup root; defaults to ${BACKUP_ROOT_ENV} or {DEFAULT_BACKUP_ROOT}")
    parser.add_argument("--yes", action="store_true", help="confirm backup creation without an interactive prompt")
    return parser


def backup_command(args: list[str], json_output: bool) -> int:
    parser = build_backup_parser()
    ns = parser.parse_args(args)
    if not ns.yes:
        if json_output:
            _json_error("CONFIRMATION_REQUIRED", "backup creation requires --yes in JSON/non-interactive mode", command="backup")
            return 2
        if not sys.stdin.isatty():
            print("ERROR [CONFIRMATION_REQUIRED]: backup creation requires --yes when input is not interactive", file=sys.stderr)
            return 2
        destination = ns.destination or os.environ.get(BACKUP_ROOT_ENV) or str(DEFAULT_BACKUP_ROOT)
        try:
            answer = input(f"Create a new atomic DR backup set under {destination}? [y/N] ")
        except EOFError:
            print("Backup cancelled.")
            return 1
        if answer.strip().lower() not in {"y", "yes"}:
            print("Backup cancelled.")
            return 1
    internal: list[str] = []
    if ns.destination:
        internal.extend(["--destination", ns.destination])
    if json_output:
        internal.append("--json")
    return _run_internal(RECOVERY / "backup-all.py", internal)


def _backup_root(override: str | None = None) -> Path:
    raw = override or os.environ.get(BACKUP_ROOT_ENV) or str(DEFAULT_BACKUP_ROOT)
    return Path(raw).expanduser().resolve()


def _backup_sets(root: Path) -> list[dict[str, object]]:
    if not root.exists():
        return []
    if not root.is_dir():
        raise OSError(f"backup root is not a directory: {root}")
    records: list[dict[str, object]] = []
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink() or not BACKUP_SET_RE.fullmatch(path.name):
            continue
        metadata_path = path / "backup.json"
        checksums_path = path / "checksums.sha256"
        record: dict[str, object] = {"name": path.name, "path": str(path), "status": "invalid"}
        if metadata_path.is_file() and not metadata_path.is_symlink() and checksums_path.is_file() and not checksums_path.is_symlink():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                valid = (
                    isinstance(metadata, dict)
                    and metadata.get("schema_version") == 1
                    and metadata.get("kind") == "local-hybrid-ai-backup-set"
                    and isinstance(metadata.get("source_commit"), str)
                    and isinstance(metadata.get("resolved_stacks"), list)
                )
                if valid:
                    record.update({"status": "completed", "created_at": metadata.get("created_at"), "source_commit": metadata.get("source_commit"), "resolved_stacks": metadata.get("resolved_stacks", [])})
            except (OSError, json.JSONDecodeError):
                pass
        records.append(record)
    return sorted(records, key=lambda item: str(item["name"]), reverse=True)


def list_backup_sets(backup_root: str | None, *, json_output: bool) -> int:
    root = _backup_root(backup_root)
    try:
        records = _backup_sets(root)
    except OSError as exc:
        if json_output:
            _json_error("BACKUP_ROOT_INVALID", str(exc), command="restore.list-backup-sets")
        else:
            print(f"ERROR [BACKUP_ROOT_INVALID]: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "command": "restore.list-backup-sets", "success": True, "backup_root": str(root), "backup_sets": records}, indent=2, sort_keys=True))
        return 0
    print(f"Backup root: {root}")
    if not records:
        print("No backup sets found.")
        return 0
    print("STATUS     BACKUP SET                   SOURCE COMMIT  STACKS")
    print("---------- ---------------------------- ------------- ------")
    for record in records:
        source = str(record.get("source_commit") or "-")[:12]
        stacks = ",".join(str(value) for value in record.get("resolved_stacks", [])) or "-"
        print(f"{str(record['status']).upper():<10} {str(record['name']):<28} {source:<13} {stacks}")
    print("\nThe PATH for a restore command is <backup-root>/<backup-set>.")
    return 0


def build_restore_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-ai restore", description="Disaster-recovery operations for Local Hybrid AI")
    actions = parser.add_subparsers(dest="restore_action", metavar="ACTION")
    listing = actions.add_parser("list-backup-sets", help="list available recovery points")
    listing.add_argument("--backup-root", help=f"backup root; defaults to ${BACKUP_ROOT_ENV} or {DEFAULT_BACKUP_ROOT}")
    plan = actions.add_parser("plan", help="validate a recovery point and show restore ordering")
    plan.add_argument("backup_set", help="completed backup-set directory")
    drill = actions.add_parser("drill", help="restore into an isolated destination and verify it")
    drill.add_argument("backup_set", help="completed backup-set directory")
    drill.add_argument("--destination", required=True, help="isolated drill destination")
    apply = actions.add_parser("apply", help="preflight or execute a clean-target restore")
    apply.add_argument("backup_set", help="completed backup-set directory")
    mode = apply.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-clean-target", action="store_true", help="read-only clean-target preflight")
    mode.add_argument("--execute", action="store_true", help="execute the restore")
    apply.add_argument("--confirm-clean-target", action="store_true", help="mandatory with --execute")
    apply.add_argument("--memory-sync-ssh-bootstrap", help="external Stack6 memory-sync SSH bootstrap directory")
    resume = actions.add_parser("resume", help="resume and verify an interrupted reconstructed target")
    resume.add_argument("backup_set", help="completed backup-set directory")
    resume.add_argument("--memory-sync-ssh-bootstrap", required=True, help="external Stack6 memory-sync SSH bootstrap directory")
    return parser


def restore_command(args: list[str], json_output: bool) -> int:
    parser = build_restore_parser()
    ns = parser.parse_args(args)
    if ns.restore_action is None:
        parser.print_help()
        return 0
    if ns.restore_action == "list-backup-sets":
        return list_backup_sets(ns.backup_root, json_output=json_output)
    action = ns.restore_action
    if action == "plan":
        script, internal = RECOVERY / "restore-all.py", [ns.backup_set, "--dry-run"]
    elif action == "drill":
        script, internal = RECOVERY / "restore-drill.py", [ns.backup_set, "--destination", ns.destination]
    elif action == "apply":
        script, internal = RECOVERY / "restore-live.py", [ns.backup_set]
        internal.append("--check-clean-target" if ns.check_clean_target else "--execute")
        if ns.confirm_clean_target:
            internal.append("--confirm-clean-target")
        if ns.memory_sync_ssh_bootstrap:
            internal.extend(["--memory-sync-ssh-bootstrap", ns.memory_sync_ssh_bootstrap])
    else:
        script, internal = RECOVERY / "restore-resume.py", [ns.backup_set, "--memory-sync-ssh-bootstrap", ns.memory_sync_ssh_bootstrap]
    if json_output:
        return _run_internal_json(script, internal, command=f"restore.{action}")
    return _run_internal(script, internal)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-ai", description="Supported management CLI for the Local Hybrid AI installation")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("install", help="install or reconcile stacks")
    sub.add_parser("backup", help="create a recovery point")
    sub.add_parser("restore", help="list, plan, drill, apply or resume disaster recovery")
    sub.add_parser("status", help="show operational stack state, runtime health and drift")
    sub.add_parser("doctor", help="diagnose management prerequisites and environment consistency")
    sub.add_parser("inventory", help="validate and rescan manifest-declared component topology")
    sub.add_parser("completion", help="emit Bash or Zsh completion integration")
    for action in ("start", "stop"):
        runtime = sub.add_parser(action, help=f"{action} one prepared stack runtime")
        runtime.add_argument("stack", help="numeric stack id, for example 7")
    sub.add_parser("upgrade", help="inspect versions and manage component upgrades")
    return parser


def _upgrade_adopt(args: list[str], *, json_output: bool) -> int:
    try:
        return upgrade_adopt.main(args, json_output=json_output)
    except upgrade_adopt.AdoptionError as exc:
        if json_output:
            print(json.dumps({"schema_version": upgrade_adopt.SCHEMA_VERSION, "command": "upgrade.adopt", "success": False, "error": {"code": exc.code, "message": str(exc)}}, indent=2, sort_keys=True))
        else:
            print(f"UPGRADE ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    raw = [arg for arg in raw if arg != "--json"]
    if raw and raw[0] == "__complete":
        try:
            print("\n".join(completion.complete(raw[1:])))
            return 0
        except Exception:
            return 0
    if raw and raw[0] == "completion":
        return completion.main(raw[1:])
    if raw and raw[0] == "install":
        if json_output:
            return install_entry.main(raw[1:])
        return _run_internal(ROOT / "commands" / "install.py", raw[1:])
    if raw and raw[0] == "backup":
        return backup_command(raw[1:], json_output)
    if raw and raw[0] == "restore":
        return restore_command(raw[1:], json_output)
    if raw and raw[0] == "inventory":
        return inventory.main(raw[1:], json_output=json_output)
    if raw and raw[0] == "upgrade":
        if len(raw) >= 2 and raw[1] == "adopt":
            return _upgrade_adopt(raw[2:], json_output=json_output)
        upgrade_args, invalid = _upgrade_public_args(raw[1:])
        if invalid is not None:
            return _stack_selector_error(invalid, json_output=json_output, command="upgrade")
        return upgrade_entry.main(upgrade_args or [], json_output=json_output)
    parser = build_parser()
    ns = parser.parse_args(raw)
    if ns.command is None:
        parser.print_help()
        return 0
    if ns.command == "status":
        return status.main(json_output=json_output)
    if ns.command == "doctor":
        return doctor.main(json_output=json_output)
    if ns.command == "inventory":
        return inventory.main([], json_output=json_output)
    if ns.command in {"start", "stop"}:
        if not ns.stack.isdigit():
            return _stack_selector_error(ns.stack, json_output=json_output, command=ns.command)
        return runtime_lifecycle.main(ns.command, ns.stack, json_output=json_output)
    parser.error("unsupported command")
    return 2
