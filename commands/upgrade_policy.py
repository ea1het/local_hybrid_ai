"""Installation-local upgrade compatibility policy evaluation and persistence.

The module keeps project defaults separate from per-installation overrides and
supports exactly ``minor-series``, ``major-series`` and ``manual`` policy modes.
It determines whether an explicitly named target is compatible with the current
identity; it never discovers targets, selects one automatically or executes an
upgrade. Existing selections are revalidated rather than silently discarded when
policy changes.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

POLICIES = ("minor-series", "major-series", "manual")
SCHEMA_VERSION = 1
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?$")


class PolicyError(RuntimeError):
    pass


def policy_path(runtime_root: Path) -> Path:
    return runtime_root / "platform" / "upgrade-policy.json"


def load_overrides(runtime_root: Path) -> dict[str, str]:
    path = policy_path(runtime_root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read upgrade policy state: {exc}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("overrides"), dict):
        raise PolicyError("unsupported upgrade policy state schema")
    overrides: dict[str, str] = {}
    for component_key, value in payload["overrides"].items():
        if value not in POLICIES:
            raise PolicyError(f"invalid policy override for {component_key}: {value}")
        overrides[str(component_key)] = str(value)
    return overrides


def _save_overrides(runtime_root: Path, overrides: dict[str, str]) -> None:
    path = policy_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "overrides": dict(sorted(overrides.items()))}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def set_override(runtime_root: Path, component_key: str, policy: str) -> None:
    if policy not in POLICIES:
        raise PolicyError(f"unsupported upgrade policy: {policy}")
    overrides = load_overrides(runtime_root)
    overrides[component_key] = policy
    _save_overrides(runtime_root, overrides)


def clear_override(runtime_root: Path, component_key: str) -> None:
    overrides = load_overrides(runtime_root)
    overrides.pop(component_key, None)
    _save_overrides(runtime_root, overrides)


def default_policy(component: dict) -> str:
    value = component.get("default_policy", "manual")
    if value not in POLICIES:
        raise PolicyError(f"invalid default policy for {component.get('stack')}/{component.get('id')}: {value}")
    return value


def effective_policy(runtime_root: Path, component_key: str, component: dict) -> tuple[str, str | None, str]:
    default = default_policy(component)
    override = load_overrides(runtime_root).get(component_key)
    return default, override, override or default


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.fullmatch(value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def target_is_newer(current: str, target: str) -> bool | None:
    current_parts = version_tuple(current)
    target_parts = version_tuple(target)
    if current_parts is None or target_parts is None:
        return None
    return target_parts > current_parts


def target_supported(policy: str, current: str, target: str) -> bool:
    if current == target:
        return False
    current_parts = version_tuple(current)
    target_parts = version_tuple(target)

    if policy == "manual":
        # Manual means the operator names the exact target and local-ai performs no
        # automatic series inference. When both values are comparable, downgrades
        # remain forbidden; non-semver identities are accepted only as explicit targets.
        return target_parts > current_parts if current_parts is not None and target_parts is not None else True

    if current_parts is None or target_parts is None or target_parts <= current_parts:
        return False
    if policy == "minor-series":
        return target_parts[:2] == current_parts[:2]
    if policy == "major-series":
        return target_parts[0] == current_parts[0]
    raise PolicyError(f"unsupported upgrade policy: {policy}")


def selection_status(runtime_root: Path, component_key: str, component: dict, selection: dict | None) -> dict:
    default, override, effective = effective_policy(runtime_root, component_key, component)
    result = {
        "default_policy": default,
        "override_policy": override,
        "effective_policy": effective,
        "selection_valid": None,
    }
    if selection:
        current = selection.get("current_at_selection")
        target = selection.get("version")
        result["selection_valid"] = bool(
            isinstance(current, str)
            and isinstance(target, str)
            and component.get("selectable", True)
            and target_supported(effective, current, target)
        )
    return result
