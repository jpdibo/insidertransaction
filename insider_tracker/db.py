from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if not readonly:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


def migrate(connection: sqlite3.Connection, migrations_dir: Path) -> list[str]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied: list[str] = []
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.name.split("_", 1)[0]
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        existing = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        if existing:
            if existing["checksum"] != checksum:
                raise RuntimeError(f"migration checksum mismatch: {path.name}")
            continue
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at) "
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (version, checksum),
        )
        connection.commit()
        applied.append(version)
    return applied


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
