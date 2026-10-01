#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Create or complete the protected deployment environment without rotating secrets.

The template supplies non-secret defaults. Locally controlled credentials are
generated only when absent or still placeholders; external credentials remain
operator-supplied. PostgreSQL passwords are generated in .env, not copied to
runtime files. Each modification of an existing .env first creates a private
timestamped backup, then replaces the file atomically. No secret value is
printed or written to Git-tracked paths. Importing this module performs no
filesystem or credential operation.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import base64
import fcntl
import hashlib
import hmac
import os
import re
import secrets
import stat
import tempfile
from datetime import datetime
from pathlib import Path

ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
PLACEHOLDER = re.compile(r"^PUT_YOUR_[A-Z0-9_]+_HERE$")
GENERATED = (
    "SEARXNG_SECRET", "REDIS_PASSWORD", "RABBITMQ_PASSWORD", "FIRECRAWL_DB_PASSWORD",
    "FIRECRAWL_POSTGRES_ADMIN_PASSWORD", "LITELLM_MASTER_KEY", "LITELLM_SALT_KEY",
    "UI_PASSWORD", "LITELLM_DB_PASSWORD", "LITELLM_POSTGRES_ADMIN_PASSWORD",
    "GITEA_INTERNAL_TOKEN", "GITEA_JWT_SECRET", "GITEA_ADMIN_PASSWORD",
    "HERMES_DASHBOARD_BASIC_AUTH_SECRET", "API_SERVER_KEY", "OPENWEBUI_SECRET_KEY",
)
STATE_SERVICES = {
    "SEARXNG_SECRET": "service_-_searxng",
    "REDIS_PASSWORD": "service_-_firecrawl-redis",
    "RABBITMQ_PASSWORD": "service_-_firecrawl-rabbitmq",
    "FIRECRAWL_DB_PASSWORD": "service_-_firecrawl-postgres",
    "FIRECRAWL_POSTGRES_ADMIN_PASSWORD": "service_-_firecrawl-postgres",
    "LITELLM_MASTER_KEY": "service_-_litellm-postgres",
    "LITELLM_SALT_KEY": "service_-_litellm-postgres",
    "UI_PASSWORD": "service_-_litellm-postgres",
    "LITELLM_DB_PASSWORD": "service_-_litellm-postgres",
    "LITELLM_POSTGRES_ADMIN_PASSWORD": "service_-_litellm-postgres",
    "GITEA_INTERNAL_TOKEN": "service_-_gitea",
    "GITEA_JWT_SECRET": "service_-_gitea",
    "GITEA_ADMIN_PASSWORD": "service_-_gitea",
    "HERMES_DASHBOARD_BASIC_AUTH_SECRET": "service_-_hermes",
    "API_SERVER_KEY": "service_-_hermes",
    "OPENWEBUI_SECRET_KEY": "service_-_open-webui",
}


class BootstrapError(RuntimeError):
    """Reject an unsafe or ambiguous environment change."""


def root_owned(metadata: os.stat_result) -> bool:
    """Require root as both file owner and group."""
    return metadata.st_uid == 0 and metadata.st_gid == 0


def private_owner(descriptor: int) -> None:
    """Ensure newly created secret files belong only to root."""
    os.fchown(descriptor, 0, 0)
    os.fchmod(descriptor, 0o600)


def assignments(text: str) -> dict[str, str]:
    """Read unique plain assignments without evaluating shell content."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            continue
        key, raw = match.groups()
        if key in values:
            raise BootstrapError(f"duplicate environment variable: {key}")
        values[key] = raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'" else raw
    return values


def missing(value: str | None) -> bool:
    """Recognize only an absent, blank, or template placeholder value."""
    return value is None or not value or bool(PLACEHOLDER.fullmatch(value))


def protected_text(path: Path) -> str:
    """Read a root-owned 0600 regular file without following symlinks."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not root_owned(metadata) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BootstrapError(f"expected a root-owned 0600 regular file: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def occupied_runtime(base: Path, service: str) -> bool:
    """Recognize existing application data without following runtime symlinks."""
    root = base / service
    data = root / "data"
    if root.is_symlink() or data.is_symlink():
        raise BootstrapError(f"unsafe runtime directory: {data}")
    return data.is_dir() and any(data.iterdir())


