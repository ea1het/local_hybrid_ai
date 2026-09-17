# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Structured recovery operations consumed by the public management CLI."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable

RECOVERY_ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1"


def _load(name: str):
    root = str(RECOVERY_ROOT); added = root not in sys.path
    if added: sys.path.insert(0, root)
    try: return importlib.import_module(name)
    finally:
        if added:
            try: sys.path.remove(root)
            except ValueError: pass


def _envelope(command: str, result: dict[str, object]) -> dict[str, object]: return {"schema_version": SCHEMA_VERSION, "command": command, "success": True, "result": result}
def _failure(command: str, code: str, exc: Exception) -> dict[str, object]: return {"schema_version": SCHEMA_VERSION, "command": command, "success": False, "error": {"code": code, "message": str(exc)}}
def _operation(command: str, code: str, callback: Callable[[], dict[str, object]]) -> dict[str, object]:
    try: return _envelope(command, callback())
    except Exception as exc: return _failure(command, code, exc)


def plan_payload(backup_set: str | Path) -> dict[str, object]:
    def run(): return _load("dr_restore_all").plan_restore_all(Path(backup_set)).as_dict()
    return _operation("restore.plan", "RESTORE_PLAN_FAILED", run)

def drill_payload(backup_set: str | Path, destination: str | Path) -> dict[str, object]:
    def run(): return _load("dr_restore_drill").run_restore_drill(Path(backup_set), Path(destination)).as_dict()
    return _operation("restore.drill", "RESTORE_DRILL_FAILED", run)

def check_clean_target_payload(backup_set: str | Path) -> dict[str, object]:
    def run(): return _load("dr_restore_live_service").check_clean(Path(backup_set))
    return _operation("restore.apply", "RESTORE_PREFLIGHT_FAILED", run)

def apply_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path | None = None) -> dict[str, object]:
    def run():
        bootstrap=Path(memory_sync_ssh_bootstrap) if memory_sync_ssh_bootstrap else None
        return _load("dr_restore_live_service").execute(Path(backup_set),bootstrap)
    return _operation("restore.apply", "RESTORE_APPLY_FAILED", run)

def resume_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path) -> dict[str, object]:
    def run(): return _load("dr_restore_resume").resume(Path(backup_set),Path(memory_sync_ssh_bootstrap))
    return _operation("restore.resume", "RESTORE_RESUME_FAILED", run)


def cli_text(payload: dict[str, object]) -> str:
    if not payload.get("success"):
        error=payload.get("error")
        if isinstance(error,dict): return f"RESTORE ERROR [{error.get('code','RESTORE_FAILED')}]: {error.get('message','recovery operation failed')}"
        return "RESTORE ERROR [RESTORE_FAILED]: recovery operation failed"
    command=payload.get("command"); result=payload.get("result")
    if not isinstance(result,dict): return str(result)
    if command=="restore.plan":
        lines=["RESTORE PLAN: PASS"]; order=result.get("restore_order")
        if isinstance(order,list) and order: lines.append("- restore order: "+", ".join(str(item) for item in order))
        if "changes_made" in result: lines.append(f"- changes made: {'yes' if result.get('changes_made') else 'no'}")
        return "\n".join(lines)
    if command=="restore.drill": return "\n".join(["RESTORE DRILL: PASS",f"- destination: {result.get('destination','-')}",f"- live runtime modified: {'yes' if result.get('live_runtime_modified') else 'no'}",f"- ports published: {'yes' if result.get('ports_published') else 'no'}",f"- platform network attached: {'yes' if result.get('platform_network_attached') else 'no'}"])
    if command=="restore.apply" and result.get("changes_made") is False: return "\n".join(["RESTORE ALL CLEAN-TARGET PREFLIGHT: PASS",f"- backup set: {result.get('backup_set','-')}",f"- source commit: {result.get('source_commit','-')}","- changes made: no"])
    if command=="restore.apply": return "\n".join(["RESTORE ALL CLEAN TARGET: PASS",f"- backup set: {result.get('backup_set','-')}",f"- source commit: {result.get('source_commit','-')}",f"- LiteLLM PostgreSQL tables restored: {result.get('postgres_tables','-')}",f"- Gitea repositories restored: {result.get('gitea_repositories','-')}"])
    if command=="restore.resume": return "\n".join(["RESTORE ALL RESUME: PASS",f"- source commit: {result.get('source_commit','-')}",f"- LiteLLM PostgreSQL tables: {result.get('postgres_tables','-')}",f"- Gitea repositories: {result.get('gitea_repositories','-')}",f"- memory-sync enabled: {'yes' if result.get('memory_sync_enabled') else 'no'}"])
    return str(result)
