from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageReference:
    registry: str
    repository: str
    tag: str | None
    digest: str | None

    @property
    def registry_host(self) -> str:
        if self.registry in {"docker.io", "index.docker.io"}:
            return "registry-1.docker.io"
        return self.registry

    def with_tag(self, tag: str) -> str:
        prefix = "" if self.registry == "docker.io" else f"{self.registry}/"
        repository = self.repository
        if self.registry == "docker.io" and repository.startswith("library/"):
            repository = repository[len("library/"):]
        return f"{prefix}{repository}:{tag}"


@dataclass(frozen=True)
class RemoteProbe:
    digest: str | None
    status: str


@dataclass(frozen=True)
class TagProbe:
    tags: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class RegistryState:
    image: str
    local_digest: str | None
    remote_digest: str | None
    tracking_image: str | None = None
    remote_status: str = "ok"
    current_version: str | None = None
    available_version: str | None = None
    tags_status: str = "unchecked"
    registry: str | None = None
    repository: str | None = None

    @property
    def update_available(self) -> bool | None:
        if self.current_version and self.available_version:
            return self.current_version != self.available_version
        if not self.local_digest or not self.remote_digest:
            return None
        return self.local_digest != self.remote_digest


_VERSION_RE = re.compile(
    r"^(?P<prefix>v?)(?P<numbers>\d+(?:\.\d+)+)(?:-(?P<suffix>[0-9A-Za-z][0-9A-Za-z._-]*))?$"
)
_AUTH_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')
_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?', re.IGNORECASE)
_MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))
_TOKEN_CACHE: dict[tuple[str, str], str] = {}


def parse_reference(reference: str) -> ImageReference:
    base, sep, digest = reference.partition("@")
    digest = digest if sep else None

    last = base.rsplit("/", 1)[-1]
    tag: str | None = None
    if ":" in last:
        base, tag = base.rsplit(":", 1)

    parts = base.split("/")
    first = parts[0]
    if len(parts) > 1 and ("." in first or ":" in first or first == "localhost"):
        registry = first
        repository_parts = parts[1:]
    else:
        registry = "docker.io"
        repository_parts = parts

    if registry in {"docker.io", "index.docker.io"}:
        registry = "docker.io"
        if len(repository_parts) == 1:
            repository_parts.insert(0, "library")

    repository = "/".join(repository_parts)
    return ImageReference(registry, repository, tag, digest)


def _repository_name(reference: str) -> str:
    return parse_reference(reference).repository


def _repo_digest_for_image(image: str, repo_digests: list[str]) -> str | None:
    wanted = parse_reference(image)
    for item in repo_digests:
        if "@sha256:" not in item:
            continue
        item_ref = parse_reference(item)
        if item_ref.repository == wanted.repository and item_ref.registry == wanted.registry:
            return item_ref.digest
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


def _local_image_data(container: str) -> dict | None:
    container_data = _inspect_json(container)
    if not container_data:
        return None
    image_id = container_data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        return None
    return _inspect_json(image_id)


def local_digest(container: str, image: str) -> str | None:
    """Resolve the immutable repo digest of the exact image used by a container."""
    image_data = _local_image_data(container)
    if not image_data:
        return None
    repo_digests = image_data.get("RepoDigests")
    if not isinstance(repo_digests, list):
        return None
    return _repo_digest_for_image(image, [str(value) for value in repo_digests])


def local_version_hint(container: str, image: str, registry_tags_value: tuple[str, ...]) -> str | None:
    """Use metadata carried by the local image before probing many remote tags."""
    image_data = _local_image_data(container)
    if not image_data:
        return None
    wanted = parse_reference(image)

    repo_tags = image_data.get("RepoTags")
    if isinstance(repo_tags, list):
        candidates: list[str] = []
        for value in repo_tags:
            if not isinstance(value, str):
                continue
            ref = parse_reference(value)
            if (ref.registry, ref.repository) != (wanted.registry, wanted.repository):
                continue
            if ref.tag and ref.tag in registry_tags_value and _version_parts(ref.tag) is not None:
                candidates.append(ref.tag)
        if candidates:
            return version_tags(candidates)[0]

    config = image_data.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if isinstance(labels, dict):
        for key in (
            "org.opencontainers.image.version",
            "org.label-schema.version",
            "version",
        ):
            value = labels.get(key)
            if isinstance(value, str) and value in registry_tags_value and _version_parts(value) is not None:
                return value
    return None


