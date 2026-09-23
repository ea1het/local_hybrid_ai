#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Update the container versions in .env.template from the upstream registries.

For every component in COMPONENTS the registry tag list is fetched from its
exact URL, the highest numeric tag of the *same family* as the current one is
selected (never ``latest``, never a digest) and the value is rewritten in the
repository ``.env.template``. Silent unless ``-v`` is given; errors always go
to stderr and produce a non-zero exit status.

Tag family = same ``v`` prefix, same number of dotted segments and the same
suffix text (digit runs in the suffix are free, so ``-alpine3.24`` may become
``-alpine3.25``; a commit-hash suffix matches any hash). Major jumps are taken.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / ".env.template"

# Exact registry tag-list URL of each container (OCI distribution API v2).
URL_HAPROXY = "https://registry-1.docker.io/v2/library/haproxy/tags/list"
URL_SEARXNG = "https://registry-1.docker.io/v2/searxng/searxng/tags/list"
URL_FIRECRAWL = "https://ghcr.io/v2/firecrawl/firecrawl/tags/list"
URL_FIRECRAWL_PLAYWRIGHT = "https://ghcr.io/v2/firecrawl/playwright-service/tags/list"
URL_FIRECRAWL_POSTGRES = "https://ghcr.io/v2/firecrawl/nuq-postgres/tags/list"
URL_REDIS = "https://registry-1.docker.io/v2/library/redis/tags/list"
URL_RABBITMQ = "https://registry-1.docker.io/v2/library/rabbitmq/tags/list"
URL_LITELLM = "https://ghcr.io/v2/berriai/litellm-database/tags/list"
URL_POSTGRES = "https://registry-1.docker.io/v2/library/postgres/tags/list"
URL_GITEA = "https://docker.gitea.com/v2/gitea/tags/list"
URL_DOCKHAND = "https://registry-1.docker.io/v2/fnsys/dockhand/tags/list"
URL_HERMES = "https://registry-1.docker.io/v2/nousresearch/hermes-agent/tags/list"
URL_OPENWEBUI = "https://ghcr.io/v2/open-webui/open-webui/tags/list"

MANUAL_MARK = "# Manual update only"


class Component:
    """One container. ``version_var`` is None when the tag lives in ``image_var``."""

    def __init__(self, name: str, image_var: str, version_var: str | None, url: str,
                 manual: bool = False) -> None:
        self.name = name
        self.image_var = image_var
        self.version_var = version_var
        self.url = url
        self.manual = manual

    @property
    def var(self) -> str:
        return self.version_var or self.image_var


COMPONENTS = [
    Component("haproxy", "HAPROXY_IMAGE", "HAPROXY_VERSION", URL_HAPROXY),
    Component("searxng", "SEARXNG_IMAGE", None, URL_SEARXNG),
    Component("firecrawl", "FIRECRAWL_IMAGE", None, URL_FIRECRAWL),
    Component("firecrawl-playwright", "FIRECRAWL_PLAYWRIGHT_IMAGE", None,
              URL_FIRECRAWL_PLAYWRIGHT, manual=True),
    Component("firecrawl-postgres", "FIRECRAWL_POSTGRES_IMAGE", None,
              URL_FIRECRAWL_POSTGRES, manual=True),
    Component("redis", "FIRECRAWL_REDIS_IMAGE", "FIRECRAWL_REDIS_VERSION", URL_REDIS),
    Component("rabbitmq", "FIRECRAWL_RABBITMQ_IMAGE", "FIRECRAWL_RABBITMQ_VERSION", URL_RABBITMQ),
    Component("litellm", "LITELLM_IMAGE", "LITELLM_VERSION", URL_LITELLM),
    Component("litellm-postgres", "LITELLM_POSTGRES_IMAGE", None, URL_POSTGRES),
    Component("gitea", "GITEA_IMAGE", None, URL_GITEA),
    Component("dockhand", "DOCKHAND_REPOSITORY", "DOCKHAND_VERSION", URL_DOCKHAND),
    Component("hermes", "HERMES_IMAGE", "HERMES_VERSION", URL_HERMES),
    Component("open-webui", "OPENWEBUI_IMAGE", "OPENWEBUI_VERSION", URL_OPENWEBUI),
]

