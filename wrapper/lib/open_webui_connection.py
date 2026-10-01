# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep Open WebUI's persisted LiteLLM connection aligned with the root .env.

Open WebUI v0.11.4 stores each persistent setting in a separate SQLite config
row. Its saved OpenAI-compatible connection key otherwise overrides Compose's
OPENAI_API_KEY on subsequent starts. This helper updates only the key for the
configured LiteLLM endpoint while the application is stopped. Other provider
connections, GUI settings, users, and chats are left untouched. Unexpected
database layouts fail closed rather than resetting all persistent settings.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path


class ConnectionError(RuntimeError):
    """Report unsafe or unrecognized persistent connection state."""


def _read_connection(database: Path) -> tuple[list[str], list[str]] | None:
    """Read only the two Open WebUI connection rows, if initialized."""
    if database.is_symlink() or not database.is_file():
        raise ConnectionError(f"unsafe Open WebUI database: {database}")
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='config'").fetchone()
        if not table:
            raise ConnectionError("Open WebUI config table is missing")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(config)")}
        if not {"key", "value", "updated_at"}.issubset(columns):
            raise ConnectionError("unexpected Open WebUI config schema")
        rows = dict(connection.execute(
            "SELECT key, value FROM config WHERE key IN ('openai.api_base_urls', 'openai.api_keys')"
        ))
    if not rows:
        return None
    if set(rows) != {"openai.api_base_urls", "openai.api_keys"}:
        raise ConnectionError("incomplete Open WebUI connection configuration")
    try:
        urls = json.loads(rows["openai.api_base_urls"])
        keys = json.loads(rows["openai.api_keys"])
    except (TypeError, ValueError) as error:
        raise ConnectionError("invalid Open WebUI connection configuration") from error
    if (not isinstance(urls, list) or not isinstance(keys, list)
            or not all(isinstance(url, str) for url in urls)
            or not all(isinstance(key, str) for key in keys)
            or len(urls) != len(keys)):
        raise ConnectionError("unexpected Open WebUI connection list")
    return urls, keys


def needs_update(database: Path, endpoint: str, key: str) -> bool:
    """Check whether the persisted key for the exact LiteLLM endpoint differs."""
    if database.is_symlink():
        raise ConnectionError(f"unsafe Open WebUI database: {database}")
    if not database.exists():
        return False
    connection = _read_connection(database)
    if connection is None:
        return False
    urls, keys = connection
    matches = [index for index, url in enumerate(urls) if url.rstrip("/") == endpoint.rstrip("/")]
    if len(matches) != 1:
        raise ConnectionError("expected exactly one persisted LiteLLM connection; review it in Open WebUI")
    return keys[matches[0]] != key


def reconcile(database: Path, endpoint: str, key: str) -> bool:
    """Back up SQLite and replace only a stale LiteLLM key while stopped."""
    if not needs_update(database, endpoint, key):
        return False
    metadata = database.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ConnectionError(f"unsafe Open WebUI database: {database}")
    backup = database.with_name(f"{database.name}-backup-{time.strftime('%y%m%d-%H%M%S')}")
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(database)) as connection, closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)
            urls, keys = _read_connection(database) or ([], [])
            index = next(index for index, url in enumerate(urls) if url.rstrip("/") == endpoint.rstrip("/"))
            keys[index] = key
            connection.execute("UPDATE config SET value = ?, updated_at = ? WHERE key = 'openai.api_keys'",
                               (json.dumps(keys), int(time.time())))
            connection.commit()
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return True