def _classify_http_status(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    return "error"


def _urlopen(request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}, b""


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _bearer_token(challenge: str) -> str | None:
    if not challenge.lower().startswith("bearer "):
        return None
    params = dict(_AUTH_PARAM_RE.findall(challenge))
    realm = params.pop("realm", None)
    if not realm:
        return None
    separator = "&" if "?" in realm else "?"
    url = realm + separator + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "local-ai/registry-discovery"})
    status, _, body = _urlopen(request)
    if status != 200:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    token = payload.get("token") or payload.get("access_token")
    return token if isinstance(token, str) and token else None


def _registry_request(
    reference: ImageReference,
    path: str,
    *,
    method: str = "GET",
    accept: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    url = f"https://{reference.registry_host}{path}"
    base_headers = {"User-Agent": "local-ai/registry-discovery"}
    if accept:
        base_headers["Accept"] = accept

    cache_key = (reference.registry_host, reference.repository)
    token = _TOKEN_CACHE.get(cache_key)
    headers = dict(base_headers)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method=method)
    status, response_headers, body = _urlopen(request)
    if status != 401:
        return status, response_headers, body

    _TOKEN_CACHE.pop(cache_key, None)
    challenge = _header(response_headers, "WWW-Authenticate")
    if not challenge and token:
        request = urllib.request.Request(url, headers=base_headers, method=method)
        status, response_headers, body = _urlopen(request)
        if status != 401:
            return status, response_headers, body
        challenge = _header(response_headers, "WWW-Authenticate")

    new_token = _bearer_token(challenge or "")
    if not new_token:
        return status, response_headers, body

    _TOKEN_CACHE[cache_key] = new_token
    headers = dict(base_headers)
    headers["Authorization"] = f"Bearer {new_token}"
    request = urllib.request.Request(url, headers=headers, method=method)
    return _urlopen(request)


def _next_tags_path(reference: ImageReference, headers: dict[str, str]) -> str | None:
    link = _header(headers, "Link")
    if not link:
        return None
    match = _LINK_RE.search(link)
    if not match:
        return None
    parsed = urllib.parse.urlparse(match.group(1))
    if parsed.netloc and parsed.netloc != reference.registry_host:
        return None
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    expected_prefix = f"/v2/{reference.repository}/tags/list"
    return path if path.startswith(expected_prefix) else None


def registry_tags(image: str, *, limit: int = 5000, page_size: int = 1000) -> TagProbe:
    """List tags from the same registry package, following OCI pagination."""
    reference = parse_reference(image)
    path = f"/v2/{reference.repository}/tags/list?n={min(limit, page_size)}"
    collected: list[str] = []
    seen_tags: set[str] = set()
    seen_paths: set[str] = set()

    while path and path not in seen_paths and len(collected) < limit:
        seen_paths.add(path)
        status, headers, body = _registry_request(reference, path)
        if status != 200:
            return TagProbe(tuple(collected), _classify_http_status(status) if status else "error")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return TagProbe(tuple(collected), "invalid")
        tags = payload.get("tags")
        if not isinstance(tags, list):
            return TagProbe(tuple(collected), "invalid")
        for tag in tags:
            if isinstance(tag, str) and tag not in seen_tags:
                seen_tags.add(tag)
                collected.append(tag)
                if len(collected) >= limit:
                    break
        path = _next_tags_path(reference, headers)

    return TagProbe(tuple(collected), "ok")


def manifest_probe(image: str) -> RemoteProbe:
    reference = parse_reference(image)
    manifest_ref = reference.digest or reference.tag or "latest"
    path = f"/v2/{reference.repository}/manifests/{urllib.parse.quote(manifest_ref, safe=':')}"
    status, headers, _ = _registry_request(reference, path, method="HEAD", accept=_MANIFEST_ACCEPT)
    if 200 <= status < 300:
        digest = _header(headers, "Docker-Content-Digest")
        if digest and digest.startswith("sha256:"):
            return RemoteProbe(digest, "ok")
        return RemoteProbe(None, "invalid")
    return RemoteProbe(None, _classify_http_status(status) if status else "error")


