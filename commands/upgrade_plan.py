# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Persistence helpers for explicit upgrade selections."""

from __future__ import annotations

import json
import os
from pathlib import Path

SCHEMA_VERSION = 1


class PlanError(RuntimeError):
    """Raised when persisted upgrade-plan state is invalid or unreadable."""


def path(runtime_root: Path) -> Path:
    return runtime_root / "platform" / "upgrade-plan.json"


def load(plan_path: Path) -> dict:
    if not plan_path.is_file():
        return {"schema_version": SCHEMA_VERSION, "selected": {}}
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read upgrade plan: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("selected"), dict):
        raise PlanError("unsupported upgrade plan schema")
    return data


def save(plan_path: Path, plan: dict) -> None:
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = plan_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, plan_path)
