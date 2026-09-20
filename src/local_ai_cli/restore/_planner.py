#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Restore-owned disaster-recovery primitives.

This module intentionally duplicates the DR surface consumed by restore while
command packages are being closed. It must not import another command package
implementation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from local_ai_cli.common import preflight

BACKUP_ROOT_ENV = preflight.BACKUP_ROOT_ENV
BACKUP_SET_NAME_PATTERN = preflight.BACKUP_SET_NAME_PATTERN
DEFAULT_BACKUP_ROOT = preflight.DEFAULT_BACKUP_ROOT
DestinationPreflight = preflight.DestinationPreflight
RecoveryError = preflight.RecoveryError
RuntimeCheck = preflight.RuntimeCheck
docker_state = preflight.docker_state
ensure_docker_preflight = preflight.ensure_docker_preflight
expand_runtime_path = preflight.expand_runtime_path
gitea_help_flags = preflight.gitea_help_flags
nearest_existing_parent = preflight.nearest_existing_parent
owned_container = preflight.owned_container
preflight_archive_source = preflight.preflight_archive_source
preflight_backup_destination = preflight.preflight_backup_destination
preflight_docker_service = preflight.preflight_docker_service
preflight_external_config_source = preflight.preflight_external_config_source
preflight_git_source = preflight.preflight_git_source
preflight_gitea_source = preflight.preflight_gitea_source
preflight_postgres_source = preflight.preflight_postgres_source
preflight_runtime_resource = preflight.preflight_runtime_resource
preflight_runtime_sources = preflight.preflight_runtime_sources
read_dotenv_presence = preflight.read_dotenv_presence
require_env_value = preflight.require_env_value
resolve_backup_root = preflight.resolve_backup_root
resolve_base_path = preflight.resolve_base_path
runtime_resources = preflight.runtime_resources

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"
BACKUP_SET_SCHEMA_VERSION = 1
ARTIFACT_EXTENSIONS = {"archive": ".tar", "postgres-custom-dump": ".dump", "gitea-native-dump": ".zip"}


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def run_manifest_tool(*args: str) -> object:
    try:
        cp = subprocess.run([sys.executable, str(MANIFEST_TOOL), *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
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
        raise RecoveryError("cannot determine Git HEAD for recovery provenance")
    head = cp.stdout.strip()
    if len(head) != 40:
        raise RecoveryError("unexpected Git HEAD format")
    return head


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