def remote_probe(image: str) -> RemoteProbe:
    """Inspect an image in its own registry without pulling or mutating runtime state."""
    return manifest_probe(image)


def remote_digest(image: str) -> str | None:
    return remote_probe(image).digest


def _version_parts(tag: str) -> tuple[tuple[int, ...], str | None, bool] | None:
    match = _VERSION_RE.fullmatch(tag)
    if not match:
        return None
    numbers = tuple(int(value) for value in match.group("numbers").split("."))
    return numbers, match.group("suffix"), bool(match.group("prefix"))


def _version_sort_key(tag: str) -> tuple:
    parsed = _version_parts(tag)
    if parsed is None:
        return ((-1,), -1, -1, -1, "")
    numbers, suffix, has_v = parsed
    padded = numbers + (0,) * (6 - len(numbers))
    return (padded, len(numbers), 1 if suffix is None else 0, 1 if has_v else 0, tag)


def version_tags(tags: tuple[str, ...] | list[str]) -> list[str]:
    return sorted(
        (tag for tag in tags if _version_parts(tag) is not None),
        key=_version_sort_key,
        reverse=True,
    )


def _variant_family(tag: str | None) -> str | None:
    if not tag:
        return None
    parsed = _version_parts(tag)
    if parsed is None:
        return None
    suffix = parsed[1]
    if not suffix or re.fullmatch(r"[0-9a-fA-F]{7,40}", suffix):
        return None
    for family in ("alpine", "rootless", "slim", "bookworm", "bullseye", "debian", "ubuntu"):
        if suffix == family or suffix.startswith(family):
            return family
    return suffix


def _same_tag_family(candidate: str, source_tag: str | None) -> bool:
    if not source_tag:
        return True
    source = _version_parts(source_tag)
    candidate_parts = _version_parts(candidate)
    if source is None or candidate_parts is None:
        return True
    _, _, source_has_v = source
    _, _, candidate_has_v = candidate_parts
    if source_has_v != candidate_has_v:
        return False
    return _variant_family(candidate) == _variant_family(source_tag)


def _release_candidates(tags: tuple[str, ...], source_tag: str | None) -> list[str]:
    candidates = [tag for tag in version_tags(tags) if _same_tag_family(tag, source_tag)]
    source = _version_parts(source_tag) if source_tag else None
    if source:
        major = source[0][0]
        same_major = [tag for tag in candidates if (_version_parts(tag) or ((-1,), None, False))[0][0] == major]
        if same_major:
            candidates = same_major
    return candidates


def _numeric_channel_prefix(tag: str | None) -> tuple[int, ...] | None:
    if not tag:
        return None
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-[A-Za-z][0-9A-Za-z._-]*)?", tag)
    if not match:
        return None
    return tuple(int(value) for value in match.group(1).split("."))


def _channel_candidates(tags: tuple[str, ...], source_tag: str | None) -> list[str]:
    candidates = _release_candidates(tags, source_tag)
    prefix = _numeric_channel_prefix(source_tag)
    if not prefix:
        return candidates
    matching: list[str] = []
    for candidate in candidates:
        parsed = _version_parts(candidate)
        if parsed is None:
            continue
        numbers = parsed[0]
        if len(numbers) > len(prefix) and numbers[:len(prefix)] == prefix:
            matching.append(candidate)
    return matching or candidates


def _is_channel_tag(tag: str | None, tags: tuple[str, ...]) -> bool:
    if not tag:
        return False
    if tag in {"latest", "stable", "main", "edge", "alpine"}:
        return True
    parsed = _version_parts(tag)
    if parsed is None:
        return bool(re.fullmatch(r"\d+(?:\.\d+)?-[A-Za-z][0-9A-Za-z._-]*", tag))
    numbers = parsed[0]
    for candidate in _release_candidates(tags, tag):
        candidate_parsed = _version_parts(candidate)
        if candidate_parsed is None:
            continue
        candidate_numbers = candidate_parsed[0]
        if len(candidate_numbers) > len(numbers) and candidate_numbers[:len(numbers)] == numbers:
            return True
    return False


