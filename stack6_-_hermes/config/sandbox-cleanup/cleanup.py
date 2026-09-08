#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("SANDBOX_CLEANUP_WORKSPACE", "/workspace"))
STATE_DB = Path(os.environ.get("SANDBOX_CLEANUP_STATE_DB", "/state/state.db"))
RETENTION_DAYS = int(os.environ.get("SANDBOX_CLEANUP_RETENTION_DAYS", "7"))
QUARANTINE_DAYS = int(os.environ.get("SANDBOX_CLEANUP_QUARANTINE_DAYS", "1"))
DB_RETENTION_DAYS = int(os.environ.get("SANDBOX_CLEANUP_DB_RETENTION_DAYS", "90"))
SWEEP_HOUR = int(os.environ.get("SANDBOX_CLEANUP_SWEEP_HOUR", "3"))
SWEEP_MINUTE = int(os.environ.get("SANDBOX_CLEANUP_SWEEP_MINUTE", "30"))
QUARANTINE = WORKSPACE / ".cleanup-quarantine"

_LOCK = threading.Lock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB, timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def validate_state() -> str:
    if not STATE_DB.is_file():
        raise RuntimeError(f"state database missing: {STATE_DB}")
    conn = connect()
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("state.db integrity_check failed; run 02-cleanup.sh --reset-sandbox")
        generation = conn.execute("SELECT value FROM metadata WHERE key='generation_id'").fetchone()
        schema = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not generation or not schema or schema[0] != "1":
            raise RuntimeError("state.db metadata invalid; run 02-cleanup.sh --reset-sandbox")
        return generation[0]
    finally:
        conn.close()


def top_level(path: Path) -> str | None:
    try:
        rel = path.relative_to(WORKSPACE)
    except ValueError:
        return None
    if not rel.parts:
        return None
    return rel.parts[0]


def latest_activity(path: Path) -> datetime:
    latest_ns = path.lstat().st_mtime_ns
    if path.is_dir() and not path.is_symlink():
        for root, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                candidate = Path(root) / name
                try:
                    latest_ns = max(latest_ns, candidate.lstat().st_mtime_ns)
                except FileNotFoundError:
                    pass
    return datetime.fromtimestamp(latest_ns / 1_000_000_000, tz=timezone.utc)


