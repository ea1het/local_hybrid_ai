# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Guarded executor for explicitly selected component upgrades.

Execution is intentionally recovery-first and fail-closed. Before mutating the
protected operational environment, the executor revalidates policy, immutable
registry identity and target availability for every selection, then creates a
recovery point when required. Deployment is targeted to selected components,
followed by READY, RECONCILE, VERIFY and dependent-consumer re-verification.
Successful selections are cleared only after the runtime proves the target.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from commands import upgrade_policy, upgrade_registry


class UpgradeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, recovery_point: str | None = None):
        super().__init__(message)
        self.code = code
        self.recovery_point = recovery_point


def _run(cmd: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise UpgradeExecutionError(
            "UPGRADE_COMMAND_FAILED",
            f"command failed (rc={cp.returncode}): {' '.join(cmd)}" + (f": {detail}" if detail else ""),
        )
    return cp


def _container_state(root: Path, name: str) -> str:
    cp = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", name],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        return "absent"
    status, _, health = cp.stdout.strip().partition("|")
    return f"{status}/{health}" if health else (status or "unknown")


def _running_image(root: Path, container: str) -> str | None:
    cp = subprocess.run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", container],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


def _version_from_image(image: str | None) -> str:
    if not image:
        return "n/a"
    if "@sha256:" in image:
        base, digest = image.split("@sha256:", 1)
        tag = base.rsplit(":", 1)[1] if ":" in base.rsplit("/", 1)[-1] else None
        return f"{tag}@{digest[:12]}" if tag else f"sha256:{digest[:12]}"
    tail = image.rsplit("/", 1)[-1]
    return tail.rsplit(":", 1)[1] if ":" in tail else "latest"


def _healthy(state: str) -> bool:
    return state in {"running", "running/healthy"}


def _wait_ready(root: Path, names: list[str], *, timeout_seconds: int = 180) -> None:
    if not names:
        return
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, str] = {}
    while True:
        last = {name: _container_state(root, name) for name in names}
        if all(_healthy(state) for state in last.values()):
            return
        terminal = {name: state for name, state in last.items() if state in {"absent", "dead", "exited"} or state.startswith("dead/") or state.startswith("exited/")}
        if terminal:
            raise UpgradeExecutionError(
                "UPGRADE_READY_FAILED",
                "required runtime failed before READY: " + ", ".join(f"{k}={v}" for k, v in terminal.items()),
            )
        if time.monotonic() >= deadline:
            raise UpgradeExecutionError(
                "UPGRADE_READY_TIMEOUT",
                "required runtime did not become READY: " + ", ".join(f"{k}={v}" for k, v in last.items()),
            )
        time.sleep(2)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", f"cannot read {path}: {exc}") from exc


def _read_env_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise UpgradeExecutionError("UPGRADE_ENV_READ_FAILED", f"cannot read operational .env: {exc}") from exc
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _atomic_update_env(path: Path, updates: dict[str, str]) -> None:
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UpgradeExecutionError("UPGRADE_ENV_READ_FAILED", f"cannot read operational .env: {exc}") from exc

    remaining = dict(updates)
    output: list[str] = []
    for raw in original.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                newline = "\n" if raw.endswith("\n") else ""
                output.append(f"{key}={remaining.pop(key)}{newline}")
                continue
        output.append(raw)

    if remaining:
        raise UpgradeExecutionError(
            "UPGRADE_ENV_KEY_MISSING",
            "selected component version keys are missing from operational .env: " + ", ".join(sorted(remaining)),
        )

    tmp = path.with_name(path.name + ".upgrade.tmp")
    try:
        tmp.write_text("".join(output), encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise UpgradeExecutionError("UPGRADE_ENV_WRITE_FAILED", f"cannot update operational .env atomically: {exc}") from exc


def _target_image_ref(component_key: str, component: dict, selection: dict, env: dict[str, str]) -> str:
    apply = component.get("apply")
    image_env_key = apply.get("image_env_key") if isinstance(apply, dict) else None
    if not isinstance(image_env_key, str) or not image_env_key:
        raise UpgradeExecutionError(
            "UPGRADE_INTERNAL_CONFIG",
            f"component has no image_env_key for target preflight: {component_key}",
        )
    repository = env.get(image_env_key)
    if not repository:
        raise UpgradeExecutionError(
            "UPGRADE_ENV_KEY_MISSING",
            f"target image repository key is missing from operational .env: {image_env_key}",
        )
    version = selection.get("version")
    if not isinstance(version, str) or not version:
        raise UpgradeExecutionError("UPGRADE_PLAN_INVALID", f"selected target version is invalid: {component_key}")
    return f"{repository}:{version}"


def _verify_selected_digest(component_key: str, image_ref: str, selection: dict) -> None:
    selected_ref = selection.get("target_image")
    selected_digest = selection.get("target_digest")
    if not all(isinstance(value, str) and value for value in (selected_ref, selected_digest)):
        raise UpgradeExecutionError(
            "UPGRADE_PLAN_STALE",
            f"selected target has no immutable identity for {component_key}; reselect the target",
        )
    if selected_ref != image_ref:
        raise UpgradeExecutionError(
            "UPGRADE_PLAN_STALE",
            f"target image reference changed for {component_key}: selected {selected_ref}, now {image_ref}",
        )
    try:
        probe = upgrade_registry.manifest_probe(image_ref)
    except upgrade_registry.RegistryError as exc:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_NOT_AVAILABLE",
            f"cannot resolve selected target {image_ref}: {exc}",
        ) from exc
    if probe.status != "ok" or not probe.digest:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_NOT_AVAILABLE",
            f"selected target is not available: {image_ref} ({probe.status})",
        )
    if probe.digest != selected_digest:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_MOVED",
            f"selected target tag moved for {component_key}: {selected_digest} -> {probe.digest}",
        )


