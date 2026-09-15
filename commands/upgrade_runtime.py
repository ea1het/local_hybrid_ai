# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Runtime and Compose image discovery for upgrade inventory."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol


class ComponentLike(Protocol):
    service: str | None
    container: str | None
    compose: str | None


_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[-?]([^}]*))?\}")
_SERVICE = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$")
_IMAGE = re.compile(r"^    image:\s*(.+?)\s*$")


def read_env(root: Path) -> dict[str, str]:
    """Read the operational env file, falling back to its repository template."""
    path = root / ".env"
    if not path.is_file():
        path = root / ".env.template"

    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def substitute_env(value: str, env: dict[str, str]) -> str:
    """Resolve the Compose-style env references used by repository image fields."""
    def replace(match: re.Match[str]) -> str:
        key, default = match.group(1), match.group(2)
        return env.get(key) or (default or match.group(0))

    return _ENV_REFERENCE.sub(replace, value)


def compose_image(root: Path, component: ComponentLike, env: dict[str, str]) -> str | None:
    """Return the configured image for a component's Compose service."""
    if not component.compose or not component.service:
        return None

    path = root / component.compose
    if not path.is_file():
        return None

    current_service: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        service_match = _SERVICE.match(raw)
        if service_match:
            current_service = service_match.group(1)
            continue
        if current_service != component.service:
            continue
        image_match = _IMAGE.match(raw)
        if image_match:
            image = image_match.group(1).strip('"').strip("'")
            return substitute_env(image, env)
    return None


def running_image(root: Path, component: ComponentLike) -> str | None:
    """Return the image configured on the running container, when observable."""
    if not component.container:
        return None
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.Config.Image}}", component.container],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
