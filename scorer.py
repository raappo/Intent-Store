"""
scorer.py — Computes a decay-based importance score and a recurring-pattern
heuristic for each file.

Scoring model
─────────────
1. Recency/frequency decay  (0–1, higher = more recently accessed)
   decay = exp(-λ · days_since_last_access)
   λ = ln(2) / HALF_LIFE_DAYS   →  a file loses half its "freshness" every
   HALF_LIFE_DAYS days without being accessed.

2. Recurring-pattern bonus  (0–1)
   Files whose stem matches a date-suffixed pattern like:
     invoice_2023.pdf, invoice_2024.pdf, invoice_2025.pdf
   are detected by stripping trailing 4-digit years/numbers and clustering
   stems.  Files that belong to a pattern family with ≥ MIN_PATTERN_FAMILY
   members get a bonus (recurring = True).  This signals "this file is part
   of a periodic workflow" independent of its recency.

3. Final importance_score = recency_decay · (1 + PATTERN_BONUS · recurring)
   Clamped to [0, 1].

   Interpretation:
   • High score  → file is recent OR part of a recurring pattern → lean Keep
   • Low score   → old AND not part of any recognized pattern → candidate
                    for archival / compression
"""

import math
import re
import sqlite3
import time
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from scanner import get_connection, DB_PATH

logger = logging.getLogger(__name__)

# ── tuneable constants ────────────────────────────────────────────────────────
HALF_LIFE_DAYS       = 90          # recency half-life in days
PATTERN_BONUS        = 0.35        # additive importance boost for recurring files
MIN_PATTERN_FAMILY   = 2           # minimum family size to count as "recurring"
# Pattern: stem ends with 4-digit year, 2-digit month/day combo, or ordinal num
_DATE_SUFFIX_RE = re.compile(
    r"[-_\s]?(\d{4}|\d{2}[-_]\d{2}|\d{1,3})$"
)
# ─────────────────────────────────────────────────────────────────────────────


def _recency_decay(atime: float, now: float | None = None) -> float:
    """Exponential decay on days since last access."""
    now = now or time.time()
    days = max((now - atime) / 86400.0, 0.0)
    lam = math.log(2) / HALF_LIFE_DAYS
    return math.exp(-lam * days)


def _pattern_key(path: str) -> str:
    """
    Strip trailing date/number suffixes from the file stem to produce a
    canonical pattern key used for family grouping.

    Examples:
      invoice_2024.pdf → 'invoice'
      report_jan_03.txt → 'report_jan'
      notes.md → 'notes'
    """
    stem = Path(path).stem
    return _DATE_SUFFIX_RE.sub("", stem).lower().rstrip("-_ ")


def _detect_recurring(
    rows: List[sqlite3.Row],
) -> Dict[str, bool]:
    """
    Build a map of path → is_recurring.

    Two files are in the same family when they share the same *parent directory*
    AND the same *pattern key*.  This avoids false positives across unrelated
    directories.
    """
    # Group by (parent_dir, pattern_key)
    families: Dict[Tuple[str, str], List[str]] = {}
    for row in rows:
        p = row["path"]
        key = (_pattern_key(p), str(Path(p).parent))
        families.setdefault(key, []).append(p)

    recurring: Dict[str, bool] = {}
    for members in families.values():
        is_rec = len(members) >= MIN_PATTERN_FAMILY
        for m in members:
            recurring[m] = is_rec

    return recurring


def score_all(db_path: str = DB_PATH) -> int:
    """
    Compute and persist importance_score for every file in the database.

    Returns the number of rows updated.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    rows = cursor.execute(
        "SELECT path, atime, mtime, importance_score FROM files"
    ).fetchall()

    if not rows:
        logger.info("No files to score.")
        conn.close()
        return 0

    now = time.time()
    recurring_map = _detect_recurring(rows)

    updates: List[Tuple[float, str]] = []
    for row in rows:
        decay   = _recency_decay(row["atime"], now)
        is_rec  = recurring_map.get(row["path"], False)
        score   = decay * (1.0 + PATTERN_BONUS * float(is_rec))
        score   = min(score, 1.0)
        updates.append((round(score, 6), row["path"]))

    cursor.executemany(
        "UPDATE files SET importance_score = ? WHERE path = ?",
        updates,
    )
    conn.commit()
    conn.close()

    logger.info("Scored %d files.", len(updates))
    return len(updates)
