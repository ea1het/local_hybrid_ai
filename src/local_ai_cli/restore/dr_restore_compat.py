#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compatibility helpers for recovering historical platform commits.

Some already-backed-up source revisions can return a non-zero installer result
immediately after a reconcile command restarts a health-checked service. The
installer message is specifically `required runtime validation failed`, while
the service is merely in Docker health `starting` and becomes healthy moments
later.

Recovery must not rewrite the historical source tree. This helper therefore
accepts only that exact transient failure class, waits for the target lifecycle's
required containers, and fails closed for every other installer error.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


class RestoreCompatibilityError(RuntimeError):
    pass


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _detail(cp: subprocess.CompletedProcess[bytes]) -> str:
    text = (cp.stderr or b"") + (cp.stdout or b"")
    return text.decode("utf-8", errors="replace").strip()


def _lifecycle_path(stacks_root: Path) -> Path:
    for candidate in (
        stacks_root / "commands" / "install-lifecycle.json",
        stacks_root / "installer" / "lifecycle.json",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise RestoreCompatibilityError("target source has no supported lifecycle registry")


def _load_lifecycle(stacks_root: Path) -> dict:
    path = _lifecycle_path(stacks_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreCompatibilityError(f"cannot read target lifecycle registry: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise RestoreCompatibilityError("unsupported target lifecycle registry")
    return data


def _installer_path(stacks_root: Path) -> Path:
    """Resolve current engine path while preserving historical recovery points."""
    for candidate in (
        stacks_root / "commands" / "install.py",
        stacks_root / "installer" / "install.py",
        stacks_root / "install.py",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise RestoreCompatibilityError("target source has no supported installer engine")


def _container_state(name: str) -> tuple[str, str]:
    cp = _run([
        "docker", "inspect", "-f",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
        name,
    ])
    if cp.returncode != 0:
        return "absent", ""
    text = cp.stdout.decode("utf-8", errors="replace").strip()
    status, _, health = text.partition("|")
    return status, health


def _required_containers(lifecycle: dict, selectors: list[int]) -> list[str]:
    required: list[str] = []
    seen: set[str] = set()
    for sid in selectors:
        entry = lifecycle.get(str(sid))
        if not isinstance(entry, dict):
            raise RestoreCompatibilityError(f"target lifecycle missing stack{sid}")
        names = entry.get("required_containers")
        if not isinstance(names, list) or not all(isinstance(value, str) and value for value in names):
            raise RestoreCompatibilityError(f"stack{sid}: invalid required_containers")
        for name in names:
            if name not in seen:
                required.append(name)
                seen.add(name)
    return required


def _runtime_ready(states: dict[str, tuple[str, str]]) -> bool:
    return all(
        status == "running" and health in {"", "healthy"}
        for status, health in states.values()
    )


def _terminal_states(states: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    terminal_statuses = {"absent", "dead", "exited", "removing"}
    return {
        name: state
        for name, state in states.items()
        if state[0] in terminal_statuses
    }


def _state_summary(states: dict[str, tuple[str, str]]) -> str:
    return ", ".join(
        f"{name}={status}/{health or 'none'}"
        for name, (status, health) in states.items()
    )


def wait_required_runtime(stacks_root: Path, selectors: list[int], timeout: int = 240) -> None:
    lifecycle = _load_lifecycle(stacks_root)["stacks"]
    required = _required_containers(lifecycle, selectors)
    deadline = time.monotonic() + timeout

    while True:
        states = {name: _container_state(name) for name in required}
        if _runtime_ready(states):
            return

        terminal = _terminal_states(states)
        if terminal:
            raise RestoreCompatibilityError(
                f"required runtime entered terminal state: {_state_summary(terminal)}"
            )
        if time.monotonic() >= deadline:
            raise RestoreCompatibilityError(
                f"required runtime readiness timeout: {_state_summary(states)}"
            )
        time.sleep(2)


def install_with_readiness_compat(
    stacks_root: Path,
    selectors: list[int],
    *,
    reconcile: bool = False,
    label: str,
) -> None:
    if not selectors:
        return
    installer = _installer_path(stacks_root)
    cmd = ["python3", str(installer.relative_to(stacks_root)), *[str(sid) for sid in selectors]]
    if reconcile:
        cmd.append("--reconcile")
    cmd.append("--yes")
    cp = _run(cmd, cwd=stacks_root)
    if cp.returncode == 0:
        return

    detail = _detail(cp)
    if "required runtime validation failed" not in detail:
        if len(detail) > 2000:
            detail = "..." + detail[-2000:]
        raise RestoreCompatibilityError(f"{label} failed: {detail or 'no diagnostic output'}")

    wait_required_runtime(stacks_root, selectors)
