#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep .env in sync with .env.template and plan/apply container upgrades.

  upgrade.py [check]   sync .env with the template, query the registries and
                       write .env--upgrading (installed -> latest per package)
  upgrade.py apply     ask y/n per entry of .env--upgrading, confirm once more,
                       then write every accepted value to .env in one pass
  upgrade.py sync      only synchronise the variables of .env with the template
  upgrade.py template  maintainers: bump .env.template from the registries

Every write to .env is preceded by a .env--backup-YYYY-MM-DD copy. Nothing is
ever written when the final answer is "no" or the input is closed.
Exit status of `check`: 0 up to date, 10 upgrades pending, 1 errors.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ behind

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_NAME = ".env--upgrading"
NEW_MARKER = "# NOTE A NEW VAR"
MANUAL_MARK = "# Manual update only"
HEADER_WIDTH = 72
PLACEHOLDER_RE = re.compile(r"PUT_YOUR_|CHANGE_ME")

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

_verbose = False


def log(message: str) -> None:
    if _verbose:
        print(message)


def err(message: str) -> None:
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------
# dotenv parsing (one parser for .env, .env.template and the plan)
# --------------------------------------------------------------------------

ASSIGN_RE = re.compile(r"^(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<raw>.*)$")


def parse_line(line: str) -> tuple[str, str] | None:
    """Return (KEY, raw text after '=') for an assignment line, else None."""
    match = ASSIGN_RE.match(line.strip())
    return (match["key"], match["raw"]) if match else None


def split_raw(raw: str) -> tuple[str, str]:
    """Split raw text into (value, inline comment incl. leading blanks)."""
    raw = raw.rstrip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end != -1:
            return raw[: end + 1], raw[end + 1:]
    match = re.match(r"^(.*?)(\s+#.*)?$", raw)
    return match[1], match[2] or ""


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


class EnvFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        self.lines = self.text.splitlines()
        self.values: dict[str, str] = {}
        self.order: list[str] = []
        for line in self.lines:
            parsed = parse_line(line)
            if parsed is None:
                continue
            key, raw = parsed
            if key not in self.values:
                self.order.append(key)
            self.values[key] = raw

    def value_map(self) -> dict[str, str]:
        return {key: unquote(split_raw(raw)[0]) for key, raw in self.values.items()}


def write_atomic(path: Path, text: str) -> None:
    existing = path.stat() if path.exists() else None
    handle = tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8")
    try:
        with handle:
            handle.write(text)
        if existing is not None:
            os.chmod(handle.name, existing.st_mode & 0o7777)
            if os.geteuid() == 0:
                os.chown(handle.name, existing.st_uid, existing.st_gid)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def backup_env(env_path: Path) -> Path:
    """Copy .env to .env--backup-YYYY-MM-DD; never overwrite an earlier copy."""
    backup = env_path.with_name(f"{env_path.name}--backup-{date.today().isoformat()}")
    if backup.exists():
        backup = backup.with_name(f"{backup.name}-{datetime.now():%H%M%S}")
    shutil.copy2(env_path, backup)
    return backup


# --------------------------------------------------------------------------
# prompts (closed input -> NoInput, callers decide the safe default)
# --------------------------------------------------------------------------

class NoInput(Exception):
    pass