def reconcile_top_level(conn: sqlite3.Connection) -> None:
    seen: set[str] = set()
    now = now_utc()
    for entry in WORKSPACE.iterdir():
        name = entry.name
        if name == ".cleanup-quarantine":
            continue
        seen.add(name)
        try:
            stat = entry.lstat()
            activity = latest_activity(entry)
        except FileNotFoundError:
            continue
        row = conn.execute(
            "SELECT protected,state,last_activity_at FROM objects WHERE path=?", (name,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO objects(path,inode,first_seen_at,last_activity_at,state,protected) VALUES(?,?,?,?, 'ACTIVE',0)",
                (name, stat.st_ino, iso(now), iso(activity)),
            )
            print(f"[sandbox-cleanup] DISCOVER path={name}")
            continue
        protected, state, last_activity = row
        if protected:
            continue
        if state == "ACTIVE" and activity > parse_iso(last_activity):
            conn.execute(
                "UPDATE objects SET inode=?, last_activity_at=? WHERE path=?",
                (stat.st_ino, iso(activity), name),
            )

    rows = conn.execute("SELECT path,protected,state FROM objects").fetchall()
    for name, protected, state in rows:
        if protected or state in {"DELETED", "QUARANTINED"}:
            continue
        if name not in seen:
            conn.execute(
                "UPDATE objects SET state='DELETED', deleted_at=? WHERE path=?",
                (iso(now), name),
            )


def mark_activity(name: str) -> None:
    if name == ".cleanup-quarantine":
        return
    path = WORKSPACE / name
    timestamp = iso()
    inode = None
    try:
        inode = path.lstat().st_ino
    except FileNotFoundError:
        pass

    with _LOCK:
        conn = connect()
        try:
            row = conn.execute("SELECT protected,state FROM objects WHERE path=?", (name,)).fetchone()
            if row and row[0] == 1:
                return
            if row:
                conn.execute(
                    "UPDATE objects SET inode=?, last_activity_at=?, state='ACTIVE', quarantined_at=NULL, deleted_at=NULL WHERE path=?",
                    (inode, timestamp, name),
                )
            else:
                conn.execute(
                    "INSERT INTO objects(path,inode,first_seen_at,last_activity_at,state,protected) VALUES(?,?,?,?, 'ACTIVE',0)",
                    (name, inode, timestamp, timestamp),
                )
            conn.commit()
        finally:
            conn.close()


def mark_deleted_if_missing(name: str) -> None:
    if (WORKSPACE / name).exists() or (WORKSPACE / name).is_symlink():
        return
    with _LOCK:
        conn = connect()
        try:
            row = conn.execute("SELECT protected,state FROM objects WHERE path=?", (name,)).fetchone()
            if not row or row[0] == 1 or row[1] == "DELETED":
                return
            conn.execute(
                "UPDATE objects SET state='DELETED', deleted_at=? WHERE path=?",
                (iso(), name),
            )
            conn.commit()
        finally:
            conn.close()


def watcher() -> None:
    cmd = [
        "inotifywait", "-m", "-r", "-q",
        "-e", "create", "-e", "modify", "-e", "close_write",
        "-e", "moved_to", "-e", "moved_from", "-e", "delete",
        "--format", "%w%f",
        str(WORKSPACE),
    ]
    while True:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            raw = line.rstrip("\n")
            name = top_level(Path(raw))
            if not name or name == ".cleanup-quarantine":
                continue
            if (WORKSPACE / name).exists() or (WORKSPACE / name).is_symlink():
                mark_activity(name)
            else:
                mark_deleted_if_missing(name)
        err = proc.stderr.read().strip() if proc.stderr else ""
        print(f"[sandbox-cleanup] watcher exited rc={proc.wait()} {err}", file=sys.stderr)
        time.sleep(5)


def safe_remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def quarantine_candidate(conn: sqlite3.Connection, name: str, last_activity: str) -> bool:
    src = WORKSPACE / name
    if not src.exists() and not src.is_symlink():
        conn.execute("UPDATE objects SET state='DELETED', deleted_at=? WHERE path=?", (iso(), name))
        return False

    cutoff = now_utc() - timedelta(days=RETENTION_DAYS)
    if parse_iso(last_activity) > cutoff:
        return False

    before = latest_activity(src)
    time.sleep(0.05)
    try:
        after = latest_activity(src)
    except FileNotFoundError:
        return False
    if after != before:
        conn.execute("UPDATE objects SET last_activity_at=? WHERE path=?", (iso(after), name))
        print(f"[sandbox-cleanup] SKIP changed-during-scan path={name}")
        return False

    inode = src.lstat().st_ino
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    dest = QUARANTINE / f"{name}.{stamp}.{inode}"
    src.rename(dest)
    conn.execute(
        "UPDATE objects SET state='QUARANTINED', quarantined_at=?, last_activity_at=? WHERE path=?",
        (iso(), iso(), name),
    )
    print(f"[sandbox-cleanup] QUARANTINE path={name}")
    return True


def delete_quarantined(conn: sqlite3.Connection) -> int:
    cutoff = now_utc() - timedelta(days=QUARANTINE_DAYS)
    rows = conn.execute(
        "SELECT path, quarantined_at FROM objects WHERE state='QUARANTINED' AND quarantined_at IS NOT NULL"
    ).fetchall()
    deleted = 0
    for name, quarantined_at in rows:
        if parse_iso(quarantined_at) > cutoff:
            continue
        matches = sorted(QUARANTINE.glob(f"{name}.*"))
        for path in matches:
            safe_remove(path)
        conn.execute(
            "UPDATE objects SET state='DELETED', deleted_at=? WHERE path=?",
            (iso(), name),
        )
        print(f"[sandbox-cleanup] DELETE path={name}")
        deleted += 1
    return deleted


def audit(conn: sqlite3.Connection) -> None:
    total_bytes = 0
    count = 0
    for root, dirs, files in os.walk(WORKSPACE, followlinks=False):
        if Path(root) == QUARANTINE:
            dirs[:] = []
            continue
        for filename in files:
            path = Path(root) / filename
            try:
                if not path.is_symlink():
                    total_bytes += path.stat().st_size
                count += 1
            except FileNotFoundError:
                pass
    protected = conn.execute("SELECT COUNT(*) FROM objects WHERE protected=1").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM objects WHERE state='ACTIVE'").fetchone()[0]
    quarantined = conn.execute("SELECT COUNT(*) FROM objects WHERE state='QUARANTINED'").fetchone()[0]
    print(
        f"[sandbox-cleanup] AUDIT files={count} bytes={total_bytes} "
        f"protected={protected} active={active} quarantined={quarantined}"
    )


def sweep() -> None:
    generation = validate_state()
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        conn = connect()
        try:
            reconcile_top_level(conn)
            audit(conn)
            rows = conn.execute(
                "SELECT path,last_activity_at FROM objects WHERE protected=0 AND state='ACTIVE'"
            ).fetchall()
            quarantined = 0
            for name, last_activity in rows:
                if quarantine_candidate(conn, name, last_activity):
                    quarantined += 1
            deleted = delete_quarantined(conn)
            cutoff = iso(now_utc() - timedelta(days=DB_RETENTION_DAYS))
            conn.execute(
                "DELETE FROM objects WHERE state='DELETED' AND deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
            conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_sweep_at',?)", (iso(),))
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA incremental_vacuum")
            print(
                f"[sandbox-cleanup] SWEEP generation={generation} quarantined={quarantined} deleted={deleted}"
            )
        finally:
            conn.close()


def next_sweep_delay() -> float:
    now = datetime.now().astimezone()
    target = now.replace(hour=SWEEP_HOUR, minute=SWEEP_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def scheduler() -> None:
    while True:
        time.sleep(next_sweep_delay())
        try:
            sweep()
        except Exception as exc:
            print(f"[sandbox-cleanup] sweep failed: {exc}", file=sys.stderr)


def main() -> int:
    for value, name in [
        (RETENTION_DAYS, "RETENTION_DAYS"),
        (QUARANTINE_DAYS, "QUARANTINE_DAYS"),
        (DB_RETENTION_DAYS, "DB_RETENTION_DAYS"),
    ]:
        if value < 1:
            raise RuntimeError(f"{name} must be >= 1")
    generation = validate_state()
    print(f"[sandbox-cleanup] start generation={generation}")
    sweep()
    threading.Thread(target=watcher, daemon=True, name="inotify-watcher").start()
    scheduler()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        print(f"[sandbox-cleanup] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
