#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Initialize or validate generation-bound Hermes sandbox state.

A workspace marker and an integrity-checked SQLite database identify one
sandbox generation. Existing mismatched, symlinked, or partially initialized
state fails closed and requires an explicit reset. Baseline objects are
marked protected so the cleanup sidecar cannot mistake them for disposable
user content. Importing this module does not create the database."""

from __future__ import annotations

import os
import sqlite3
import sys

sys.dont_write_bytecode = True
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
STATE_DIR = Path(os.environ.get("SANDBOX_STATE_DIR", "/var/lib/hermes-sandbox-state"))
DB = STATE_DIR / "state.db"
MARKER = WORKSPACE / ".sandbox-generation"
QUARANTINE = WORKSPACE / ".cleanup-quarantine"
STATE_FILES = (DB, STATE_DIR / "state.db-wal", STATE_DIR / "state.db-shm")
RESET_HINT = "run cleanup.py --reset-sandbox"


def now_utc() -> str:
    """Return an ISO 8601 UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    """Open the lifecycle database with WAL and integrity-related SQLite settings."""
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the lifecycle metadata and object tracking schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS objects (
            path TEXT PRIMARY KEY,
            inode INTEGER,
            first_seen_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('ACTIVE','QUARANTINED','DELETED','PROTECTED')),
            protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0,1)),
            quarantined_at TEXT,
            deleted_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_objects_state_activity
            ON objects(state, last_activity_at);
        CREATE INDEX IF NOT EXISTS idx_objects_deleted_at
            ON objects(deleted_at);
        """
    )


def integrity_ok(conn: sqlite3.Connection) -> bool:
    """Check SQLite database integrity."""
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def metadata_value(conn: sqlite3.Connection, key: str) -> str | None:
    """Read a metadata value, or return None when absent."""
    row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_metadata(conn: sqlite3.Connection, **values: str) -> None:
    """Upsert lifecycle metadata values."""
    conn.executemany(
        "INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
        values.items(),
    )


def read_marker() -> str:
    """Read a valid workspace generation marker or fail closed."""
    if MARKER.is_symlink() or not MARKER.is_file():
        raise RuntimeError(f"sandbox generation marker missing/invalid; {RESET_HINT}")
    value = MARKER.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"sandbox generation marker is empty; {RESET_HINT}")
    return value


def protect(conn: sqlite3.Connection, name: str, inode: int | None, created: str) -> None:
    """Record a top-level workspace object as protected."""
    conn.execute(
        """
        INSERT OR REPLACE INTO objects
            (path, inode, first_seen_at, last_activity_at, state, protected,
             quarantined_at, deleted_at)
        VALUES (?, ?, ?, ?, 'PROTECTED', 1, NULL, NULL)
        """,
        (name, inode, created, created),
    )


def remove_state_files() -> None:
    """Remove database and WAL sidecar files after failed initialization."""
    for path in STATE_FILES:
        path.unlink(missing_ok=True)


def protect_workspace_baseline(conn: sqlite3.Connection, created: str) -> None:
    """Protect all objects present when a generation is created."""
    for entry in WORKSPACE.iterdir():
        if entry.name.startswith(".sandbox-generation.tmp."):
            continue
        protect(conn, entry.name, entry.lstat().st_ino, created)
    protect(conn, MARKER.name, None, created)


def generation_presence() -> tuple[bool, bool]:
    """Report whether the state database and marker each exist."""
    return DB.exists() or DB.is_symlink(), MARKER.exists() or MARKER.is_symlink()


def initialize_new() -> None:
    """Create a new generation, database, and protected workspace baseline."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    db_present, marker_present = generation_presence()
    if db_present or marker_present:
        raise RuntimeError(f"sandbox generation is partially initialized; {RESET_HINT}")

    for stale in STATE_FILES[1:]:
        stale.unlink(missing_ok=True)

    if any(STATE_DIR.iterdir()):
        raise RuntimeError(f"sandbox state directory is not empty; {RESET_HINT}")

    QUARANTINE.mkdir(parents=True, exist_ok=True)

    generation_id = uuid.uuid4().hex
    created = now_utc()
    marker_tmp = WORKSPACE / f".sandbox-generation.tmp.{os.getpid()}"

    try:
        conn = connect()
        try:
            # Commit the database before publishing the marker; either partial state fails closed.
            create_schema(conn)
            set_metadata(
                conn,
                schema_version="1",
                generation_id=generation_id,
                created_at=created,
            )
            protect_workspace_baseline(conn, created)
            conn.commit()
        finally:
            conn.close()

        marker_tmp.write_text(generation_id + "\n", encoding="utf-8")
        os.chmod(marker_tmp, 0o600)
        os.replace(marker_tmp, MARKER)
        os.chmod(DB, 0o600)

        conn = connect()
        try:
            conn.execute(
                "UPDATE objects SET inode=? WHERE path=?",
                (MARKER.lstat().st_ino, MARKER.name),
            )
            conn.commit()
        finally:
            conn.close()

    except Exception:
        marker_tmp.unlink(missing_ok=True)
        MARKER.unlink(missing_ok=True)
        remove_state_files()
        raise

    print(f"[sandbox-state] initialized generation={generation_id}")


def validate_existing() -> None:
    """Validate an existing generation against database integrity and metadata."""
    marker_generation = read_marker()

    if not DB.is_file() or DB.is_symlink():
        raise RuntimeError(f"state.db missing/invalid; {RESET_HINT}")

    conn = connect()
    try:
        create_schema(conn)
        if not integrity_ok(conn):
            raise RuntimeError(f"state.db integrity_check failed; {RESET_HINT}")

        generation = metadata_value(conn, "generation_id")
        schema = metadata_value(conn, "schema_version")
        if generation is None or schema != "1":
            raise RuntimeError(f"state.db metadata invalid; {RESET_HINT}")
        if generation != marker_generation:
            raise RuntimeError(f"sandbox generation mismatch; {RESET_HINT}")

        created_at = metadata_value(conn, "created_at") or now_utc()
        protect(conn, MARKER.name, MARKER.lstat().st_ino, created_at)
        if QUARANTINE.exists() and not QUARANTINE.is_symlink():
            protect(conn, QUARANTINE.name, QUARANTINE.lstat().st_ino, created_at)
        conn.commit()

        print(f"[sandbox-state] existing generation={generation}")
    finally:
        conn.close()


def main() -> int:
    """Initialize or validate generation-bound sandbox state."""
    if not WORKSPACE.is_dir() or WORKSPACE.is_symlink():
        raise RuntimeError(f"invalid workspace: {WORKSPACE}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    db_present, marker_present = generation_presence()
    if db_present or marker_present:
        if not (db_present and marker_present):
            raise RuntimeError(f"sandbox generation is incomplete; {RESET_HINT}")
        validate_existing()
    else:
        initialize_new()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[sandbox-state] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
