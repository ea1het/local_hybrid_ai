#!/usr/bin/env python3
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
    schema_path = root / "src" / "local_ai_cli" / "restore" / "recovery.schema.json"
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


def _exact_keys(value: dict, required: set[str], optional: set[str], where: str) -> None:
    missing = required - set(value)
    unexpected = set(value) - required - optional
    if missing:
        _fail(f"{where}: missing required fields: {', '.join(sorted(missing))}")
    if unexpected:
        _fail(f"{where}: unsupported fields: {', '.join(sorted(unexpected))}")


def _non_empty(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{where} must be a non-empty string")
    return value


def _validate_restore(restore: object, schema: dict, where: str) -> None:
    if not isinstance(restore, dict):
        _fail(f"{where} must be an object")
    _exact_keys(restore, {"phase"}, set(), where)
    if restore["phase"] not in schema["restore_phases"]:
        _fail(f"{where}.phase has unsupported value: {restore['phase']}")


STRATEGY_CONTRACTS = {
    "archive": ("runtime-path", {"type", "path"}, set(), {"quiesce_container"}, True),
    "postgres-custom-dump": ("postgres", {"type", "service", "database_env"}, {"user_env"}, set(), True),
    "gitea-native-dump": ("application", {"type", "service"}, set(), set(), True),
    "external-config": ("environment", {"type", "key"}, set(), set(), False),
    "git": ("git", {"type"}, {"repository_env"}, set(), False),
}


def _validate_resource(resource: object, schema: dict, where: str) -> None:
    if not isinstance(resource, dict):
        _fail(f"{where} must be an object")
    _exact_keys(resource, {"id", "class", "strategy", "sensitive"}, {"config"}, where)
    resource_id = _non_empty(resource["id"], f"{where}.id")
    if not RESOURCE_ID_RE.fullmatch(resource_id):
        _fail(f"{where}.id has invalid format: {resource_id}")
    if resource["class"] not in schema["classes"]:
        _fail(f"{where}.class has unsupported value: {resource['class']}")
    strategy = resource["strategy"]
    if strategy not in schema["strategies"]:
        _fail(f"{where}.strategy has unsupported value: {strategy}")
    if not isinstance(resource["sensitive"], bool):
        _fail(f"{where}.sensitive must be boolean")
    if not isinstance(resource.get("config"), dict):
        _fail(f"{where}.config must be an object for strategy {strategy}")
    contract = STRATEGY_CONTRACTS.get(strategy)
    if contract is None:
        _fail(f"{where}.strategy is declared by schema but unsupported by validator: {strategy}")
    source_type, source_required, source_optional, config_optional, restore_required = contract
    config = resource["config"]
    required_config = {"source", "restore"} if restore_required else {"source"}
    _exact_keys(config, required_config, config_optional, f"{where}.config")
    source = config["source"]
    if not isinstance(source, dict):
        _fail(f"{where}.config.source must be an object")
    _exact_keys(source, source_required, source_optional, f"{where}.config.source")
    if source["type"] != source_type:
        _fail(f"{where}.config.source.type must be {source_type} for strategy {strategy}")
    for key, value in source.items():
        if key != "type":
            _non_empty(value, f"{where}.config.source.{key}")
    if "quiesce_container" in config:
        _non_empty(config["quiesce_container"], f"{where}.config.quiesce_container")
    if restore_required:
        _validate_restore(config["restore"], schema, f"{where}.config.restore")


def validate_recovery(data: dict, schema: dict, manifest_path: Path) -> None:
    recovery = data.get("recovery")
    where = f"{manifest_path}: recovery"
    if not isinstance(recovery, dict):
        _fail(f"{manifest_path}: recovery must be an object")
    _exact_keys(recovery, {"contract"}, {"resources"}, where)
    contract = recovery["contract"]
    if not isinstance(contract, dict):
        _fail(f"{manifest_path}: recovery.contract must be an object")
    _exact_keys(contract, {"schema_version", "mode"}, set(), f"{manifest_path}: recovery.contract")
    if contract["schema_version"] != schema["version"]:
        _fail(f"{manifest_path}: recovery.contract.schema_version must be {schema['version']}")
    mode = contract["mode"]
    if mode not in schema["modes"]:
        _fail(f"{manifest_path}: unsupported recovery mode: {mode}")
    resources = recovery.get("resources")
    if resources is not None:
        if not isinstance(resources, list) or not resources:
            _fail(f"{manifest_path}: recovery.resources must be a non-empty list when present")
        seen: set[str] = set()
        for index, resource in enumerate(resources):
            resource_where = f"{manifest_path}: recovery.resources[{index}]"
            _validate_resource(resource, schema, resource_where)
            if resource["id"] in seen:
                _fail(f"{manifest_path}: duplicate recovery resource id: {resource['id']}")
            seen.add(resource["id"])
    if mode in {"managed", "mixed"} and resources is None:
        _fail(f"{manifest_path}: recovery mode {mode} requires resources")
    if mode == "reconstructable" and resources is not None:
        for resource in resources:
            if resource["class"] != "externalized":
                _fail(f"{manifest_path}: reconstructable stacks may only declare externalized recovery resources")
