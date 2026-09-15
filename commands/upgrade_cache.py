# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Best-effort persistence for upgrade registry discovery state."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from commands import upgrade_registry

SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 300
MAX_ENTRIES = 64
MAX_TTL_SECONDS = 86400


def path(runtime_root: Path) -> Path:
    return runtime_root / "platform" / "registry-discovery-cache.json"


def ttl_seconds() -> int:
    raw = os.environ.get("LOCAL_AI_REGISTRY_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return max(0, min(value, MAX_TTL_SECONDS))


def load(cache_path: Path) -> dict[str, dict]:
    if not cache_path.is_file():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("entries"), dict):
        return {}
    return {
        key: value
        for key, value in data["entries"].items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def save(cache_path: Path, entries: dict[str, dict]) -> None:
    ordered = sorted(
        entries.items(),
        key=lambda item: float(item[1].get("stored_at", 0)),
        reverse=True,
    )[:MAX_ENTRIES]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "entries": dict(ordered),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, cache_path)
    except OSError:
        return


def key(component_key: str, image: str, local_digest: str | None) -> str:
    return json.dumps(
        {
            "component": component_key,
            "image": image,
            "local_digest": local_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def get(
    cache_path: Path,
    component_key: str,
    container: str | None,
    image: str,
) -> upgrade_registry.RegistryState | None:
    ttl = ttl_seconds()
    if ttl <= 0:
        return None
    local = upgrade_registry.local_digest(container, image) if container else None
    entry = load(cache_path).get(key(component_key, image, local))
    if not entry:
        return None
    stored_at = entry.get("stored_at")
    state = entry.get("state")
    if not isinstance(stored_at, (int, float)) or time.time() - float(stored_at) > ttl:
        return None
    if not isinstance(state, dict):
        return None
    try:
        return upgrade_registry.RegistryState(**state)
    except TypeError:
        return None


def store(
    cache_path: Path,
    component_key: str,
    image: str,
    state: upgrade_registry.RegistryState,
) -> None:
    if ttl_seconds() <= 0:
        return
    entries = load(cache_path)
    entries[key(component_key, image, state.local_digest)] = {
        "stored_at": time.time(),
        "state": dict(state.__dict__),
    }
    save(cache_path, entries)
