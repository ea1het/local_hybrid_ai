#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
STATE_DIR = Path(os.environ.get("SANDBOX_STATE_DIR", "/var/lib/hermes-sandbox-state"))
DB = STATE_DIR / "state.db"
MARKER = WORKSPACE / ".sandbox-generation"
QUARANTINE = WORKSPACE / ".cleanup-quarantine"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("PRAGMA busy_timeout=30000")
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


def read_marker() -> str:
    if MARKER.is_symlink() or not MARKER.is_file():
        raise RuntimeError(
            "sandbox generation marker missing/invalid; run 02-cleanup.sh --reset-sandbox"
        )
    value = MARKER.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(
            "sandbox generation marker is empty; run 02-cleanup.sh --reset-sandbox"
        )
    return value


def protect(conn: sqlite3.Connection, name: str, inode: int | None, created: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO objects
            (path, inode, first_seen_at, last_activity_at, state, protected,
             quarantined_at, deleted_at)
        VALUES (?, ?, ?, ?, 'PROTECTED', 1, NULL, NULL)
        """,
        (name, inode, created, created),
    )


def initialize_new() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if DB.exists() or MARKER.exists() or MARKER.is_symlink():
        raise RuntimeError(
            "sandbox generation is partially initialized; run 02-cleanup.sh --reset-sandbox"
        )

    for stale in (STATE_DIR / "state.db-wal", STATE_DIR / "state.db-shm"):
        stale.unlink(missing_ok=True)

    leftovers = list(STATE_DIR.iterdir())
    if leftovers:
        raise RuntimeError(
            "sandbox state directory is not empty; run 02-cleanup.sh --reset-sandbox"
        )

    QUARANTINE.mkdir(parents=True, exist_ok=True)

    generation_id = uuid.uuid4().hex
    created = now_utc()
    marker_tmp = WORKSPACE / f".sandbox-generation.tmp.{os.getpid()}"

    try:
        conn = connect()
        try:
            create_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version','1')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES('generation_id',?)",
                (generation_id,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES('created_at',?)",
                (created,),
            )

            for entry in WORKSPACE.iterdir():
                if entry.name.startswith(".sandbox-generation.tmp."):
                    continue
                stat = entry.lstat()
                protect(conn, entry.name, stat.st_ino, created)

            protect(conn, MARKER.name, None, created)
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
        for path in (DB, STATE_DIR / "state.db-wal", STATE_DIR / "state.db-shm"):
            path.unlink(missing_ok=True)
        raise

    print(f"[sandbox-state] initialized generation={generation_id}")


def validate_existing() -> None:
    marker_generation = read_marker()

    if not DB.is_file() or DB.is_symlink():
        raise RuntimeError(
            "state.db missing/invalid; run 02-cleanup.sh --reset-sandbox"
        )

    conn = connect()
    try:
        create_schema(conn)
        if not integrity_ok(conn):
            raise RuntimeError(
                "state.db integrity_check failed; run 02-cleanup.sh --reset-sandbox"
            )

        generation = conn.execute(
            "SELECT value FROM metadata WHERE key='generation_id'"
        ).fetchone()
        schema = conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()

        if not generation or not schema or schema[0] != "1":
            raise RuntimeError(
                "state.db metadata invalid; run 02-cleanup.sh --reset-sandbox"
            )

        if generation[0] != marker_generation:
            raise RuntimeError(
                "sandbox generation mismatch; run 02-cleanup.sh --reset-sandbox"
            )

        created = conn.execute(
            "SELECT value FROM metadata WHERE key='created_at'"
        ).fetchone()
        created_at = created[0] if created else now_utc()
        protect(conn, MARKER.name, MARKER.lstat().st_ino, created_at)
        if QUARANTINE.exists() and not QUARANTINE.is_symlink():
            protect(conn, QUARANTINE.name, QUARANTINE.lstat().st_ino, created_at)
        conn.commit()

        print(f"[sandbox-state] existing generation={generation[0]}")
    finally:
        conn.close()


def main() -> int:
    if not WORKSPACE.is_dir() or WORKSPACE.is_symlink():
        raise RuntimeError(f"invalid workspace: {WORKSPACE}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    db_present = DB.exists() or DB.is_symlink()
    marker_present = MARKER.exists() or MARKER.is_symlink()

    if db_present or marker_present:
        if not (db_present and marker_present):
            raise RuntimeError(
                "sandbox generation is incomplete; run 02-cleanup.sh --reset-sandbox"
            )
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