LINE_RE = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<val>[^\s#]*)(?P<tail>\s+#.*)?$")
TAG_RE = re.compile(r"^(?P<prefix>v?)(?P<core>\d+(?:\.\d+)*)(?P<suffix>.*)$")
HASH_SUFFIX_RE = re.compile(r"^-[0-9a-f]{7,}$")
NUM_RUN_RE = re.compile(r"\d+(?:\.\d+)*")

_verbose = False


def log(message: str) -> None:
    if _verbose:
        print(message)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        match = LINE_RE.match(raw)
        if match:
            values[match["key"]] = match["val"]
    return values


def split_ref(value: str) -> tuple[str, str | None, str | None]:
    """Return (image, tag, digest) for ``repo[:tag][@sha256:...]``."""
    digest = None
    if "@" in value:
        value, digest = value.split("@", 1)
    tag = None
    last = value.rsplit("/", 1)[-1]
    if ":" in last:
        value, tag = value.rsplit(":", 1)
    return value, tag, digest


def current_tag(component: Component, env: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (tag, digest) currently declared for the component."""
    if component.version_var:
        return env.get(component.version_var), None
    _, tag, digest = split_ref(env.get(component.image_var, ""))
    return tag, digest


def family_regex(tag: str) -> re.Pattern[str] | None:
    match = TAG_RE.match(tag)
    if not match:
        return None
    prefix, core, suffix = match["prefix"], match["core"], match["suffix"]
    segments = core.count(".") + 1
    if HASH_SUFFIX_RE.match(suffix):
        suffix_re = r"-[0-9a-f]{7,}"
    else:
        parts = NUM_RUN_RE.split(suffix)
        suffix_re = r"\d+(?:\.\d+)*".join(re.escape(part) for part in parts)
    core_re = r"\d+" + r"\.\d+" * (segments - 1)
    return re.compile(rf"^{re.escape(prefix)}({core_re})({suffix_re})$")


def sort_key(tag: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = TAG_RE.match(tag)
    assert match
    core = tuple(int(part) for part in match["core"].split("."))
    suffix = match["suffix"]
    extra = () if HASH_SUFFIX_RE.match(suffix) else tuple(
        int(part) for run in NUM_RUN_RE.findall(suffix) for part in run.split("."))
    return core, extra


def newest_tag(current: str, tags: Iterable[str]) -> str:
    pattern = family_regex(current)
    if pattern is None:
        raise ValueError(f"cannot parse current tag {current!r}")
    candidates = [tag for tag in tags if pattern.match(tag)]
    if current not in candidates:
        candidates.append(current)
    return max(candidates, key=sort_key)


def _bearer_token(challenge: str) -> str:
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.get("realm")
    if not realm:
        raise RuntimeError(f"unsupported auth challenge: {challenge!r}")
    query = "&".join(f"{key}={fields[key]}" for key in ("service", "scope") if key in fields)
    with urlopen(f"{realm}?{query}" if query else realm, timeout=30) as response:
        payload = json.load(response)
    token = payload.get("token") or payload.get("access_token")
    if not token:
        raise RuntimeError("registry token endpoint returned no token")
    return token


def fetch_tags(url: str) -> list[str]:
    tags: list[str] = []
    next_url: str | None = f"{url}{'&' if '?' in url else '?'}n=1000"
    token: str | None = None
    while next_url:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urlopen(Request(next_url, headers=headers), timeout=60) as response:
                payload = json.load(response)
                link = response.headers.get("Link", "")
        except HTTPError as error:
            if error.code == 401 and token is None:
                token = _bearer_token(error.headers.get("WWW-Authenticate", ""))
                continue
            raise
        tags.extend(payload.get("tags") or [])
        found = re.search(r'<([^>]+)>;\s*rel="next"', link)
        next_url = urljoin(next_url, found[1]) if found else None
    return tags


def rewrite_value(component: Component, old_value: str, new_tag: str) -> str:
    if component.version_var:
        return new_tag
    image, _, digest = split_ref(old_value)
    return f"{image}:{new_tag}" if not digest else old_value


def apply_updates(lines: list[str], updates: dict[str, tuple[Component, str]],
                  manual_vars: set[str]) -> tuple[list[str], list[str]]:
    """Return (new_lines, human-readable change list)."""
    out: list[str] = []
    changes: list[str] = []
    for index, raw in enumerate(lines):
        match = LINE_RE.match(raw)
        key = match["key"] if match else None
        if key in manual_vars and not (out and out[-1].strip() == MANUAL_MARK):
            out.append(MANUAL_MARK)
            changes.append(f"{key}: marked '{MANUAL_MARK}'")
        if key in updates:
            component, new_tag = updates[key]
            new_value = rewrite_value(component, match["val"], new_tag)
            tail = (match["tail"] or "").strip()
            if tail:
                out.append(tail)
            out.append(f"{key}={new_value}")
            changes.append(f"{key}: {match['val']} -> {new_value}")
        else:
            out.append(raw)
    return out, changes


def main(argv: list[str] | None = None) -> int:
    global _verbose
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="show the whole process")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                        help="template to update (default: repository .env.template)")
    args = parser.parse_args(argv)
    _verbose = args.verbose

    template: Path = args.template
    text = template.read_text()
    lines = text.split("\n")
    env = read_env(template)

    updates: dict[str, tuple[Component, str]] = {}
    manual_vars: set[str] = set()
    failures = 0

    for component in COMPONENTS:
        tag, digest = current_tag(component, env)
        if component.manual or digest:
            log(f"[{component.name}] {component.var}: Manual update only (digest-pinned)")
            manual_vars.add(component.var)
            continue
        if not tag:
            print(f"ERROR [{component.name}] no tag for {component.var} in {template}",
                  file=sys.stderr)
            failures += 1
            continue
        log(f"[{component.name}] {component.var}: current {tag}")
        log(f"[{component.name}] GET {component.url}")
        try:
            tags = fetch_tags(component.url)
            log(f"[{component.name}] {len(tags)} tags received")
            new_tag = newest_tag(tag, tags)
        except (HTTPError, URLError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            print(f"ERROR [{component.name}] {error}", file=sys.stderr)
            failures += 1
            continue
        if new_tag == tag:
            log(f"[{component.name}] up to date ({tag})")
        else:
            log(f"[{component.name}] {tag} -> {new_tag}")
            updates[component.var] = (component, new_tag)

    new_lines, changes = apply_updates(lines, updates, manual_vars)
    if changes:
        handle = tempfile.NamedTemporaryFile("w", dir=template.parent, delete=False)
        with handle:
            handle.write("\n".join(new_lines))
        Path(handle.name).chmod(template.stat().st_mode & 0o7777)
        Path(handle.name).replace(template)
        for change in changes:
            log(f"updated {template.name}: {change}")
    else:
        log(f"{template.name} unchanged")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
