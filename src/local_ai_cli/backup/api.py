# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Public Backup API backed exclusively by package-owned implementation."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
SCHEMA_VERSION = "1"


def _load(name: str):
    root = str(PACKAGE_ROOT)
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


def _envelope(result: dict[str, object]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": "backup", "success": True, "result": result}


def _failure(exc: Exception) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "command": "backup", "success": False, "error": {"code": "BACKUP_FAILED", "message": str(exc)}}


def backup_payload(destination: str | Path | None = None) -> dict[str, object]:
    try:
        dr = _load("dr")
        dr.MANIFEST_TOOL = PROJECT_ROOT / "stack0_-_platform" / "manifests.py"
        backup = _load("dr_backup_all")
        backup.ENV_SOURCE = PROJECT_ROOT / ".env"
        root, _ = dr.resolve_backup_root(str(destination) if destination is not None else None)
        return _envelope(backup.execute_backup_all(root).as_dict())
    except Exception as exc:
        return _failure(exc)


def cli_text(payload: dict[str, object]) -> str:
    if not payload.get("success"):
        error = payload.get("error")
        if isinstance(error, dict):
            return f"RECOVERY ERROR [{error.get('code','BACKUP_FAILED')}]: {error.get('message','backup operation failed')}"
        return "RECOVERY ERROR [BACKUP_FAILED]: backup operation failed"
    result = payload.get("result")
    if not isinstance(result, dict):
        return str(result)
    path = result.get("backup_set", result.get("path", "-"))
    return "\n".join(["DR BACKUP: PASS", f"- backup set: {path}", f"- artifacts: {result.get('artifact_count','-')}", "- publication: atomic"])


__all__ = ["SCHEMA_VERSION", "backup_payload", "cli_text"]
