# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Report preparation and Docker health without changing stack state.

Wrappers call this module for their status verb. It reads each preparation
lock, inspects Docker containers belonging to the stack's Compose working
directory, and separates container state from health. Optional services are shown when present but
do not make an inactive profile look broken. Deep mode adds an authenticated,
read-only ``SELECT 1`` inside the PostgreSQL containers owned by Stacks 20
and 30. No environment values or database credentials are printed, and no
waiting, deployment, repair, or network mutation is performed on import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REQUIRED_SERVICES = {
    "10": ("haproxy", "web"),
    "20": ("searxng", "searxng-mcp", "firecrawl-mcp", "firecrawl-api",
           "firecrawl-playwright", "firecrawl-redis", "firecrawl-rabbitmq", "firecrawl-postgres"),
    "30": ("litellm-postgres", "litellm"),
    "40": ("gitea", "gitea-runner"),
    "50": ("dockhand",),
    "60": ("hermes", "hermes-sandbox", "hermes-sandbox-cleanup"),
    "70": ("open-webui",),
}
OPTIONAL_SERVICES = {"60": ("hermes-memory-sync",)}
ANCHOR_CONTAINERS = {
    "10": "haproxy",
    "20": "firecrawl-postgres",
    "30": "litellm-postgres",
    "40": "gitea-runner",
    "50": "dockhand",
    "60": "hermes-sandbox",
    "70": "open-webui",
}
DATABASE_PROBES = {
    "20": (
        "firecrawl-postgres",
        'PGPASSWORD="$FIRECRAWL_DB_PASSWORD" psql -h 127.0.0.1 '
        '-U "$FIRECRAWL_DB_USER" -d "$FIRECRAWL_DB_NAME" -Atqc "SELECT 1"',
    ),
    "30": (
        "litellm-postgres",
        'PGPASSWORD="$POSTGRES_PASSWORD" psql '
        '-h 127.0.0.1 -U postgres -d postgres -Atqc "SELECT 1"',
    ),
}


def preparation_state(lock_file: Path) -> str:
    """Distinguish a missing lock from a regular or suspicious lock path."""
    if lock_file.is_symlink() or (lock_file.exists() and not lock_file.is_file()):
        return "INVALID"
    return "PREPARED" if lock_file.is_file() else "UNPREPARED"


def container_rows(stack_dir: Path) -> dict[str, dict[str, object]]:
    """Inspect the stack's containers without requiring local Compose inputs."""
    command = ["docker", "ps", "--all", "--quiet", "--no-trunc", "--filter",
               "label=com.docker.compose.service"]
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeError(f"Docker ps failed (exit {result.returncode})")
    rows = {}
    container_ids = result.stdout.split()
    if not container_ids:
        return rows
    result = subprocess.run(["docker", "inspect", "--type", "container", *container_ids],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=15, check=False)
    if result.returncode:
        raise RuntimeError(f"Docker inspect failed (exit {result.returncode})")
    containers = json.loads(result.stdout)
    if not isinstance(containers, list):
        raise ValueError("invalid Docker inspect response")
    prefix, separator, suffix = stack_dir.name.partition("_-_")
    working_dirs = {stack_dir}
    if separator and prefix.startswith("stack-") and prefix[6:].isdigit():
        working_dirs.add(stack_dir.with_name(f"stack{int(prefix[6:]) // 10}_-_{suffix}"))
    stack_number = prefix.removeprefix("stack-")
    selected = []
    for container in containers:
        if not isinstance(container, dict):
            raise ValueError("invalid Docker inspect container")
        labels = (container.get("Config") or {}).get("Labels") or {}
        if Path(labels.get("com.docker.compose.project.working_dir", "")) in working_dirs:
            selected.append(container)
    if not selected:
        anchor_name = ANCHOR_CONTAINERS.get(stack_number)
        anchor = next((container for container in containers
                       if container.get("Name") == f"/{anchor_name}"
                       and (container.get("Config") or {}).get("Labels", {}).get(
                           "com.docker.compose.service") in REQUIRED_SERVICES.get(stack_number, ())), None)
        if anchor is not None:
            project = anchor["Config"]["Labels"].get("com.docker.compose.project")
            if project:
                selected = [container for container in containers
                            if (container.get("Config") or {}).get("Labels", {}).get(
                                "com.docker.compose.project") == project]
    for container in selected:
        labels = (container.get("Config") or {}).get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        state = container.get("State") or {}
        if not isinstance(service, str) or not isinstance(state, dict):
            raise ValueError("invalid Docker Compose container metadata")
        if service in rows:
            raise ValueError(f"duplicate Docker Compose service: {service}")
        rows[service] = {
            "State": state.get("Status", "unknown"),
            "Health": (state.get("Health") or {}).get("Status", "none"),
            "ExitCode": state.get("ExitCode"),
        }
    return rows