def _best_tag_for_digest(
    reference: ImageReference,
    digest: str | None,
    candidates: list[str],
    *,
    max_probes: int = 500,
) -> tuple[str | None, str]:
    if not digest:
        return None, "local_unknown"
    status = "not_found"
    for tag in candidates[:max_probes]:
        probe = manifest_probe(reference.with_tag(tag))
        if probe.status != "ok":
            status = probe.status
            if probe.status in {"rate_limited", "unauthorized", "forbidden"}:
                return None, probe.status
            continue
        status = "ok"
        if probe.digest == digest:
            return tag, "ok"
    return None, status


def tracking_reference(image: str, explicit: str | None = None) -> str | None:
    reference = parse_reference(image)
    if explicit:
        explicit_ref = parse_reference(explicit)
        if (explicit_ref.registry, explicit_ref.repository) != (reference.registry, reference.repository):
            raise RegistryError("tracking reference must use the configured image registry/repository")
        return explicit
    if reference.tag:
        return reference.with_tag(reference.tag)
    return None


def display_label(
    image: str,
    tracking_image: str | None = None,
    *,
    discovered_version: str | None = None,
) -> str:
    if discovered_version:
        return discovered_version
    reference = parse_reference(image)
    if reference.tag:
        return f"{reference.tag} (pinned)" if reference.digest else reference.tag
    if reference.digest:
        return "pinned"
    return "latest"


def inspect(
    container: str | None,
    image: str | None,
    *,
    tracking_image: str | None = None,
) -> RegistryState | None:
    if not container or not image or "${" in image:
        return None

    reference = parse_reference(image)
    local = local_digest(container, image)
    tags_probe = registry_tags(image)
    tags = tags_probe.tags

    current_version: str | None = None
    available_version: str | None = None
    remote = RemoteProbe(None, tags_probe.status if tags_probe.status != "ok" else "unknown")
    tracked = tracking_reference(image, tracking_image)

    if reference.tag and _version_parts(reference.tag) is not None:
        current_version = reference.tag

    if tags_probe.status == "ok":
        channel = _is_channel_tag(reference.tag, tags)

        if channel:
            candidates = _channel_candidates(tags, reference.tag)
            hint = local_version_hint(container, image, tags)
            if hint and hint in candidates:
                current_version = hint
            elif candidates:
                current_version, current_status = _best_tag_for_digest(reference, local, candidates)
                if current_version is None and current_status in {"rate_limited", "unauthorized", "forbidden"}:
                    remote = RemoteProbe(None, current_status)

            if tracked:
                tracked_probe = manifest_probe(tracked)
                remote = tracked_probe
                if tracked_probe.status == "ok" and candidates:
                    available_version, mapped_status = _best_tag_for_digest(reference, tracked_probe.digest, candidates)
                    if available_version is None and mapped_status not in {"ok", "not_found"}:
                        remote = RemoteProbe(tracked_probe.digest, mapped_status)

        elif reference.tag is None:
            all_candidates = version_tags(tags)
            hint = local_version_hint(container, image, tags)
            if hint:
                current_version = hint
            elif all_candidates:
                current_version, current_status = _best_tag_for_digest(reference, local, all_candidates)
                if current_version is None and current_status in {"rate_limited", "unauthorized", "forbidden"}:
                    remote = RemoteProbe(None, current_status)

            compatible = _release_candidates(tags, current_version) if current_version else all_candidates
            if compatible:
                available_version = compatible[0]
                remote = manifest_probe(reference.with_tag(available_version))

        else:
            candidates = _release_candidates(tags, reference.tag)
            if candidates:
                available_version = candidates[0]
                remote = manifest_probe(reference.with_tag(available_version))
            elif tracked:
                remote = manifest_probe(tracked)

    elif tracked:
        remote = manifest_probe(tracked)

    return RegistryState(
        image=image,
        local_digest=local,
        remote_digest=remote.digest,
        tracking_image=tracked,
        remote_status=remote.status,
        current_version=current_version,
        available_version=available_version,
        tags_status=tags_probe.status,
        registry=reference.registry,
        repository=reference.repository,
    )