def _preflight_target_image(root: Path, image_ref: str) -> None:
    try:
        cp = subprocess.run(
            ["docker", "manifest", "inspect", image_ref],
            cwd=root,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_PREFLIGHT_FAILED",
            f"cannot inspect target image {image_ref}: {exc}",
        ) from exc
    if cp.returncode != 0:
        detail = (cp.stderr or "").strip()
        raise UpgradeExecutionError(
            "UPGRADE_TARGET_NOT_AVAILABLE",
            f"target image is not available: {image_ref}" + (f": {detail}" if detail else ""),
        )


def _recovery_point(root: Path) -> str:
    script = root / "commands" / "recovery" / "backup-all.py"
    cp = _run([sys.executable, str(script), "--json"], cwd=root, capture=True)
    try:
        payload = json.loads(cp.stdout)
        path = str(payload["backup_set"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpgradeExecutionError("UPGRADE_BACKUP_INVALID", "backup engine returned invalid JSON") from exc
    if not path:
        raise UpgradeExecutionError("UPGRADE_BACKUP_INVALID", "backup engine returned an empty recovery-point path")
    return path


def _run_commands(root: Path, directory: str, commands: list[list[str]], *, quiet: bool) -> None:
    cwd = root / directory
    for command in commands:
        cmd = list(command)
        if cmd[0].startswith("./"):
            cmd = ["bash", cmd[0], *cmd[1:]]
        _run(cmd, cwd=cwd, capture=quiet)


def _load_manifests(root: Path) -> dict[int, dict]:
    manifests: dict[int, dict] = {}
    for path in sorted(root.glob("stack*_*/manifest.json")):
        data = _load_json(path)
        manifests[int(data["id"])] = data
    return manifests


def _stack_number(stack: str) -> int:
    if not stack.startswith("stack") or not stack[5:].isdigit():
        raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", f"invalid stack id: {stack}")
    return int(stack[5:])


def _prepared(root: Path, manifest: dict) -> bool:
    return (root / manifest["directory"] / ".lock").is_file()


def execute(
    *,
    root: Path,
    runtime_root: Path,
    selections: list[dict],
    components: dict[str, dict],
    plan_path: Path,
    quiet: bool = False,
) -> dict:
    if not selections:
        raise UpgradeExecutionError("UPGRADE_NOTHING_SELECTED", "no upgrades are selected")
    if os.geteuid() != 0:
        raise UpgradeExecutionError("UPGRADE_ROOT_REQUIRED", "upgrade execution requires root")
    env_path = root / ".env"
    if not env_path.is_file():
        raise UpgradeExecutionError("UPGRADE_ENV_MISSING", f"missing operational environment: {env_path}")

    lifecycle = _load_json(root / "commands" / "install-lifecycle.json")
    manifests = _load_manifests(root)
    env_values = _read_env_values(env_path)
    env_updates: dict[str, str] = {}
    affected_stacks: set[int] = set()
    recovery_required = False
    target_images: list[str] = []

    for selection in selections:
        component_key = f"{selection['stack']}/{selection['component']}"
        component = components.get(component_key)
        if component is None:
            raise UpgradeExecutionError("UPGRADE_COMPONENT_UNKNOWN", f"selected component is not in catalog: {component_key}")
        if not component.get("selectable", True):
            raise UpgradeExecutionError(
                "UPGRADE_COMPONENT_NOT_SELECTABLE",
                f"selected component is not executable by policy: {component_key}",
            )
        try:
            effective = upgrade_policy.effective_policy(runtime_root, component_key, component)[2]
        except upgrade_policy.PolicyError as exc:
            raise UpgradeExecutionError("UPGRADE_POLICY_INVALID", str(exc)) from exc
        current = selection.get("current_at_selection")
        target = selection.get("version")
        if not isinstance(current, str) or not isinstance(target, str):
            raise UpgradeExecutionError("UPGRADE_PLAN_INVALID", f"selected versions are invalid: {component_key}")
        if not upgrade_policy.target_supported(effective, current, target):
            raise UpgradeExecutionError(
                "UPGRADE_TARGET_UNSUPPORTED",
                f"selected target {target} is not permitted by {effective} policy for {component_key}",
            )
        apply = component.get("apply")
        if not isinstance(apply, dict) or apply.get("type") != "env-version":
            raise UpgradeExecutionError("UPGRADE_COMPONENT_NOT_EXECUTABLE", f"component has no safe executor: {component_key}")
        env_key = apply.get("env_key")
        if not isinstance(env_key, str) or not env_key:
            raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", f"component has invalid env_key: {component_key}")
        env_updates[env_key] = selection["version"]
        affected_stacks.add(_stack_number(selection["stack"]))
        recovery_required = recovery_required or bool(component.get("recovery_required", False))
        image_ref = _target_image_ref(component_key, component, selection, env_values)
        _verify_selected_digest(component_key, image_ref, selection)
        target_images.append(image_ref)

    for image_ref in target_images:
        _preflight_target_image(root, image_ref)

    recovery_point: str | None = None
    if recovery_required:
        recovery_point = _recovery_point(root)

    try:
        _atomic_update_env(env_path, env_updates)

        for sid in sorted(affected_stacks):
            entry = lifecycle["stacks"][str(sid)]
            selected_for_stack = [s for s in selections if _stack_number(s["stack"]) == sid]
            for selection in selected_for_stack:
                component = components[f"{selection['stack']}/{selection['component']}"]
                deploy = component["apply"].get("deploy")
                if not isinstance(deploy, list) or not deploy:
                    raise UpgradeExecutionError(
                        "UPGRADE_INTERNAL_CONFIG",
                        f"component has no targeted deploy command: {selection['stack']}/{selection['component']}",
                    )
                _run_commands(root, entry["directory"], [deploy], quiet=quiet)

            _wait_ready(root, entry["required_containers"])
            _run_commands(root, entry["directory"], entry.get("reconcile", []), quiet=quiet)
            _wait_ready(root, entry["required_containers"])
            _run_commands(root, entry["directory"], entry.get("verify", []), quiet=quiet)

            for selection in selected_for_stack:
                component = components[f"{selection['stack']}/{selection['component']}"]
                actual = _version_from_image(_running_image(root, component["container"]))
                if actual != selection["version"]:
                    raise UpgradeExecutionError(
                        "UPGRADE_TARGET_NOT_RUNNING",
                        f"{selection['stack']}/{selection['component']} expected {selection['version']} but runtime reports {actual}",
                    )

        reverified: list[int] = []
        for provider_sid in sorted(affected_stacks):
            provider = manifests[provider_sid]
            provider_caps = set(provider.get("provides", []))
            for sid, manifest in manifests.items():
                if sid in affected_stacks or not _prepared(root, manifest):
                    continue
                depends_by_id = provider_sid in set(manifest.get("requires", [])) | set(manifest.get("optional", []))
                consumes_capability = bool(provider_caps & (set(manifest.get("consumes", [])) | set(manifest.get("optional_consumes", []))))
                if not (depends_by_id or consumes_capability):
                    continue
                entry = lifecycle["stacks"][str(sid)]
                _run_commands(root, entry["directory"], entry.get("verify", []), quiet=quiet)
                if sid not in reverified:
                    reverified.append(sid)

        plan = _load_json(plan_path)
        for selection in selections:
            plan["selected"].pop(f"{selection['stack']}/{selection['component']}", None)
        tmp = plan_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, plan_path)

        history_path = runtime_root / "platform" / "upgrade-history.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": 1,
            "success": True,
            "recovery_point": recovery_point,
            "target_images": target_images,
            "upgraded": selections,
            "reverified_stacks": sorted(reverified),
        }
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event
    except UpgradeExecutionError as exc:
        if exc.recovery_point is None:
            exc.recovery_point = recovery_point
        raise