def database_probe(number: str) -> bool:
    """Execute one authenticated read-only query without exposing passwords."""
    container, query = DATABASE_PROBES[number]
    result = subprocess.run(["docker", "exec", container, "sh", "-c", query],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=10, check=False)
    return result.returncode == 0 and result.stdout.strip() == "1"


def report_status(number: str, stack_dir: Path, lock_file: Path, *, deep: bool = False) -> int:
    """Print a non-mutating summary and return zero only for prepared, healthy stacks."""
    prepared = preparation_state(lock_file)
    print(f"Stack {number}: preparation={prepared}")
    try:
        rows = container_rows(stack_dir)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"runtime=UNKNOWN ({error})")
        return 2

    states = []
    failed_exit = False
    for service in (*REQUIRED_SERVICES[number], *OPTIONAL_SERVICES.get(number, ())):
        item = rows.get(service)
        if item is None:
            if service in OPTIONAL_SERVICES.get(number, ()):
                print(f"  {service}: inactive optional profile")
                continue
            state, health = "absent", "none"
        else:
            state = str(item.get("State") or "unknown")
            health = str(item.get("Health") or "none")
            failed_exit |= state == "exited" and item.get("ExitCode") not in (None, 0)
        print(f"  {service}: {state} / {health}")
        states.append((state, health))

    if failed_exit:
        runtime = "DEGRADED"
    elif all(state in {"absent", "exited", "created"} for state, _ in states):
        runtime = "STOPPED"
    elif any(state != "running" for state, _ in states):
        runtime = "PARTIAL"
    elif any(health == "unhealthy" for _, health in states):
        runtime = "DEGRADED"
    elif all(health == "healthy" for _, health in states):
        runtime = "READY"
    else:
        runtime = "RUNNING (health pending or unavailable)"

    deep_ok = True
    if deep and number in DATABASE_PROBES:
        database_service = DATABASE_PROBES[number][0]
        if rows.get(database_service, {}).get("State") != "running":
            deep_ok = False
        else:
            try:
                deep_ok = database_probe(number)
            except (OSError, subprocess.TimeoutExpired):
                deep_ok = False
        print(f"  PostgreSQL SELECT 1: {'OK' if deep_ok else 'FAILED'}")

    print(f"runtime={runtime}")
    if deep and number not in DATABASE_PROBES:
        print("deep=No additional read-only probe is defined for this stack")
    overall_ready = prepared == "PREPARED" and runtime == "READY" and deep_ok
    print(f"overall={'READY' if overall_ready else 'NOT READY'}")
    return 0 if overall_ready else 1


def report_platform_status(stack_dir: Path, lock_file: Path, *, deep: bool = False) -> int:
    """Report Stack 00 lock state and optionally run its read-only verifier."""
    prepared = preparation_state(lock_file)
    print(f"Stack 00: preparation={prepared}; runtime=no containers")
    if not deep:
        print("platform=NOT VERIFIED (use status --deep)")
        return 0 if prepared == "PREPARED" else 1
    if os.geteuid() != 0:
        print("platform=UNKNOWN (deep verification requires root)")
        return 2
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(stack_dir.parent), environment.get("PYTHONPATH", "")) if part
    )
    try:
        result = subprocess.run([sys.executable, "-B", "-m", "stack-00_-_platform.verify"],
                                cwd=stack_dir, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"platform=UNKNOWN ({error})")
        return 2
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    print(f"platform={'VERIFIED' if result.returncode == 0 else 'FAILED'}")
    return 0 if prepared == "PREPARED" and result.returncode == 0 else 1
