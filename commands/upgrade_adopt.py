# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Adopt observed component image identities into the protected operational env.

This is a non-disruptive migration boundary for installations that predate
explicit image authority variables. Adoption never recreates containers: it
records the already-running image/version as installation-owned intent.
Existing conflicting values fail closed and are never overwritten implicitly.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from commands import upgrade, upgrade_registry

SCHEMA_VERSION = "1"

AUTHORITIES: dict[str, dict[str, str]] = {
    "stack1/haproxy": {"type": "split", "image_key": "HAPROXY_IMAGE", "version_key": "HAPROXY_VERSION"},
    "stack2/searxng": {"type": "ref", "ref_key": "SEARXNG_IMAGE"},
    "stack2/firecrawl": {"type": "ref", "ref_key": "FIRECRAWL_IMAGE"},
    "stack2/firecrawl-playwright": {"type": "ref", "ref_key": "FIRECRAWL_PLAYWRIGHT_IMAGE"},
    "stack2/redis": {"type": "split", "image_key": "FIRECRAWL_REDIS_IMAGE", "version_key": "FIRECRAWL_REDIS_VERSION"},
    "stack2/rabbitmq": {"type": "split", "image_key": "FIRECRAWL_RABBITMQ_IMAGE", "version_key": "FIRECRAWL_RABBITMQ_VERSION"},
    "stack2/nuq-postgres": {"type": "ref", "ref_key": "FIRECRAWL_POSTGRES_IMAGE"},
    "stack3/postgresql": {"type": "ref", "ref_key": "LITELLM_POSTGRES_IMAGE"},
    "stack3/litellm": {"type": "split", "image_key": "LITELLM_IMAGE", "version_key": "LITELLM_VERSION"},
    "stack4/gitea": {"type": "ref", "ref_key": "GITEA_IMAGE"},
    "stack5/dockhand": {"type": "split", "image_key": "DOCKHAND_REPOSITORY", "version_key": "DOCKHAND_VERSION"},
    "stack6/hermes": {"type": "split", "image_key": "HERMES_IMAGE", "version_key": "HERMES_VERSION"},
    "stack7/open-webui": {"type": "split", "image_key": "OPENWEBUI_IMAGE", "version_key": "OPENWEBUI_VERSION"},
}


class AdoptionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "UPGRADE_ADOPTION_ERROR"):
        super().__init__(message)
        self.code = code


def _read_operational_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AdoptionError(f"cannot read operational .env: {exc}", code="UPGRADE_ADOPTION_ENV_READ_FAILED") from exc
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _repository_text(reference: upgrade_registry.ImageReference) -> str:
    repository = reference.repository
    if reference.registry == "docker.io":
        if repository.startswith("library/"):
            repository = repository[len("library/"):]
        return repository
    return f"{reference.registry}/{repository}"


def _tracking_tag(tag: str | None) -> bool:
    if not tag:
        return True
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-[0-9A-Za-z][0-9A-Za-z._-]*)?", tag)
    if match is None:
        return True
    return len(match.group(1).split(".")) < 3


def _split_identity(component, running: str) -> tuple[str, str]:
    reference = upgrade_registry.parse_reference(running)
    version = reference.tag
    if _tracking_tag(version):
        try:
            state = upgrade_registry.inspect(component.container, running)
        except upgrade_registry.RegistryError as exc:
            raise AdoptionError(
                f"cannot resolve installed version for {upgrade.key(component)}: {exc}",
                code="UPGRADE_ADOPTION_IDENTITY_UNRESOLVED",
            ) from exc
        if state is not None and state.current_version:
            version = state.current_version
    if not version:
        raise AdoptionError(
            f"cannot resolve installed version for {upgrade.key(component)}",
            code="UPGRADE_ADOPTION_IDENTITY_UNRESOLVED",
        )
    return _repository_text(reference), version


