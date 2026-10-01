# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify selective Open WebUI LiteLLM-key reconciliation in an isolated DB."""

import sys

sys.dont_write_bytecode = True

import json
import sqlite3
import stat

import pytest

from wrapper.lib.open_webui_connection import ConnectionError, needs_update, reconcile


def make_database(path, urls, keys):
    """Create the pinned Open WebUI per-key config schema."""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value JSON NOT NULL, updated_at BIGINT)")
        for name, value in (("openai.api_base_urls", urls), ("openai.api_keys", keys),
                            ("web.search", {"enabled": True})):
            connection.execute("INSERT INTO config VALUES (?, ?, 0)", (name, json.dumps(value)))


def test_rotates_only_matching_key_and_preserves_gui_configuration(tmp_path):
    """Keep other connections and settings, and retain an offline backup."""
    database = tmp_path / "webui.db"
    make_database(database, ["http://other/v1", "http://litellm:4000/v1"], ["other-secret", "old-secret"])
    assert needs_update(database, "http://litellm:4000/v1", "new-secret")
    assert reconcile(database, "http://litellm:4000/v1", "new-secret")
    with sqlite3.connect(database) as connection:
        values = {name: json.loads(value) for name, value in connection.execute("SELECT key, value FROM config")}
    assert values["openai.api_keys"] == ["other-secret", "new-secret"]
    assert values["web.search"] == {"enabled": True}
    backup = next(tmp_path.glob("webui.db-backup-*"))
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with sqlite3.connect(backup) as connection:
        assert json.loads(connection.execute("SELECT value FROM config WHERE key='openai.api_keys'").fetchone()[0]) == [
            "other-secret", "old-secret"]
    assert not reconcile(database, "http://litellm:4000/v1", "new-secret")
    assert len(list(tmp_path.glob("webui.db-backup-*"))) == 1


def test_fresh_database_does_not_require_reconciliation(tmp_path):
    """Let Open WebUI seed a genuinely fresh database from Compose."""
    assert not needs_update(tmp_path / "webui.db", "http://litellm:4000/v1", "key")


def test_unexpected_connection_fails_without_modification(tmp_path):
    """Never replace an unknown or ambiguous endpoint."""
    database = tmp_path / "webui.db"
    make_database(database, ["http://elsewhere/v1"], ["old-secret"])
    with pytest.raises(ConnectionError, match="exactly one"):
        reconcile(database, "http://litellm:4000/v1", "new-secret")
    assert not list(tmp_path.glob("webui.db-backup-*"))
