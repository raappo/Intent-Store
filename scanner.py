"""
scanner.py — Directory walker that records file metadata into SQLite.

Schema: files(path, size, atime, mtime, embedding, importance_score, status)
"""

import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = "intent_store.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path              TEXT PRIMARY KEY,
    size              INTEGER,
    atime             REAL,
    mtime             REAL,
    embedding         BLOB,
    importance_score  REAL DEFAULT 0.5,
    status            TEXT DEFAULT 'pending',
    justification     TEXT,
    action            TEXT
);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA_SQL)
    conn.commit()
    return conn


def is_likely_text(path: str, sample_bytes: int = 512) -> bool:
    """Heuristic: a file is text if it contains no null bytes in its first chunk."""
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(sample_bytes)
        return b"\x00" not in chunk
    except OSError:
        return False


def scan_directory(target_dir: str, db_path: str = DB_PATH) -> int:
    """
    Walk *target_dir* recursively and upsert every file's metadata into SQLite.

    Returns the number of files recorded.
    """
    target = Path(target_dir).resolve()
    if not target.is_dir():
        raise ValueError(f"Target is not a directory: {target}")

    conn = get_connection(db_path)
    cursor = conn.cursor()
    count = 0

    for dirpath, _dirnames, filenames in os.walk(target):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                stat = os.stat(fpath)
            except OSError as exc:
                logger.warning("Cannot stat %s: %s", fpath, exc)
                continue

            # Preserve atime/mtime once a file has been embedded: the profiler
            # opens each file for reading which resets the OS atime, so we must
            # protect historically accurate timestamps from being silently
            # overwritten on every subsequent re-scan.
            cursor.execute(
                """
                INSERT INTO files (path, size, atime, mtime)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size  = excluded.size,
                    atime = CASE WHEN files.embedding IS NULL THEN excluded.atime ELSE files.atime END,
                    mtime = CASE WHEN files.embedding IS NULL THEN excluded.mtime ELSE files.mtime END
                """,
                (
                    str(fpath),
                    stat.st_size,
                    stat.st_atime,
                    stat.st_mtime,
                ),
            )
            count += 1
            logger.debug("Recorded: %s", fpath)

    conn.commit()
    conn.close()
    logger.info("Scanned %d files from %s", count, target)
    return count