def desired_updates() -> tuple[dict[str, str], list[dict]]:
    components = {upgrade.key(component): component for component in upgrade.load_catalog()}
    updates: dict[str, str] = {}
    adopted: list[dict] = []

    for component_key, authority in AUTHORITIES.items():
        component = components.get(component_key)
        if component is None:
            raise AdoptionError(
                f"version authority references unknown component: {component_key}",
                code="UPGRADE_ADOPTION_CONFIG_INVALID",
            )
        running = upgrade.running_image(component)
        if not running:
            raise AdoptionError(
                f"cannot adopt {component_key}: running image is unavailable",
                code="UPGRADE_ADOPTION_RUNTIME_UNAVAILABLE",
            )

        if authority["type"] == "split":
            repository, version = _split_identity(component, running)
            updates[authority["image_key"]] = repository
            updates[authority["version_key"]] = version
            adopted.append({"component": component_key, "image": repository, "version": version, "running_image": running})
        else:
            updates[authority["ref_key"]] = running
            adopted.append({
                "component": component_key,
                "image": running,
                "version": upgrade.version_from_image(running),
                "running_image": running,
            })

    return updates, adopted


def _apply_missing(path: Path, expected: dict[str, str]) -> list[str]:
    current = _read_operational_env(path)
    conflicts = {
        key: (current[key], value)
        for key, value in expected.items()
        if key in current and current[key] != value
    }
    if conflicts:
        detail = ", ".join(f"{key}={actual} (runtime requires {wanted})" for key, (actual, wanted) in sorted(conflicts.items()))
        raise AdoptionError(
            "operational version authority conflicts with the running installation: " + detail,
            code="UPGRADE_ADOPTION_CONFLICT",
        )

    missing = {key: value for key, value in expected.items() if key not in current}
    if not missing:
        return []

    tmp = path.with_name(path.name + ".adopt.tmp")
    try:
        original = path.read_text(encoding="utf-8")
        suffix = "" if original.endswith("\n") else "\n"
        block = [suffix, "\n# Managed component image authority (adopted by ./local-ai upgrade adopt)\n"]
        block.extend(f"{key}={value}\n" for key, value in sorted(missing.items()))
        tmp.write_text(original + "".join(block), encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise AdoptionError(f"cannot update operational .env atomically: {exc}", code="UPGRADE_ADOPTION_ENV_WRITE_FAILED") from exc
    return sorted(missing)


def main(args: list[str], *, json_output: bool = False) -> int:
    execute = args == ["--yes"]
    if args not in ([], ["--yes"]):
        raise AdoptionError("usage: ./local-ai upgrade adopt [--yes]", code="UPGRADE_USAGE")
    if execute and os.geteuid() != 0:
        raise AdoptionError("version adoption requires root", code="UPGRADE_ROOT_REQUIRED")

    env_path = upgrade.ROOT / ".env"
    if not env_path.is_file():
        raise AdoptionError(f"missing operational environment: {env_path}", code="UPGRADE_ENV_MISSING")

    expected, components = desired_updates()
    current = _read_operational_env(env_path)
    conflicts = [key for key, value in expected.items() if key in current and current[key] != value]
    missing = sorted(key for key in expected if key not in current)
    if conflicts:
        _apply_missing(env_path, expected)

    written: list[str] = []
    if execute:
        written = _apply_missing(env_path, expected)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "command": "upgrade.adopt",
        "success": True,
        "executed": execute,
        "missing_keys": missing,
        "written_keys": written,
        "components": components,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("VERSION AUTHORITY ADOPTION: " + ("PASS" if execute else "PLAN"))
        for item in components:
            print(f"- {item['component']}: {item['version']}")
        if missing:
            print("- missing operational keys: " + ", ".join(missing))
        else:
            print("- operational version authority already matches runtime")
        if not execute and missing:
            print("- no changes made; run `./local-ai upgrade adopt --yes` to persist this exact runtime baseline")
    return 0
