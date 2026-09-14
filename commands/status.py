# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Build the operator-facing Desired / Deployed / Actual / Drift inventory.

Status keeps installation intent, recorded guarded-upgrade history and observed
runtime identity separate. Installation-owned configuration defines Desired;
runtime image identity defines Actual. Mutable runtime image references are
resolved through the same registry boundary used by upgrade discovery whenever
possible, independently of how Desired is expressed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from commands import upgrade, upgrade_registry

SCHEMA_VERSION = "2"


class StatusError(RuntimeError):
    pass


def _deployed_versions(runtime_root: Path) -> dict[str, str]:
    """Return the last successfully applied version known for each component."""
    path = runtime_root / "platform" / "upgrade-history.jsonl"
    if not path.is_file():
        return {}

    deployed: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StatusError(f"cannot read upgrade history: {exc}") from exc

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StatusError(f"invalid upgrade history at line {number}") from exc
        if event.get("success") is not True:
            continue
        upgraded = event.get("upgraded", [])
        if not isinstance(upgraded, list):
            raise StatusError(f"invalid successful upgrade history at line {number}")
        for item in upgraded:
            if not isinstance(item, dict):
                raise StatusError(f"invalid successful upgrade history at line {number}")
            stack = item.get("stack")
            component = item.get("component")
            version = item.get("version")
            if all(isinstance(value, str) and value for value in (stack, component, version)):
                deployed[f"{stack}/{component}"] = version
    return deployed


def _deployed(component_key: str, desired: str, actual: str, deployed_versions: dict[str, str]) -> str:
    """Resolve deployed state without confusing absent history with uncertainty."""
    recorded = deployed_versions.get(component_key)
    if recorded is not None:
        return recorded
    if desired == "n/a" and actual == "n/a":
        return "n/a"
    if actual != "n/a":
        return actual
    return "unknown"


def _drift(desired: str, actual: str) -> str:
    if desired == "n/a":
        return "n/a"
    if actual == "n/a":
        return "yes"
    return "no" if desired == actual else "yes"


def _is_floating_image_reference(image: str | None) -> bool:
    """Return whether an image reference follows a mutable tag/channel."""
    if not image or "${" in image or "@sha256:" in image:
        return False
    tag = upgrade_registry.parse_reference(image).tag
    if not tag:
        return True
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-[0-9A-Za-z][0-9A-Za-z._-]*)?", tag)
    if match is None:
        return True
    return len(match.group(1).split(".")) < 3


def _concrete_runtime_identity(component, actual_image: str | None) -> tuple[str, str | None]:
    """Return concrete Actual and local digest evidence for the observed runtime.

    A container may still report the historical mutable Config.Image string after
    source has migrated to an exact installation-owned baseline. Runtime identity
    therefore must be resolved independently of Desired. Registry failure never
    invents a concrete version; callers receive the literal runtime tag and no
    digest proof in that case.
    """
    actual = upgrade.version_from_image(actual_image)
    if not actual_image or not _is_floating_image_reference(actual_image):
        return actual, None
    if not getattr(component, "container", None):
        return actual, None
    try:
        state = upgrade_registry.inspect(component.container, actual_image)
    except upgrade_registry.RegistryError:
        return actual, None
    if state is None:
        return actual, None
    return state.current_version or actual, state.local_digest


def _resolve_state(component, desired_image: str | None, actual_image: str | None) -> tuple[str, str, str]:
    """Resolve Desired/Actual while keeping installation intent authoritative.

    Desired comes from installation-owned configuration and is never advanced by
    registry discovery. Actual comes from the running container and may require
    registry mapping when Docker still records a mutable historical image tag.
    """
    desired = upgrade.version_from_image(desired_image)
    actual, _local_digest = _concrete_runtime_identity(component, actual_image)

    if desired == "n/a":
        return desired, actual, "n/a"
    if actual == "n/a":
        return desired, actual, "yes"

    if not _is_floating_image_reference(desired_image):
        return desired, actual, _drift(desired, actual)

    # Compatibility path for installations not yet migrated to exact authority.
    if not actual_image or not getattr(component, "container", None):
        return desired, actual, "n/a"
    try:
        state = upgrade_registry.inspect(
            component.container,
            actual_image,
            tracking_image=desired_image,
        )
    except upgrade_registry.RegistryError:
        return desired, actual, "n/a"
    if state is None:
        return desired, actual, "n/a"

    desired_display = state.available_version or desired
    actual_display = state.current_version or actual
    if state.local_digest and state.remote_digest:
        drift = "no" if state.local_digest == state.remote_digest else "yes"
    elif state.current_version and state.available_version:
        drift = "no" if state.current_version == state.available_version else "yes"
    else:
        drift = "n/a"
    return desired_display, actual_display, drift


def inventory(*, runtime_root: Path | None = None, deployed_versions: dict[str, str] | None = None) -> list[dict]:
    """Build status without hiding state dependencies behind global runtime lookups."""
    env = upgrade.read_env()
    if deployed_versions is None:
        deployed_versions = _deployed_versions(runtime_root or upgrade.runtime_root())

    rows: list[dict] = []
    for component in upgrade.load_catalog():
        desired_image = upgrade.compose_image(component, env)
        actual_image = upgrade.running_image(component)
        desired, actual, drift = _resolve_state(component, desired_image, actual_image)
        component_key = upgrade.key(component)
        rows.append({
            "stack": component.stack,
            "component": component.name,
            "desired": desired,
            "deployed": _deployed(component_key, desired, actual, deployed_versions),
            "actual": actual,
            "drift": drift,
        })
    return rows


def _print_table(rows: list[dict]) -> None:
    headers = ("STACK", "COMPONENT", "DESIRED", "DEPLOYED", "ACTUAL", "DRIFT")
    values = [headers]
    for row in rows:
        values.append((
            upgrade.human_stack_id(row["stack"]),
            row["component"],
            row["desired"],
            row["deployed"],
            row["actual"],
            row["drift"],
        ))
    widths = [max(len(str(row[i])) for row in values) for i in range(len(headers))]
    for index, row in enumerate(values):
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def main(*, json_output: bool = False) -> int:
    try:
        rows = inventory()
    except (StatusError, OSError, json.JSONDecodeError) as exc:
        if json_output:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "command": "status",
                "success": False,
                "error": {"code": "STATUS_STATE_INVALID", "message": str(exc)},
            }, indent=2, sort_keys=True))
        else:
            print(f"STATUS ERROR [STATUS_STATE_INVALID]: {exc}")
        return 1

    if json_output:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "command": "status",
            "success": True,
            "components": rows,
        }, indent=2, sort_keys=True))
    else:
        _print_table(rows)
    return 0