def dashboard_hash(password: str) -> str:
    """Use Hermes' documented scrypt hash format for dashboard login."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(derived).decode()


def verify_dashboard_password(password: str, encoded: str) -> None:
    """Reject disagreement when both retrievable password and managed hash exist."""
    if not encoded.startswith("scrypt$"):
        return
    try:
        scheme, count, block, parallel, salt, digest = encoded.split("$")
        if (scheme, count, block, parallel) != ("scrypt", "16384", "8", "1"):
            raise ValueError("unexpected scrypt parameters")
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True),
                                n=16384, r=8, p=1, dklen=len(expected))
    except (ValueError, MemoryError) as error:
        raise BootstrapError("invalid Hermes dashboard password hash") from error
    if not hmac.compare_digest(actual, expected):
        raise BootstrapError("Hermes dashboard password does not match its existing hash")


def render(text: str, replacements: dict[str, str]) -> str:
    """Replace only selected assignments, preserving every other line."""
    def assignment(key: str) -> str:
        """Quote the one generated value containing shell metacharacters."""
        value = replacements[key]
        return f"{key}='{value}'" if key == "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH" else f"{key}={value}"

    output: list[str] = []
    found: set[str] = set()
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match and match[1] in replacements:
            key = match[1]
            output.append(assignment(key))
            found.add(key)
        else:
            output.append(line)
    for key in replacements:
        if key not in found:
            output.append(assignment(key))
    return "\n".join(output) + "\n"


def write_private(path: Path, content: str) -> None:
    """Create a private file exclusively and synchronize its contents."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        private_owner(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_path(path: Path) -> Path:
    """Build the required timestamped environment backup name."""
    return path.with_name(f".env-backup-{datetime.now():%y%m%d-%H%M%S}")


def save(path: Path, old: str | None, new: str, backup: Path | None = None) -> Path | None:
    """Back up existing content and atomically replace the protected .env."""
    if old is not None and backup is None:
        backup = backup_path(path)
        write_private(backup, old)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.bootstrap.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        private_owner(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(new)
            handle.flush()
            os.fsync(handle.fileno())
        if old is None and (path.exists() or path.is_symlink()):
            raise BootstrapError(".env appeared during bootstrap; update refused")
        if old is not None and protected_text(path) != old:
            raise BootstrapError(".env changed during bootstrap; backup kept, update refused")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def bootstrap(root: Path) -> tuple[list[str], list[str], Path | None, bool]:
    """Generate local secrets in .env and report external credential gaps."""
    if os.geteuid() != 0:
        raise BootstrapError("run as root to protect the operational .env")
    template_path, env_path = root / ".env.template", root / ".env"
    if template_path.is_symlink() or not template_path.is_file():
        raise BootstrapError(f"missing regular template: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    template_values = assignments(template)
    lock_path = root / ".env-bootstrap.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not root_owned(metadata) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BootstrapError(f"unsafe bootstrap lock: {lock_path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        old = protected_text(env_path) if env_path.exists() or env_path.is_symlink() else None
        text = old if old is not None else template
        values = assignments(text)
        replacements: dict[str, str] = {}
        base = values.get("BASE_PATH") or template_values.get("BASE_PATH", "")
        if not base.startswith("/") or base == "/":
            raise BootstrapError("BASE_PATH must be an absolute service directory")
        base_path = Path(base)
        if base_path.is_symlink():
            raise BootstrapError(f"unsafe runtime root: {base_path}")
        hermes_service = values.get("HERMES_SERVICE") or template_values.get("HERMES_SERVICE", "")
        if not re.fullmatch(r"service_-_[A-Za-z0-9._-]+", hermes_service):
            raise BootstrapError("HERMES_SERVICE must be a service directory name")
        for key in GENERATED:
            if key not in template_values:
                raise BootstrapError(f"template missing generated secret: {key}")
            if missing(values.get(key)):
                service = hermes_service if key in {"HERMES_DASHBOARD_BASIC_AUTH_SECRET", "API_SERVER_KEY"} else STATE_SERVICES[key]
                if occupied_runtime(base_path, service):
                    raise BootstrapError(f"{key} is missing beside existing service data; recover its original value")
                replacements[key] = ("sk-" if key == "LITELLM_MASTER_KEY" else "") + secrets.token_hex(32)

        password_key = "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"
        hash_key = "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"
        if missing(values.get(hash_key)):
            if occupied_runtime(base_path, hermes_service):
                raise BootstrapError("Hermes dashboard hash is missing beside existing service data")
            password = values.get(password_key)
            if missing(password):
                password = secrets.token_hex(32)
                replacements[password_key] = password
            replacements[hash_key] = dashboard_hash(password)
        elif not missing(values.get(password_key)):
            verify_dashboard_password(values[password_key], values[hash_key])

        updated = render(text, replacements) if replacements else text
        backup = save(env_path, old, updated) if old is None or updated != old else None
        pending = [key for key in ("OMLX_API_KEY", "TELEGRAM_BOT_TOKEN", "BUZZ_PRIVATE_KEY", "BUZZ_RELAY_URL",
                                   "LITELLM_API_KEY", "LITELLM_MCP_API_KEY", "OPENWEBUI_LITELLM_API_KEY")
                   if missing(values.get(key))]
        return list(replacements), pending, backup, old is None or updated != old
    finally:
        os.close(descriptor)
