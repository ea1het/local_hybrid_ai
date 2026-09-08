#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
STATE_DIR = Path(os.environ.get("SANDBOX_STATE_DIR", "/var/lib/hermes-sandbox-state"))
DB = STATE_DIR / "state.db"
QUARANTINE = WORKSPACE / ".cleanup-quarantine"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
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
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def initialize_new() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE.mkdir(parents=True, exist_ok=True)

    generation_id = uuid.uuid4().hex
    created = now_utc()
    conn = connect()
    try:
        create_schema(conn)
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version','1')")
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('generation_id',?)", (generation_id,))
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('created_at',?)", (created,))

        for entry in WORKSPACE.iterdir():
            stat = entry.lstat()
            rel = entry.name
            conn.execute(
                """
                INSERT OR REPLACE INTO objects
                    (path, inode, first_seen_at, last_activity_at, state, protected)
                VALUES (?, ?, ?, ?, 'PROTECTED', 1)
                """,
                (rel, stat.st_ino, created, created),
            )
        conn.commit()
    finally:
        conn.close()

    os.chmod(DB, 0o600)
    print(f"[sandbox-state] initialized generation={generation_id}")


def validate_existing() -> None:
    conn = connect()
    try:
        create_schema(conn)
        if not integrity_ok(conn):
            raise RuntimeError("state.db integrity_check failed; run 02-cleanup.sh --reset-sandbox")
        generation = conn.execute("SELECT value FROM metadata WHERE key='generation_id'").fetchone()
        schema = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not generation or not schema or schema[0] != "1":
            raise RuntimeError("state.db metadata invalid; run 02-cleanup.sh --reset-sandbox")
        print(f"[sandbox-state] existing generation={generation[0]}")
    finally:
        conn.close()


def main() -> int:
    if not WORKSPACE.is_dir() or WORKSPACE.is_symlink():
        raise RuntimeError(f"invalid workspace: {WORKSPACE}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        validate_existing()
    else:
        # Missing DB with a non-empty state directory indicates partial/corrupt state.
        leftovers = [p for p in STATE_DIR.iterdir() if p.name not in {"state.db-wal", "state.db-shm"}]
        if leftovers:
            raise RuntimeError("sandbox state is incomplete; run 02-cleanup.sh --reset-sandbox")
        initialize_new()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[sandbox-state] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
