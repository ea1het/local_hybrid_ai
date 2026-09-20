#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Structured Restore API backed exclusively by package-owned implementation."""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

RESTORE_ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1"
DEFAULT_BACKUP_ROOT = Path("/opt/local-hybrid-ai-backups")
BACKUP_ROOT_ENV = "DR_BACKUP_ROOT"
BACKUP_SET_RE = re.compile(r"^backup-\d{8}T\d{6}Z$")


def _load(name: str):
    root = str(RESTORE_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(name)
    finally:
        if added:
            try: sys.path.remove(root)
            except ValueError: pass


def _envelope(command: str, result: dict[str, object]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": command, "success": True, "result": result}


def _failure(command: str, code: str, exc: Exception) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": command, "success": False, "error": {"code": code, "message": str(exc)}}


def _operation(command: str, code: str, callback: Callable[[], dict[str, object]]) -> dict[str, object]:
    try: return _envelope(command, callback())
    except Exception as exc: return _failure(command, code, exc)


def _backup_root(override: str | Path | None = None) -> Path:
    return Path(override or os.environ.get(BACKUP_ROOT_ENV) or str(DEFAULT_BACKUP_ROOT)).expanduser().resolve()


def list_backup_sets_payload(backup_root: str | Path | None = None) -> dict[str, object]:
    root = _backup_root(backup_root)
    try:
        if not root.exists():
            records: list[dict[str, object]] = []
        elif not root.is_dir():
            raise OSError(f"backup root is not a directory: {root}")
        else:
            from local_ai_cli.common import archive as archive
            records = []
            for path in root.iterdir():
                if not path.is_dir() or path.is_symlink() or not BACKUP_SET_RE.fullmatch(path.name):
                    continue
                metadata_path = path / "backup.json"
                checksums_path = path / "checksums.sha256"
                record: dict[str, object] = {"name": path.name, "path": str(path), "status": "invalid"}
                if metadata_path.is_file() and not metadata_path.is_symlink() and checksums_path.is_file() and not checksums_path.is_symlink():
                    try:
                        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                        if not isinstance(metadata, dict):
                            raise archive.ArchiveBackupError("backup metadata must be an object")
                        archive.validate_completed_metadata(metadata)
                        record.update({
                            "status": "completed",
                            "created_at": metadata["created_at"],
                            "source_commit": metadata["source_commit"],
                            "resolved_stacks": metadata["resolved_stacks"],
                        })
                    except (OSError, json.JSONDecodeError, archive.ArchiveBackupError, KeyError, TypeError):
                        pass
                records.append(record)
            records.sort(key=lambda item: str(item["name"]), reverse=True)
    except (OSError, ImportError) as exc:
        return {"schema_version": SCHEMA_VERSION, "command": "restore.list-backup-sets", "success": False, "error": {"code": "BACKUP_ROOT_INVALID", "message": str(exc)}}
    return {"schema_version": SCHEMA_VERSION, "command": "restore.list-backup-sets", "success": True, "backup_root": str(root), "backup_sets": records}


def plan_payload(backup_set: str | Path) -> dict[str, object]:
    return _operation("restore.plan", "RESTORE_PLAN_FAILED", lambda: _load("_restore_all").plan_restore_all(Path(backup_set)).as_dict())


def drill_payload(backup_set: str | Path, destination: str | Path) -> dict[str, object]:
    return _operation("restore.drill", "RESTORE_DRILL_FAILED", lambda: _load("_restore_drill").run_restore_drill(Path(backup_set), Path(destination)).as_dict())


def check_clean_target_payload(backup_set: str | Path) -> dict[str, object]:
    return _operation("restore.apply", "RESTORE_PREFLIGHT_FAILED", lambda: _load("_restore_live_service").check_clean(Path(backup_set)))


def apply_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path | None = None) -> dict[str, object]:
    def run():
        bootstrap = Path(memory_sync_ssh_bootstrap) if memory_sync_ssh_bootstrap else None
        return _load("_restore_live_service").execute(Path(backup_set), bootstrap)
    return _operation("restore.apply", "RESTORE_APPLY_FAILED", run)


def resume_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path) -> dict[str, object]:
    return _operation("restore.resume", "RESTORE_RESUME_FAILED", lambda: _load("_restore_resume").resume(Path(backup_set), Path(memory_sync_ssh_bootstrap)))


def cli_text(payload: dict[str, object]) -> str:
    if not payload.get("success"):
        error = payload.get("error")
        if isinstance(error, dict): return f"RECOVERY ERROR [{error.get('code','RECOVERY_FAILED')}]: {error.get('message','recovery operation failed')}"
        return "RECOVERY ERROR [RECOVERY_FAILED]: recovery operation failed"
    command = payload.get("command")
    if command == "restore.list-backup-sets":
        lines = [f"Backup root: {payload.get('backup_root', '-')}" ]
        records = payload.get("backup_sets")
        if not isinstance(records, list) or not records:
            return "\n".join(lines + ["No backup sets found."])
        lines += ["STATUS     BACKUP SET                   SOURCE COMMIT  STACKS", "---------- ---------------------------- ------------- ------"]
        for record in records:
            if not isinstance(record, dict):
                continue
            source = str(record.get("source_commit") or "-")[:12]
            stacks = ",".join(str(v) for v in record.get("resolved_stacks", [])) or "-"
            lines.append(f"{str(record.get('status','invalid')).upper():<10} {str(record.get('name','-')):<28} {source:<13} {stacks}")
        return "\n".join(lines + ["", "The PATH for a restore command is <backup-root>/<backup-set>."])
    result = payload.get("result")
    if not isinstance(result, dict): return str(result)
    if command == "restore.plan":
        lines=["RESTORE PLAN: PASS"]; order=result.get("restore_order")
        if isinstance(order,list) and order: lines.append("- restore order: "+", ".join(str(item) for item in order))
        if "changes_made" in result: lines.append(f"- changes made: {'yes' if result.get('changes_made') else 'no'}")
        return "\n".join(lines)
    if command == "restore.drill": return "\n".join(["RESTORE DRILL: PASS",f"- destination: {result.get('destination','-')}",f"- live runtime modified: {'yes' if result.get('live_runtime_modified') else 'no'}",f"- ports published: {'yes' if result.get('ports_published') else 'no'}",f"- platform network attached: {'yes' if result.get('platform_network_attached') else 'no'}"])
    if command == "restore.apply" and result.get("changes_made") is False: return "\n".join(["RESTORE ALL CLEAN-TARGET PREFLIGHT: PASS",f"- backup set: {result.get('backup_set','-')}",f"- source commit: {result.get('source_commit','-')}","- changes made: no"])
    if command == "restore.apply": return "\n".join(["RESTORE ALL CLEAN TARGET: PASS",f"- backup set: {result.get('backup_set','-')}",f"- source commit: {result.get('source_commit','-')}",f"- LiteLLM PostgreSQL tables restored: {result.get('postgres_tables','-')}",f"- Gitea repositories restored: {result.get('gitea_repositories','-')}"])
    if command == "restore.resume": return "\n".join(["RESTORE ALL RESUME: PASS",f"- source commit: {result.get('source_commit','-')}",f"- LiteLLM PostgreSQL tables: {result.get('postgres_tables','-')}",f"- Gitea repositories: {result.get('gitea_repositories','-')}",f"- memory-sync enabled: {'yes' if result.get('memory_sync_enabled') else 'no'}"])
    return str(result)


__all__ = ["SCHEMA_VERSION", "apply_payload", "check_clean_target_payload", "cli_text", "drill_payload", "list_backup_sets_payload", "plan_payload", "resume_payload"]
