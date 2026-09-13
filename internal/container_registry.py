from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteProbe:
    digest: str | None
    status: str


@dataclass(frozen=True)
class RegistryState:
    image: str
    local_digest: str | None
    remote_digest: str | None
    tracking_image: str | None = None
    remote_status: str = "ok"

    @property
    def update_available(self) -> bool | None:
        if not self.local_digest or not self.remote_digest:
            return None
        return self.local_digest != self.remote_digest


def _repository_name(reference: str) -> str:
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


def _classify_remote_failure(stderr: str) -> str:
    text = stderr.lower()
    if "429" in text or "too many requests" in text:
        return "rate_limited"
    if "401" in text or "unauthorized" in text or "authentication required" in text:
        return "unauthorized"
    if "403" in text or "forbidden" in text:
        return "forbidden"
    if "404" in text or "not found" in text or "manifest unknown" in text:
        return "not_found"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "error"


def remote_probe(image: str) -> RemoteProbe:
    """Inspect a tracked tag/channel without pulling or mutating runtime state."""
    cp = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest.Digest}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        return RemoteProbe(None, _classify_remote_failure(cp.stderr))
    raw = cp.stdout.strip()
    if not raw:
        return RemoteProbe(None, "empty")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw.strip('"')
    digest = str(value) if str(value).startswith("sha256:") else None
    return RemoteProbe(digest, "ok" if digest else "invalid")


def remote_digest(image: str) -> str | None:
    """Compatibility wrapper returning only the remote digest."""
    return remote_probe(image).digest


def tracking_reference(image: str, explicit: str | None = None) -> str | None:
    """Return the mutable tag/channel used to discover changes for an image.

    A ref of the form repo:tag@sha256:... naturally tracks repo:tag.  A pure
    digest pin has no discoverable channel unless the catalog explicitly
    declares one.
    """
    if explicit:
        return explicit
    if "@sha256:" not in image:
        return image
    before_digest = image.split("@", 1)[0]
    tail = before_digest.rsplit("/", 1)[-1]
    if ":" in tail:
        return before_digest
    return None


def display_label(image: str, tracking_image: str | None = None) -> str:
    """Human label: prefer a published tag/channel, never the digest as version."""
    tracked = tracking_reference(image, tracking_image)
    if tracked:
        tail = tracked.rsplit("/", 1)[-1]
        if ":" in tail:
            tag = tail.rsplit(":", 1)[1]
        else:
            tag = "latest"
        return f"{tag} (pinned)" if "@sha256:" in image else tag
    if "@sha256:" in image:
        return "pinned"
    return image.rsplit("/", 1)[-1]


def inspect(container: str | None, image: str | None, *, tracking_image: str | None = None) -> RegistryState | None:
    if not container or not image or "${" in image:
        return None
    tracked = tracking_reference(image, tracking_image)
    if tracked is None:
        return RegistryState(
            image=image,
            local_digest=local_digest(container, image),
            remote_digest=None,
            tracking_image=None,
            remote_status="not_tracked",
        )
    remote = remote_probe(tracked)
    return RegistryState(
        image=image,
        local_digest=local_digest(container, image),
        remote_digest=remote.digest,
        tracking_image=tracked,
        remote_status=remote.status,
    )
