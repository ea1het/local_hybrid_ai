from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistryState:
    image: str
    local_digest: str | None
    remote_digest: str | None

    @property
    def update_available(self) -> bool | None:
        if not self.local_digest or not self.remote_digest:
            return None
        return self.local_digest != self.remote_digest


def _repository_name(reference: str) -> str:
    """Return a registry-independent repository name for comparison.

    Docker may preserve an explicit registry in Config.Image while RepoDigests
    omits Docker Hub's registry prefix.  Normalizing both sides prevents a
    false unknown for equivalent references such as
    docker.io/searxng/searxng and searxng/searxng.
    """
    repository = reference.split("@", 1)[0]
    tail = repository.rsplit("/", 1)[-1]
    if ":" in tail:
        repository = repository.rsplit(":", 1)[0]

    parts = repository.split("/")
    if parts and parts[0] in {"docker.io", "index.docker.io"}:
        parts = parts[1:]
    if len(parts) == 1:
        parts.insert(0, "library")
    return "/".join(parts)


def _repo_digest_for_image(image: str, repo_digests: list[str]) -> str | None:
    repository = _repository_name(image)
    for item in repo_digests:
        if "@sha256:" not in item:
            continue
        item_repo, digest = item.split("@", 1)
        if _repository_name(item_repo) == repository:
            return digest
    return None


def _inspect_json(target: str) -> dict | None:
    cp = subprocess.run(
        ["docker", "inspect", target],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        return None
    try:
        values = json.loads(cp.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(values, list) or not values or not isinstance(values[0], dict):
        return None
    return values[0]


def local_digest(container: str, image: str) -> str | None:
    """Resolve the immutable repo digest of the exact image used by a container."""
    container_data = _inspect_json(container)
    if not container_data:
        return None
    image_id = container_data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        return None

    image_data = _inspect_json(image_id)
    if not image_data:
        return None
    repo_digests = image_data.get("RepoDigests")
    if not isinstance(repo_digests, list):
        return None
    return _repo_digest_for_image(image, [str(value) for value in repo_digests])


def remote_digest(image: str) -> str | None:
    """Inspect the configured image reference without pulling or mutating runtime state."""
    cp = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest.Digest}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        return None
    raw = cp.stdout.strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw.strip('"')
    return str(value) if str(value).startswith("sha256:") else None


def inspect(container: str | None, image: str | None) -> RegistryState | None:
    if not container or not image or "${" in image:
        return None
    return RegistryState(
        image=image,
        local_digest=local_digest(container, image),
        remote_digest=remote_digest(image),
    )
