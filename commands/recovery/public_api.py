# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Structured recovery operations consumed by the public management CLI."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

RECOVERY_ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1"


def _load(name: str):
    root = str(RECOVERY_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(name)
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


def _load_script(filename: str):
    """Load a legacy hyphenated recovery entrypoint without executing main()."""
    root = str(RECOVERY_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        path = RECOVERY_ROOT / filename
        module_name = "_local_ai_recovery_" + filename.replace("-", "_").removesuffix(".py")
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load recovery module: {filename}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


def _envelope(command: str, result: dict[str, object]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": command, "success": True, "result": result}


def plan_payload(backup_set: str | Path) -> dict[str, object]:
    engine = _load("dr_restore_all")
    return _envelope("restore.plan", engine.plan_restore_all(Path(backup_set)).as_dict())


def drill_payload(backup_set: str | Path, destination: str | Path) -> dict[str, object]:
    engine = _load("dr_restore_drill")
    return _envelope("restore.drill", engine.run_restore_drill(Path(backup_set), Path(destination)).as_dict())


def check_clean_target_payload(backup_set: str | Path) -> dict[str, object]:
    entry = _load_script("restore-live.py")
    return _envelope("restore.apply", entry.check_clean(Path(backup_set)))


def apply_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path | None = None) -> dict[str, object]:
    entry = _load_script("restore-live.py")
    bootstrap = Path(memory_sync_ssh_bootstrap) if memory_sync_ssh_bootstrap else None
    return _envelope("restore.apply", entry._execute_with_optional_bootstrap(Path(backup_set), bootstrap))


def resume_payload(backup_set: str | Path, memory_sync_ssh_bootstrap: str | Path) -> dict[str, object]:
    entry = _load_script("restore-resume.py")
    return _envelope("restore.resume", entry.resume(Path(backup_set), Path(memory_sync_ssh_bootstrap)))


def cli_text(payload: dict[str, object]) -> str:
    """Return human-readable text without writing to stdout or stderr."""
    command = payload.get("command")
    result = payload.get("result")
    if not isinstance(result, dict):
        return str(result)
    if command == "restore.plan":
        lines = ["RESTORE PLAN: PASS"]
        order = result.get("restore_order")
        if isinstance(order, list) and order:
            lines.append("- restore order: " + ", ".join(str(item) for item in order))
        if "changes_made" in result:
            lines.append(f"- changes made: {'yes' if result.get('changes_made') else 'no'}")
        return "\n".join(lines)
    if command == "restore.drill":
        return "\n".join([
            "RESTORE DRILL: PASS",
            f"- destination: {result.get('destination', '-')}",
            f"- live runtime modified: {'yes' if result.get('live_runtime_modified') else 'no'}",
            f"- ports published: {'yes' if result.get('ports_published') else 'no'}",
            f"- platform network attached: {'yes' if result.get('platform_network_attached') else 'no'}",
        ])
    if command == "restore.apply" and result.get("changes_made") is False:
        return "\n".join([
            "RESTORE ALL CLEAN-TARGET PREFLIGHT: PASS",
            f"- backup set: {result.get('backup_set', '-')}",
            f"- source commit: {result.get('source_commit', '-')}",
            "- changes made: no",
        ])
    if command == "restore.apply":
        return "\n".join([
            "RESTORE ALL CLEAN TARGET: PASS",
            f"- backup set: {result.get('backup_set', '-')}",
            f"- source commit: {result.get('source_commit', '-')}",
            f"- LiteLLM PostgreSQL tables restored: {result.get('postgres_tables', '-')}",
            f"- Gitea repositories restored: {result.get('gitea_repositories', '-')}",
        ])
    if command == "restore.resume":
        return "\n".join([
            "RESTORE ALL RESUME: PASS",
            f"- source commit: {result.get('source_commit', '-')}",
            f"- LiteLLM PostgreSQL tables: {result.get('postgres_tables', '-')}",
            f"- Gitea repositories: {result.get('gitea_repositories', '-')}",
            f"- memory-sync enabled: {'yes' if result.get('memory_sync_enabled') else 'no'}",
        ])
    return str(result)
