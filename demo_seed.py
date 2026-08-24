"""
demo_seed.py — Seed the database with realistic access-time overrides so the
demo shows interesting scoring variation without depending on the host OS's
actual file-access history.

Run this ONCE after `python3 cli.py scan demo/` to back-fill realistic
timestamps into the SQLite database.  The scan command will normally
over-write atimes with the current time (because the OS updates atime on
read), so this script corrects them to values that exercise the full scoring
range.
"""

import sqlite3
import time
import sys
from pathlib import Path

DB_PATH = "intent_store.db"

# (path_suffix, days_since_access, days_since_modify)
# These correspond to the four demo/ files.
DEMO_OVERRIDES = [
    ("invoice_2024.txt",              200,  500),  # stale recurring financial doc
    ("invoice_2025.txt",               30,   30),  # recent recurring financial doc
    ("debug_crawler_2022.log",       1500, 1600),  # very stale debug log
    ("project_alpha_notes_2021.md",   900, 1000),  # old meeting notes
]


def seed(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    now = time.time()
    updated = 0

    for suffix, a_days, m_days in DEMO_OVERRIDES:
        rows = conn.execute(
            "SELECT path FROM files WHERE path LIKE ?", (f"%{suffix}",)
        ).fetchall()
        if not rows:
            print(f"  [warn] no DB entry found for *{suffix} — run scan first.")
            continue
        for (path,) in rows:
            conn.execute(
                "UPDATE files SET atime=?, mtime=? WHERE path=?",
                (now - a_days * 86400, now - m_days * 86400, path),
            )
            print(f"  set atime={a_days}d ago  mtime={m_days}d ago  → {Path(path).name}")
            updated += 1

    conn.commit()
    conn.close()
    print(f"\nSeeded {updated} file(s).  Now run: python3 cli.py report  (after re-scoring)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    seed(db)
