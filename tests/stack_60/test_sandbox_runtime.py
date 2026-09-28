# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Hermes sandbox generation and cleanup sidecar behavior."""

import sys

sys.dont_write_bytecode = True

from datetime import timedelta

import pytest

from tests.helpers import load_module


STACK = "stack-60_-_hermes"


def sandbox_modules(tmp_path, monkeypatch):
    """Load sandbox modules and bind them to an isolated workspace."""
    state = load_module(STACK, "config/sandbox/state-init.py")
    cleaner = load_module(STACK, "config/sandbox-cleanup/cleanup.py")
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    workspace.mkdir()
    marker = workspace / ".sandbox-generation"
    quarantine = workspace / ".cleanup-quarantine"
    database = state_dir / "state.db"
    for target in (state, cleaner):
        monkeypatch.setattr(target, "WORKSPACE", workspace)
        monkeypatch.setattr(target, "MARKER", marker)
        monkeypatch.setattr(target, "QUARANTINE", quarantine)
    monkeypatch.setattr(state, "STATE_DIR", state_dir)
    monkeypatch.setattr(state, "DB", database)
    monkeypatch.setattr(state, "STATE_FILES", (database, state_dir / "state.db-wal", state_dir / "state.db-shm"))
    monkeypatch.setattr(cleaner, "STATE_DB", database)
    return state, cleaner, workspace, marker


def test_state_initializer_creates_and_validates_generation(tmp_path, monkeypatch):
    """Initialize a generation and preserve protected baseline objects."""
    state, cleaner, workspace, marker = sandbox_modules(tmp_path, monkeypatch)
    (workspace / "baseline.txt").write_text("preserve")
    assert state.main() == 0
    generation = marker.read_text().strip()
    assert generation
    assert cleaner.validate_state() == generation
    conn = state.connect()
    try:
        assert state.metadata_value(conn, "generation_id") == generation
        row = conn.execute("SELECT state, protected FROM objects WHERE path='baseline.txt'").fetchone()
        assert row == ("PROTECTED", 1)
    finally:
        conn.close()
    assert state.main() == 0
    assert marker.read_text().strip() == generation


def test_state_initializer_rejects_partial_and_mismatched_state(tmp_path, monkeypatch):
    """Reject incomplete or mismatched sandbox generation state."""
    state, cleaner, _workspace, marker = sandbox_modules(tmp_path, monkeypatch)
    marker.write_text("orphan")
    with pytest.raises(RuntimeError, match="incomplete"):
        state.main()
    marker.unlink()
    state.main()
    marker.write_text("different-generation")
    with pytest.raises(RuntimeError, match="mismatch"):
        state.main()
    with pytest.raises(RuntimeError, match="mismatch"):
        cleaner.validate_state()


def test_cleanup_sidecar_quarantines_then_deletes_unprotected_file(tmp_path, monkeypatch):
    """Quarantine and delete an expired unprotected workspace file."""
    state, cleaner, workspace, _marker = sandbox_modules(tmp_path, monkeypatch)
    state.main()
    payload = workspace / "stale.txt"
    payload.write_text("temporary")
    conn = cleaner.connect()
    try:
        stale = cleaner.iso(cleaner.now_utc() - timedelta(days=10))
        conn.execute(
            "INSERT INTO objects(path, first_seen_at, last_activity_at, state, protected) "
            "VALUES (?, ?, ?, 'ACTIVE', 0)",
            (payload.name, stale, stale),
        )
        monkeypatch.setattr(cleaner.time, "sleep", lambda _: None)
        assert cleaner.quarantine_candidate(conn, payload.name, stale)
        assert not payload.exists()
        assert len(cleaner.quarantine_matches(payload.name)) == 1
        conn.execute("UPDATE objects SET quarantined_at=? WHERE path=?", (stale, payload.name))
        assert cleaner.delete_quarantined(conn) == 1
        assert not cleaner.quarantine_matches(payload.name)
    finally:
        conn.close()


def test_cleanup_sidecar_rejects_marker_symlink_and_outside_path(tmp_path, monkeypatch):
    """Reject symlinked markers and paths outside the workspace."""
    _state, cleaner, workspace, marker = sandbox_modules(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.write_text("not a marker")
    marker.symlink_to(outside)
    with pytest.raises(RuntimeError, match="marker"):
        cleaner.read_marker()
    assert cleaner.top_level(outside) is None
    assert cleaner.top_level(workspace / "nested" / "file") == "nested"
