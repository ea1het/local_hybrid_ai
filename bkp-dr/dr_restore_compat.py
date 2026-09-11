#!/usr/bin/env python3
"""Compatibility helpers for recovering historical platform commits.

Some already-backed-up source revisions can return a non-zero installer result
immediately after a reconcile command restarts a health-checked service.  The
installer message is specifically `required runtime validation failed`, while
the service is merely in Docker health `starting` and becomes healthy moments
later.

Recovery must not rewrite the historical source tree.  This helper therefore
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


def _load_lifecycle(stacks_root: Path) -> dict:
    path = stacks_root / "installer" / "lifecycle.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreCompatibilityError(f"cannot read target lifecycle registry: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("stacks"), dict):
        raise RestoreCompatibilityError("unsupported target lifecycle registry")
    return data


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


def wait_required_runtime(stacks_root: Path, selectors: list[int], timeout: int = 240) -> None:
    lifecycle = _load_lifecycle(stacks_root)["stacks"]
    required: list[str] = []
    seen: set[str] = set()
    for sid in selectors:
        entry = lifecycle.get(str(sid))
        if not isinstance(entry, dict):
            raise RestoreCompatibilityError(f"target lifecycle missing stack{sid}")
        names = entry.get("required_containers")
        if not isinstance(names, list) or not all(isinstance(v, str) and v for v in names):
            raise RestoreCompatibilityError(f"stack{sid}: invalid required_containers")
        for name in names:
            if name not in seen:
                required.append(name)
                seen.add(name)

    deadline = time.monotonic() + timeout
    while True:
        states = {name: _container_state(name) for name in required}
        ready = all(
            status == "running" and health in {"", "healthy"}
            for status, health in states.values()
        )
        if ready:
            return
        terminal = {
            name: (status, health)
            for name, (status, health) in states.items()
            if status in {"absent", "dead", "exited", "removing"}
        }
        if terminal:
            summary = ", ".join(f"{n}={s}/{h or 'none'}" for n, (s, h) in terminal.items())
            raise RestoreCompatibilityError(f"required runtime entered terminal state: {summary}")
        if time.monotonic() >= deadline:
            summary = ", ".join(f"{n}={s}/{h or 'none'}" for n, (s, h) in states.items())
            raise RestoreCompatibilityError(f"required runtime readiness timeout: {summary}")
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
    cmd = ["python3", "install.py", *[str(sid) for sid in selectors]]
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

    # Historical installer compatibility: only this exact failure class may be
    # converted into success, and only after every required target container is
    # independently observed running/healthy.
    wait_required_runtime(stacks_root, selectors)