def ask(question: str) -> bool:
    while True:
        try:
            answer = input(f"{question} [y/n]: ").strip().lower()
        except EOFError:
            print()
            raise NoInput from None
        if answer in {"y", "yes", "s", "si", "sí"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def ask_default_no(question: str) -> bool:
    try:
        return ask(question)
    except NoInput:
        return False


# --------------------------------------------------------------------------
# version logic
# --------------------------------------------------------------------------

TAG_RE = re.compile(r"^(?P<prefix>v?)(?P<core>\d+(?:\.\d+)*)(?P<suffix>.*)$")
HASH_SUFFIX_RE = re.compile(r"^-[0-9a-f]{7,}$")
NUM_RUN_RE = re.compile(r"\d+(?:\.\d+)*")


def split_ref(value: str) -> tuple[str, str | None, str | None]:
    """Return (image, tag, digest) for ``repo[:tag][@sha256:...]``."""
    digest = None
    if "@" in value:
        value, digest = value.split("@", 1)
    tag = None
    if ":" in value.rsplit("/", 1)[-1]:
        value, tag = value.rsplit(":", 1)
    return value, tag, digest


def ref_of(component: Component, values: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (tag, digest) declared for the component in a value map."""
    if component.version_var:
        return values.get(component.version_var) or None, None
    _, tag, digest = split_ref(values.get(component.image_var, ""))
    return tag, digest


def new_value(component: Component, old_value: str, new_tag: str) -> str:
    if component.version_var:
        return new_tag
    image, _, digest = split_ref(old_value)
    return old_value if digest else f"{image}:{new_tag}"


def family_regex(tag: str) -> re.Pattern[str] | None:
    match = TAG_RE.match(tag)
    if not match:
        return None
    prefix, core, suffix = match["prefix"], match["core"], match["suffix"]
    if HASH_SUFFIX_RE.match(suffix):
        suffix_re = r"-[0-9a-f]{7,}"
    else:
        suffix_re = r"\d+(?:\.\d+)*".join(re.escape(part) for part in NUM_RUN_RE.split(suffix))
    core_re = r"\d+" + r"\.\d+" * core.count(".")
    return re.compile(rf"^{re.escape(prefix)}({core_re})({suffix_re})$")


def tag_key(tag: str | None):
    match = TAG_RE.match(tag) if tag else None
    if not match:
        return None
    suffix = match["suffix"]
    extra = () if HASH_SUFFIX_RE.match(suffix) else tuple(
        int(part) for run in NUM_RUN_RE.findall(suffix) for part in run.split("."))
    return tuple(int(part) for part in match["core"].split(".")), extra


def compare(a: str | None, b: str | None) -> int | None:
    key_a, key_b = tag_key(a), tag_key(b)
    if key_a is None or key_b is None:
        return None
    return (key_a > key_b) - (key_a < key_b)


def is_major_jump(old: str, new: str) -> bool:
    key_old, key_new = tag_key(old), tag_key(new)
    if key_old is None or key_new is None or key_old[0][0] >= 1000:
        return False  # calendar versions: the year is not a major
    return key_old[0][0] != key_new[0][0]


def newest_tag(current: str, tags: list[str]) -> str:
    pattern = family_regex(current)
    if pattern is None:
        raise ValueError(f"cannot parse current tag {current!r}")
    candidates = [tag for tag in tags if pattern.match(tag)]
    if current not in candidates:
        candidates.append(current)
    return max(candidates, key=tag_key)


# --------------------------------------------------------------------------
# registry access
# --------------------------------------------------------------------------

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


NETWORK_ERRORS = (HTTPError, URLError, RuntimeError, ValueError, json.JSONDecodeError, OSError)


# --------------------------------------------------------------------------
# sync .env <-> .env.template
# --------------------------------------------------------------------------

def change_header(new: list[str], removed: list[str], values: dict[str, str]) -> list[str]:
    if not new and not removed:
        return []
    bar = "#" * HEADER_WIDTH
    lines = [bar, "# ENVIRONMENT CHANGES", bar]
    if new:
        lines += ["", "# NEW VARIABLES"] + [f"#   {key}" for key in new]
    if removed:
        lines += ["", "# REMOVED VARIABLES"] + [f"#   {key}" for key in removed] + [""]
        lines += [f"### REMOVED -- {key}={values[key]}" for key in removed]
    return lines + ["", bar, ""]


def build_synced(env: EnvFile, tpl: EnvFile, retire: bool) -> tuple[str, list[str], list[str]]:
    """Rebuild .env in template order keeping current values (returns text, new, extra)."""
    new = [key for key in tpl.order if key not in env.values]
    extra = [key for key in env.order if key not in tpl.values]
    out = change_header(new, extra if retire else [], env.values)
    for line in tpl.lines:
        parsed = parse_line(line)
        if parsed is None:
            out.append(line)
            continue
        key, raw = parsed
        out.append(f"{key}={env.values[key]}" if key in env.values else f"{key}={raw} {NEW_MARKER}")
    if extra and not retire:
        out += ["", "# LOCAL VARIABLES (not in .env.template)"]
        out += [f"{key}={env.values[key]}" for key in extra]
    return "\n".join(out).rstrip() + "\n", new, extra


def run_sync(env_path: Path, tpl_path: Path) -> bool:
    """Synchronise .env with the template. Returns True when .env was rewritten."""
    env, tpl = EnvFile(env_path), EnvFile(tpl_path)
    new = [key for key in tpl.order if key not in env.values]
    extra = [key for key in env.order if key not in tpl.values]

    if extra:
        err(f"WARNING: {len(extra)} variable(s) in .env are not in .env.template: {', '.join(extra)}")
    retire = False
    if extra:
        retire = ask_default_no(
            "Retire them (kept as '### REMOVED' comments; the stacks stop seeing them)? "
            "n = keep them active")
    if not new and not retire:
        log("sync: .env already has every template variable")
        return False

    text, new, _ = build_synced(env, tpl, retire)
    backup = backup_env(env_path)
    write_atomic(env_path, text)
    print(f"Sync: {len(new)} new variable(s) added, "
          f"{len(extra) if retire else 0} retired. Backup: {backup}")
    needing = [key for key in new if PLACEHOLDER_RE.search(tpl.values[key])]
    if needing:
        err(f"WARNING: new variables that need a real value: {', '.join(needing)}")
    return True


# --------------------------------------------------------------------------
# check: compare installed / template / internet and write the plan
# --------------------------------------------------------------------------

def shown(tag: str | None, digest: str | None) -> str:
    if digest:
        return digest[:19] + "…" if len(digest) > 19 else digest
    return tag or "-"


def analyse(installed: dict[str, str], template: dict[str, str]) -> list[dict]:
    rows = []
    for component in COMPONENTS:
        inst_tag, inst_dig = ref_of(component, installed)
        tpl_tag, tpl_dig = ref_of(component, template)
        row = {"component": component, "installed": shown(inst_tag, inst_dig),
               "template": shown(tpl_tag, tpl_dig), "latest": "-", "action": "OK",
               "target": None, "note": ""}
        rows.append(row)

        if component.manual or inst_dig or tpl_dig:
            row["action"] = "Manual update only"
            continue
        if not inst_tag:
            row["action"] = "ERROR"
            err(f"ERROR [{component.name}] no tag for {component.var}")
            continue

        log(f"[{component.name}] {component.var}: installed {inst_tag}, template {tpl_tag}")
        log(f"[{component.name}] GET {component.url}")
        try:
            tags = fetch_tags(component.url)
            latest = newest_tag(inst_tag, tags)
        except NETWORK_ERRORS as error:
            row["action"] = "ERROR"
            err(f"ERROR [{component.name}] {error}")
            continue
        log(f"[{component.name}] {len(tags)} tags received; newest {latest}")

        if tpl_tag and compare(tpl_tag, latest) == 1:
            latest = tpl_tag
        row["latest"] = latest

        if tpl_tag and compare(tpl_tag, inst_tag) == -1:
            print(f"\n{component.name}: .env.template pins {tpl_tag}, older than the "
                  f"installed {inst_tag}.")
            if ask_default_no("Use the template version in the plan (downgrade)? "
                              "n = keep the installed one"):
                row["target"], row["action"] = tpl_tag, "DOWNGRADE (template)"
                continue
            row["note"] = "template behind"

        if compare(latest, inst_tag) == 1:
            row["target"] = latest
            row["action"] = "UPGRADE (MAJOR)" if is_major_jump(inst_tag, latest) else "UPGRADE"
        elif row["note"]:
            row["action"] = "OK (template behind)"
    return rows


def print_table(rows: list[dict]) -> None:
    table = [("COMPONENT", "VARIABLE", "INSTALLED", "TEMPLATE", "LATEST", "ACTION")]
    table += [(r["component"].name, r["component"].var, r["installed"], r["template"],
               r["latest"], r["action"]) for r in rows]
    widths = [max(len(row[col]) for row in table) for col in range(6)]
    for index, row in enumerate(table):
        print("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)).rstrip())
        if index == 0:
            print("  ".join("-" * width for width in widths))


def write_plan(plan_path: Path, rows: list[dict], installed: dict[str, str],
               env_path: Path, has_env: bool, template_sha: str) -> int:
    entries = [row for row in rows if row["target"]]
    lines = [
        f"# upgrade.py plan - generated {datetime.now():%Y-%m-%dT%H:%M:%S}",
        f"# env: {env_path if has_env else 'NONE - .env.template used as installed baseline'}",
        f"# template-sha256: {template_sha}",
        "# Delete or comment out a line to skip it, then run: tools/upgrade.py apply",
        "# MAJOR = first version number changes: databases may need a data migration.",
        "",
    ]
    for row in entries:
        component = row["component"]
        old = installed.get(component.var, "")
        value = new_value(component, old, row["target"])
        flags = f" | {row['action']}" if row["action"] != "UPGRADE" else ""
        lines.append(f"{component.var}={value}   # installed: {old} | template: "
                     f"{row['template']} | latest: {row['latest']}{flags}")
    for row in rows:
        if row["action"] == "Manual update only":
            lines.append(f"# MANUAL {row['component'].var}: digest-pinned, update by hand")
    write_atomic(plan_path, "\n".join(lines) + "\n")
    return len(entries)


def cmd_check(base: Path, no_sync: bool) -> int:
    env_path, tpl_path, plan_path = base / ".env", base / ".env.template", base / PLAN_NAME
    if not tpl_path.is_file():
        err(f"ERROR: not found: {tpl_path}")
        return 1
    has_env = env_path.is_file()
    if not has_env:
        print(f"NOTE: no {env_path.name} in {base}; using .env.template as the installed baseline.")
    elif not no_sync:
        run_sync(env_path, tpl_path)

    template = EnvFile(tpl_path)
    installed = template.value_map()
    if has_env:
        installed.update(EnvFile(env_path).value_map())
    rows = analyse(installed, template.value_map())
    print()
    print_table(rows)

    errors = any(row["action"] == "ERROR" for row in rows)
    template_sha = hashlib.sha256(tpl_path.read_bytes()).hexdigest()
    count = write_plan(plan_path, rows, installed, env_path, has_env, template_sha) \
        if any(row["target"] for row in rows) else 0
    if count:
        print(f"\n{count} upgrade(s) planned in {plan_path}. Review it, then run: "
              f"tools/upgrade.py apply")
    else:
        plan_path.unlink(missing_ok=True)
        print("\nNothing to upgrade.")
    if errors:
        return 1
    return 10 if count else 0


# --------------------------------------------------------------------------
# apply: y/n per entry, one confirmation, one write
# --------------------------------------------------------------------------

def cmd_apply(base: Path) -> int:
    env_path, tpl_path, plan_path = base / ".env", base / ".env.template", base / PLAN_NAME
    for path in (env_path, plan_path):
        if not path.is_file():
            err(f"ERROR: not found: {path}" + ("  (run: tools/upgrade.py check)"
                                                  if path == plan_path else ""))
            return 1
    plan_text = plan_path.read_text(encoding="utf-8")
    recorded = re.search(r"^# template-sha256: (\w+)", plan_text, re.M)
    if tpl_path.is_file() and recorded and \
            recorded[1] != hashlib.sha256(tpl_path.read_bytes()).hexdigest():
        err("ERROR: .env.template changed after this plan was generated; "
            "run: tools/upgrade.py check")
        return 1

    env = EnvFile(env_path)
    entries = []
    for line in plan_text.splitlines():
        parsed = parse_line(line)
        if parsed is None:
            continue
        key, raw = parsed
        value, tail = split_raw(raw)
        old = re.search(r"installed:\s*(\S*)", tail)
        entries.append({"key": key, "value": unquote(value), "old": old[1] if old else "",
                        "tail": tail.strip().lstrip("#").strip()})

    valid = []
    for entry in entries:
        current = unquote(split_raw(env.values[entry["key"]])[0]) if entry["key"] in env.values else None
        if current is None:
            err(f"SKIP {entry['key']}: not present in .env")
        elif current != entry["old"]:
            err(f"SKIP {entry['key']}: .env changed since the plan ({current} != {entry['old']}); "
                f"run check again")
        else:
            valid.append(entry)
    if not valid:
        print("Nothing to apply.")
        return 0

    print(f"{len(valid)} upgrade(s) in {plan_path.name}\n")
    selected = []
    try:
        for entry in valid:
            major = " [MAJOR]" if "MAJOR" in entry["tail"] else ""
            if ask(f"{entry['key']}: {entry['old']} -> {entry['value']}{major}. Inject?"):
                selected.append(entry)
        if not selected:
            print("\nNothing selected. .env unchanged.")
            return 0
        print(f"\nChanges to inject into {env_path}")
        for entry in selected:
            print(f"  {entry['key']}: {entry['old']} -> {entry['value']}")
        if not ask("\nAre you happy with these changes?"):
            print("Cancelled. .env unchanged.")
            return 0
    except (KeyboardInterrupt, NoInput):
        print("\nAborted. .env unchanged.")
        return 1

    wanted = {entry["key"]: entry["value"] for entry in selected}
    out = []
    for line in env.text.split("\n"):
        parsed = parse_line(line)
        if parsed and parsed[0] in wanted:
            _, tail = split_raw(parsed[1])
            line = f"{parsed[0]}={wanted[parsed[0]]}{tail}"
        out.append(line)
    backup = backup_env(env_path)
    print(f"\nBackup: {backup}")
    write_atomic(env_path, "\n".join(out))
    plan_path.unlink(missing_ok=True)
    print(f"Done: {len(selected)} variable(s) updated in {env_path}.")
    return 0


# --------------------------------------------------------------------------
# template: maintainers bump .env.template from the registries
# --------------------------------------------------------------------------

def cmd_template(base: Path) -> int:
    tpl_path = base / ".env.template"
    if not tpl_path.is_file():
        err(f"ERROR: not found: {tpl_path}")
        return 1
    template = EnvFile(tpl_path)
    values = template.value_map()
    updates: dict[str, tuple[Component, str]] = {}
    manual_vars: set[str] = set()
    failures = 0
    for component in COMPONENTS:
        tag, digest = ref_of(component, values)
        if component.manual or digest:
            log(f"[{component.name}] {component.var}: Manual update only (digest-pinned)")
            manual_vars.add(component.var)
            continue
        if not tag:
            err(f"ERROR [{component.name}] no tag for {component.var} in {tpl_path}")
            failures += 1
            continue
        log(f"[{component.name}] {component.var}: current {tag}")
        log(f"[{component.name}] GET {component.url}")
        try:
            tags = fetch_tags(component.url)
            newest = newest_tag(tag, tags)
        except NETWORK_ERRORS as error:
            err(f"ERROR [{component.name}] {error}")
            failures += 1
            continue
        log(f"[{component.name}] {len(tags)} tags received; " +
            ("up to date" if newest == tag else f"{tag} -> {newest}"))
        if newest != tag:
            updates[component.var] = (component, newest)

    out: list[str] = []
    changes: list[str] = []
    for line in template.text.split("\n"):
        parsed = parse_line(line)
        key = parsed[0] if parsed else None
        if key in manual_vars and not (out and out[-1].strip() == MANUAL_MARK):
            out.append(MANUAL_MARK)
            changes.append(f"{key}: marked '{MANUAL_MARK}'")
        if parsed and key in updates:
            component, newest = updates[key]
            value, tail = split_raw(parsed[1])
            replaced = new_value(component, unquote(value), newest)
            if tail.strip():
                out.append(tail.strip())
            out.append(f"{key}={replaced}")
            changes.append(f"{key}: {unquote(value)} -> {replaced}")
        else:
            out.append(line)
    if changes:
        write_atomic(tpl_path, "\n".join(out))
        for change in changes:
            log(f"updated {tpl_path.name}: {change}")
    else:
        log(f"{tpl_path.name} unchanged")
    return 1 if failures else 0


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global _verbose
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", type=Path, default=REPO_ROOT,
                        help="directory with .env and .env.template (default: repository root)")
    common.add_argument("-v", "--verbose", action="store_true", help="show the whole process")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", parents=[common], help="sync, query registries, write plan")
    check.add_argument("--no-sync", action="store_true", help="do not touch .env")
    sub.add_parser("apply", parents=[common], help="inject planned upgrades into .env")
    sub.add_parser("sync", parents=[common], help="only sync .env with .env.template")
    sub.add_parser("template", parents=[common], help="bump .env.template (maintainers)")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"check", "apply", "sync", "template", "-h", "--help"}:
        argv.insert(0, "check")
    args = parser.parse_args(argv)
    _verbose = args.verbose
    base = args.dir.expanduser().resolve()

    if args.command == "check":
        return cmd_check(base, args.no_sync)
    if args.command == "apply":
        return cmd_apply(base)
    if args.command == "template":
        return cmd_template(base)
    env_path, tpl_path = base / ".env", base / ".env.template"
    for path in (env_path, tpl_path):
        if not path.is_file():
            err(f"ERROR: not found: {path}")
            return 1
    if not run_sync(env_path, tpl_path):
        print("Already in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
