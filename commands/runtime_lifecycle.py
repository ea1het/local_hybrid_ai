# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Selective non-destructive runtime start/stop for one prepared stack.

The module interprets stack manifests and the lifecycle registry to preserve
ownership and dependency rules around ``docker compose start``/``stop``. It
never performs ``down``, removal, recreation or implicit dependency startup.
Stopping a required provider fails closed while consumers are active; starting
a consumer fails closed when required runtime providers are unavailable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from commands import install

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1"


class RuntimeLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RuntimeResult:
    action: str
    stack_id: int
    directory: str
    containers: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "command": f"runtime.{self.action}",
            "success": True,
            "stack": f"stack{self.stack_id}",
            "directory": self.directory,
            "containers": list(self.containers),
        }


def _required_containers(sid: int, lifecycle: dict) -> tuple[str, ...]:
    entry = lifecycle["stacks"][str(sid)]
    return tuple(entry["required_containers"])


def _owned_containers(manifest: dict) -> tuple[str, ...]:
    return tuple(
        value.split(":", 1)[1]
        for value in manifest.get("owns", [])
        if isinstance(value, str) and value.startswith("container:")
    )


def _runtime_running(sid: int, lifecycle: dict) -> bool:
    required = _required_containers(sid, lifecycle)
    return bool(required) and all(install.is_running(install.container_state(name)) for name in required)


def _required_provider_ids(manifest: dict) -> set[int]:
    return {int(value) for value in manifest.get("requires", [])}


def _required_consumers(
    provider_sid: int,
    manifests: dict[int, dict],
    lifecycle: dict,
) -> list[int]:
    provider_caps = set(manifests[provider_sid].get("provides", []))
    consumers: list[int] = []
    for sid, manifest in manifests.items():
        if sid == provider_sid or not _runtime_running(sid, lifecycle):
            continue
        depends_by_id = provider_sid in _required_provider_ids(manifest)
        consumes_capability = bool(provider_caps & set(manifest.get("consumes", [])))
        if depends_by_id or consumes_capability:
            consumers.append(sid)
    return sorted(consumers)


def _missing_required_providers(
    sid: int,
    manifests: dict[int, dict],
    lifecycle: dict,
) -> list[int]:
    missing: list[int] = []
    for provider_sid in sorted(_required_provider_ids(manifests[sid])):
        required = _required_containers(provider_sid, lifecycle)
        if required and not _runtime_running(provider_sid, lifecycle):
            missing.append(provider_sid)
    return missing


def _resolve_one(selector: str, manifests: dict[int, dict]) -> int:
    try:
        values = install.resolve_requested([selector], manifests)
    except install.InstallerError as exc:
        raise RuntimeLifecycleError("STACK_UNKNOWN", str(exc)) from exc
    if len(values) != 1:
        raise RuntimeLifecycleError("STACK_SELECTOR_INVALID", "exactly one stack selector is required")
    return values[0]


def _preflight() -> tuple[dict[int, dict], dict]:
    if os.geteuid() != 0:
        raise RuntimeLifecycleError("RUNTIME_ROOT_REQUIRED", "stack start/stop requires root")
    manifests = install.all_manifests()
    lifecycle = install.load_lifecycle()
    install.validate_registry(manifests, lifecycle)
    try:
        install.run(["docker", "compose", "version"], capture=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeLifecycleError("DOCKER_UNAVAILABLE", "docker compose is unavailable") from exc
    return manifests, lifecycle


def execute(action: str, selector: str) -> RuntimeResult:
    if action not in {"start", "stop"}:
        raise RuntimeLifecycleError("RUNTIME_ACTION_INVALID", f"unsupported runtime action: {action}")

    manifests, lifecycle = _preflight()
    sid = _resolve_one(selector, manifests)
    manifest = manifests[sid]
    required = _required_containers(sid, lifecycle)
    owned = _owned_containers(manifest)
    if not required:
        raise RuntimeLifecycleError(
            "STACK_RUNTIME_EMPTY",
            f"stack{sid} has no managed runtime containers to {action}",
        )

    directory = manifest["directory"]
    cwd = ROOT / directory
    if not install.stack_prepared(directory):
        raise RuntimeLifecycleError("STACK_NOT_PREPARED", f"stack{sid} is not PREPARED")

    if action == "stop":
        consumers = _required_consumers(sid, manifests, lifecycle)
        if consumers:
            joined = ", ".join(f"stack{value}" for value in consumers)
            raise RuntimeLifecycleError(
                "STACK_HAS_ACTIVE_CONSUMERS",
                f"cannot stop stack{sid}; required consumers are running: {joined}",
            )
    else:
        missing = _missing_required_providers(sid, manifests, lifecycle)
        if missing:
            joined = ", ".join(f"stack{value}" for value in missing)
            raise RuntimeLifecycleError(
                "STACK_DEPENDENCY_NOT_RUNNING",
                f"cannot start stack{sid}; required providers are not running: {joined}",
            )

    cp = install.run(["docker", "compose", action], cwd=cwd, capture=True, check=False)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise RuntimeLifecycleError(
            "STACK_RUNTIME_COMMAND_FAILED",
            f"stack{sid} docker compose {action} failed: {detail or 'no diagnostic output'}",
        )

    if action == "start":
        try:
            install.wait_required_runtime(sid, lifecycle["stacks"][str(sid)])
        except install.InstallerError as exc:
            raise RuntimeLifecycleError("STACK_START_NOT_READY", str(exc)) from exc

    return RuntimeResult(action, sid, directory, owned)


def main(action: str, selector: str, *, json_output: bool = False) -> int:
    try:
        result = execute(action, selector)
    except (RuntimeLifecycleError, install.InstallerError) as exc:
        code = exc.code if isinstance(exc, RuntimeLifecycleError) else "RUNTIME_INTERNAL_ERROR"
        message = exc.message if isinstance(exc, RuntimeLifecycleError) else str(exc)
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": f"runtime.{action}",
                "success": False,
                "error": {"code": code, "message": message},
            }, indent=2))
        else:
            print(f"ERROR [{code}]: {message}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(f"stack{result.stack_id}: {action.upper()} PASS")
        print(f"- directory: {result.directory}")
        print(f"- containers: {', '.join(result.containers)}")
    return 0
