from __future__ import annotations

import json
import urllib.error
import urllib.request


class VersionSourceError(RuntimeError):
    pass


def _github_latest(repo: str) -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "local-ai-upgrade-check/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "unknown"
    tag = data.get("tag_name")
    return str(tag) if tag else "unknown"


def _transform(version: str, source: dict) -> str:
    if version == "unknown":
        return version
    if source.get("strip_prefix") and version.startswith(str(source["strip_prefix"])):
        version = version[len(str(source["strip_prefix"])):]
    suffix = source.get("suffix")
    if suffix:
        version += str(suffix)
    return version


def available_version(component: dict, *, online: bool) -> str:
    """Return a candidate version only through an explicitly declared adapter."""
    if not online:
        return "unchecked"

    source = component.get("version_source")
    if not source:
        return "n/a"
    if not isinstance(source, dict):
        raise VersionSourceError("version_source must be an object")

    source_type = source.get("type")
    if source_type == "github_release":
        repo = source.get("repo")
        if not isinstance(repo, str) or not repo:
            raise VersionSourceError("github_release requires repo")
        return _transform(_github_latest(repo), source)

    raise VersionSourceError(f"unsupported version source: {source_type}")
