# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only platform diagnostics exposed through ``./local-ai doctor``.

The doctor command checks management prerequisites and repository/runtime
contracts without mutating installation state. It deliberately reuses installer
registry validation instead of creating a second source of lifecycle truth.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from commands import install

SCHEMA_VERSION = "1"
ROOT = Path(__file__).resolve().parents[1]


def _check(check_id: str, status: str, message: str, **details: object) -> dict:
    return {
        "id": check_id,
        "status": status,
        "message": message,
        "details": details,
    }


def run_checks() -> list[dict]:
    """Return deterministic diagnostic records without changing platform state."""
    checks: list[dict] = []

    entry = ROOT / "local-ai"
    if entry.is_file():
        checks.append(_check("management_entrypoint", "pass", "root management entry point is present"))
    else:
        checks.append(_check("management_entrypoint", "fail", "root management entry point is missing"))

    try:
        manifests = install.all_manifests()
        lifecycle = install.load_lifecycle()
        install.validate_registry(manifests, lifecycle)
    except (install.InstallerError, OSError, subprocess.CalledProcessError) as exc:
        checks.append(_check("lifecycle_registry", "fail", "manifest/lifecycle registry validation failed", error=str(exc)))
    else:
        checks.append(
            _check(
                "lifecycle_registry",
                "pass",
                "manifest and lifecycle registries agree",
                stacks=len(manifests),
            )
        )

    env_path = ROOT / ".env"
    if not env_path.is_file():
        checks.append(_check("operational_env", "fail", "protected operational .env is missing"))
    else:
        mode = stat.S_IMODE(env_path.stat().st_mode)
        if mode != 0o600:
            checks.append(
                _check(
                    "operational_env",
                    "fail",
                    "protected operational .env must use mode 0600",
                    mode=f"{mode:04o}",
                )
            )
        else:
            checks.append(_check("operational_env", "pass", "protected operational .env is present with mode 0600"))

    docker = shutil.which("docker")
    if docker is None:
        checks.append(_check("docker_cli", "fail", "docker CLI is not available"))
        checks.append(_check("docker_compose", "fail", "docker compose cannot be checked without docker CLI"))
    else:
        checks.append(_check("docker_cli", "pass", "docker CLI is available", path=docker))
        cp = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if cp.returncode == 0:
            checks.append(_check("docker_compose", "pass", "docker compose is available"))
        else:
            checks.append(
                _check(
                    "docker_compose",
                    "fail",
                    "docker compose command failed",
                    returncode=cp.returncode,
                )
            )

    runtime_root = Path(os.environ.get("LOCAL_AI_RUNTIME_ROOT", "/opt/docker/runtime"))
    if runtime_root.exists() and runtime_root.is_dir():
        checks.append(_check("runtime_root", "pass", "runtime root exists", configured=True))
    else:
        checks.append(_check("runtime_root", "warn", "runtime root does not exist yet", configured=False))

    return checks


def payload(checks: list[dict]) -> dict:
    success = not any(item["status"] == "fail" for item in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "doctor",
        "success": success,
        "checks": checks,
    }


def main(*, json_output: bool = False) -> int:
    checks = run_checks()
    result = payload(checks)
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in checks:
            print(f"{item['status'].upper():4}  {item['id']}: {item['message']}")
        print("DOCTOR: PASS" if result["success"] else "DOCTOR: FAIL")
    return 0 if result["success"] else 1
