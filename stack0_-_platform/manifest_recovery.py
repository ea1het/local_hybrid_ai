# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Recovery-contract validation used by the Stack0 manifest registry."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NoReturn

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


def load_recovery_schema(root: Path) -> dict:
    schema_path = root / "commands" / "restore" / "recovery.schema.json"
    try:
        schema = json.loads(schema_path.read_text())
        contract = schema["$defs"]["contract"]
        resource = schema["$defs"]["resource"]
        restore = schema["$defs"]["restore"]
        result = {
            "path": schema_path,
            "version": contract["properties"]["schema_version"]["const"],
            "modes": set(contract["properties"]["mode"]["enum"]),
            "classes": set(resource["properties"]["class"]["enum"]),
            "strategies": set(resource["properties"]["strategy"]["enum"]),
            "restore_phases": set(restore["properties"]["phase"]["enum"]),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        _fail(f"cannot read valid recovery schema {schema_path}: {exc}")
    if result["version"] != 1:
        _fail(f"unsupported recovery schema version in {schema_path}: {result['version']}")
    return result


def _expect_keys(value: dict, allowed: set[str], context: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        _fail(f"{context}: unknown fields: {', '.join(sorted(unknown))}")


def _expect_bool(value: object, context: str) -> None:
    if not isinstance(value, bool):
        _fail(f"{context}: must be boolean")


def validate_recovery(data: dict, schema: dict, manifest_path: Path) -> None:
    recovery = data.get("recovery")
    if not isinstance(recovery, dict):
        _fail(f"{manifest_path}: recovery must be an object")
    _expect_keys(recovery, {"contract", "resources"}, f"{manifest_path}: recovery")
    contract = recovery.get("contract")
    if not isinstance(contract, dict):
        _fail(f"{manifest_path}: recovery.contract must be an object")
    _expect_keys(contract, {"schema_version", "mode"}, f"{manifest_path}: recovery.contract")
    if contract.get("schema_version") != schema["version"]:
        _fail(f"{manifest_path}: unsupported recovery contract schema_version")
    mode = contract.get("mode")
    if mode not in schema["modes"]:
        _fail(f"{manifest_path}: invalid recovery mode {mode!r}")
    resources = recovery.get("resources", [])
    if not isinstance(resources, list):
        _fail(f"{manifest_path}: recovery.resources must be a list")
    if mode == "managed" and not resources:
        _fail(f"{manifest_path}: managed recovery requires resources")
    seen: set[str] = set()
    for index, resource in enumerate(resources):
        context = f"{manifest_path}: recovery.resources[{index}]"
        if not isinstance(resource, dict):
            _fail(f"{context}: must be an object")
        _expect_keys(resource, {"id", "class", "strategy", "sensitive", "config"}, context)
        resource_id = resource.get("id")
        if not isinstance(resource_id, str) or not RESOURCE_ID_RE.fullmatch(resource_id):
            _fail(f"{context}: invalid resource id")
        if resource_id in seen:
            _fail(f"{manifest_path}: duplicate recovery resource id {resource_id}")
        seen.add(resource_id)
        resource_class = resource.get("class")
        strategy = resource.get("strategy")
        if resource_class not in schema["classes"]:
            _fail(f"{context}: invalid class {resource_class!r}")
        if strategy not in schema["strategies"]:
            _fail(f"{context}: invalid strategy {strategy!r}")
        _expect_bool(resource.get("sensitive"), f"{context}.sensitive")
        config = resource.get("config")
        if not isinstance(config, dict):
            _fail(f"{context}.config: must be an object")
        source = config.get("source")
        if not isinstance(source, dict):
            _fail(f"{context}.config.source: must be an object")
        source_type = source.get("type")
        expected_source = {
            "archive": "runtime-path",
            "file-copy": "runtime-path",
            "postgres-custom-dump": "postgres",
            "gitea-native-dump": "application",
            "external-config": "environment",
            "git": "git",
        }.get(strategy)
        if expected_source is not None and source_type != expected_source:
            _fail(f"{context}: strategy {strategy} requires source type {expected_source}")
        if mode == "reconstructable" and resource_class in {"persistent-data", "persistent-identity"}:
            _fail(f"{context}: reconstructable stack cannot own local persistent state")
        if "quiesce_container" in config:
            quiesce = config["quiesce_container"]
            if strategy != "archive" or not isinstance(quiesce, str) or not quiesce.strip():
                _fail(f"{context}: invalid quiesce_container")
        restore = config.get("restore")
        if restore is not None:
            if not isinstance(restore, dict):
                _fail(f"{context}.config.restore: must be an object")
            phase = restore.get("phase")
            if phase not in schema["restore_phases"]:
                _fail(f"{context}: invalid restore phase {phase!r}")
