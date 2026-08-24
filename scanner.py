"""
scanner.py — Directory walker.

Walks a target directory and upserts every file's metadata into SQLite.

Schema (files table):
    path             TEXT  PRIMARY KEY
    size             INTEGER          bytes
    atime            REAL             Unix timestamp, last access
    mtime            REAL             Unix timestamp, last modification
    embedding        BLOB             serialised numpy float32 vector (set by profiler)
    importance_score REAL  DEFAULT 0.5
    status           TEXT  DEFAULT 'pending'
    action           TEXT             'archive' | 'keep' | 'compress' | NULL
    justification    TEXT
"""

import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = "intent_store.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path             TEXT PRIMARY KEY,
    size             INTEGER,
    atime            REAL,
    mtime            REAL,
    embedding        BLOB,
    importance_score REAL DEFAULT 0.5,
    status           TEXT DEFAULT 'pending',
    action           TEXT,
    justification    TEXT
);
"""


# ── public helpers ────────────────────────────────────────────────────────────

def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return an open, schema-initialised SQLite connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def is_likely_text(path: str, sample: int = 512) -> bool:
    """Return True if the file looks like UTF-8 / ASCII text (no null bytes)."""
    try:
        with open(path, "rb") as fh:
            return b"\x00" not in fh.read(sample)
    except OSError:
        return False


# ── main entry point ──────────────────────────────────────────────────────────

def scan_directory(target_dir: str, db_path: str = DB_PATH) -> int:
    """
    Walk *target_dir* and upsert file metadata into the database.

    On conflict (path already exists):
      - size / atime / mtime are always refreshed for new files.
      - atime / mtime are preserved once an embedding exists, so that a
        re-scan after the profiler has opened the files does not overwrite
        the historically accurate timestamps with "just now".

    Returns the number of files recorded.
    """
    root = Path(target_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    conn = get_connection(db_path)
    cur = conn.cursor()
    count = 0

    for dirpath, _dirs, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.stat(fpath)
            except OSError as exc:
                logger.warning("Cannot stat %s: %s", fpath, exc)
                continue

            # Preserve timestamps once embedding exists (profiler opens files,
            # which resets OS atime; we don't want that to pollute history).
            cur.execute(
                """
                INSERT INTO files (path, size, atime, mtime)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size  = excluded.size,
                    atime = CASE WHEN files.embedding IS NULL
                                 THEN excluded.atime ELSE files.atime END,
                    mtime = CASE WHEN files.embedding IS NULL
                                 THEN excluded.mtime ELSE files.mtime END
                """,
                (str(fpath), st.st_size, st.st_atime, st.st_mtime),
            )
            count += 1
            logger.debug("Indexed: %s", fpath)

    conn.commit()
    conn.close()
    logger.info("Indexed %d files from %s", count, root)
    return count
