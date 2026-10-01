# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Remove stale gateway overrides from Hermes' ephemeral runtime environment.

Compose supplies the LiteLLM credentials from the protected root .env. Hermes
may also write a private data/.env while running, and its dotenv loader can
override container variables with that file on the next start. Before Compose
starts Hermes, remove only the gateway variables from that runtime file and
retain all unrelated application settings. The original is privately backed
up when a change is needed; no credential value is logged.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import os
import re
import stat
import tempfile
import time
from pathlib import Path


GATEWAY_KEYS = frozenset({"LITELLM_API_KEY", "LITELLM_MCP_API_KEY", "LITELLM_BASE_URL",
                          "LITELLM_MCP_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL"})
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
MANAGED_CONFIG_LINES = (
    (re.compile(r"(?m)^(  base_url: ).*$"), r"\g<1>${LITELLM_BASE_URL}"),
    (re.compile(r"(?m)^(  api_key: ).*$"), r"\g<1>${LITELLM_API_KEY}"),
    (re.compile(r"(?m)^(    url: ).*$"), r"\g<1>${LITELLM_MCP_URL}"),
    (re.compile(r"(?m)^(      Authorization: ).*$"), r'\g<1>"Bearer ${LITELLM_MCP_API_KEY}"'),
)


class RuntimeEnvironmentError(RuntimeError):
    """Reject an unsafe Hermes runtime file."""


def _filtered(path: Path, managed_keys: frozenset[str]) -> tuple[os.stat_result, bytes] | None:
    """Return metadata and content without central-environment overrides."""
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeEnvironmentError(f"unsafe Hermes runtime environment: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeEnvironmentError(f"unsafe Hermes runtime environment: {path}")
    lines = path.read_bytes().splitlines(keepends=True)
    kept = []
    removed = False
    for line in lines:
        match = ASSIGNMENT.match(line.decode("utf-8"))
        if match and match.group(1) in GATEWAY_KEYS | managed_keys:
            removed = True
        else:
            kept.append(line)
    return (metadata, b"".join(kept)) if removed else None


def needs_update(path: Path, managed_keys: frozenset[str] = frozenset()) -> bool:
    """Report whether Hermes shadows any central environment variable."""
    return _filtered(path, managed_keys) is not None


def reconcile(path: Path, managed_keys: frozenset[str] = frozenset()) -> bool:
    """Back up and atomically remove central overrides while stopped."""
    filtered = _filtered(path, managed_keys)
    if filtered is None:
        return False
    metadata, payload = filtered
    backup = path.with_name(f"{path.name}-backup-{time.strftime('%y%m%d-%H%M%S')}")
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(path.read_bytes())
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".hermes-env-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def _managed_config(path: Path) -> tuple[os.stat_result, str] | None:
    """Render only the four gateway settings back to environment references."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeEnvironmentError(f"unsafe Hermes managed configuration: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeEnvironmentError(f"unsafe Hermes managed configuration: {path}")
    original = path.read_text()
    rendered = original
    for pattern, replacement in MANAGED_CONFIG_LINES:
        rendered, count = pattern.subn(replacement, rendered)
        if count != 1:
            raise RuntimeEnvironmentError(f"unexpected Hermes gateway configuration: {path}")
    return (metadata, rendered) if rendered != original else None


def config_needs_update(path: Path) -> bool:
    """Check whether Hermes stored a literal gateway secret or endpoint."""
    return _managed_config(path) is not None


def reconcile_config(path: Path) -> bool:
    """Back up and restore environment references in the managed config."""
    managed = _managed_config(path)
    if managed is None:
        return False
    metadata, rendered = managed
    backup = path.with_name(f"{path.name}-backup-{time.strftime('%y%m%d-%H%M%S')}")
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(path.read_bytes())
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".hermes-config-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w") as output:
            os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(output.fileno(), 0o640)
            output.write(rendered)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True
