from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


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
            "UPGRADE_TARGET_UNAVAILABLE",
            f"target image is not available: {image_ref}" + (f": {detail}" if detail else ""),
        )


def _recovery_point(root: Path) -> str:
    cp = _run([sys.executable, str(root / "bkp-dr" / "backup-all.py"), "--json"], cwd=root, capture=True)
    try:
        payload = json.loads(cp.stdout)
        path = str(payload["path"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpgradeExecutionError("UPGRADE_BACKUP_INVALID", "backup engine returned invalid JSON") from exc
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

    lifecycle = _load_json(root / "installer" / "lifecycle.json")
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
        apply = component.get("apply")
        if not isinstance(apply, dict) or apply.get("type") != "env-version":
            raise UpgradeExecutionError("UPGRADE_COMPONENT_NOT_EXECUTABLE", f"component has no safe executor: {component_key}")
        env_key = apply.get("env_key")
        if not isinstance(env_key, str) or not env_key:
            raise UpgradeExecutionError("UPGRADE_INTERNAL_CONFIG", f"component has invalid env_key: {component_key}")
        env_updates[env_key] = selection["version"]
        affected_stacks.add(_stack_number(selection["stack"]))
        recovery_required = recovery_required or bool(component.get("recovery_required", False))
        target_images.append(_target_image_ref(component_key, component, selection, env_values))

    # PRE-FLIGHT: prove every exact selected image exists before backup or desired-state mutation.
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
