"""
scorer.py — Importance scoring engine.

Computes a final `importance_score` for each file based on:
1. Recency Decay (exponential decay based on last access time).
2. Recurring Pattern Bonus (detects date-suffixed files in the same family).
3. Semantic Similarity (cosine similarity against a high-importance reference centroid).

The final score is clamped between [0.0, 1.0].
"""

import math
import re
import time
import logging
from collections import defaultdict
from typing import Dict
import numpy as np

from scanner import get_connection, DB_PATH
from profiler import deserialize

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

HALF_LIFE_DAYS = 90
PATTERN_BONUS = 0.35
SIMILARITY_BONUS = 0.40
MIN_PATTERN_FAMILY = 2

# Matches date/number suffixes like _2024, -12-05, _v2, etc.
_DATE_SUFFIX_RE = re.compile(r"[-_\s]?(\d{4}|\d{2}[-_]\d{2}|\d{1,3})$")

# High-importance reference phrases to compute the semantic centroid
_IMPORTANCE_PHRASES = [
    "legal contract agreement formal binding",
    "tax return financial record statement invoice receipt",
    "medical report health record prescription",
    "official certificate credential passport identity",
]

_importance_centroid = None


def _get_importance_centroid() -> np.ndarray:
    """Computes and caches the reference embedding centroid."""
    global _importance_centroid
    if _importance_centroid is not None:
        return _importance_centroid
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        vecs = model.encode(_IMPORTANCE_PHRASES)
        _importance_centroid = vecs.mean(axis=0)
        return _importance_centroid
    except Exception as exc:
        logger.error("Could not compute importance centroid: %s", exc)
        # Fallback to a zero vector if something is fatally wrong, though profiler
        # should have caught model load errors.
        return np.zeros(384, dtype=np.float32)


# ── helpers ───────────────────────────────────────────────────────────────────

def _days_ago(ts: float) -> float:
    return max(0.0, (time.time() - ts) / 86400.0)


def _get_stem_pattern(filename: str) -> str:
    """Strip date/number suffixes to find the base 'family' name."""
    import os
    base = os.path.splitext(filename)[0]
    return _DATE_SUFFIX_RE.sub("", base).strip().lower()


def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    if vec1 is None or vec2 is None:
        return 0.0
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


# ── main ──────────────────────────────────────────────────────────────────────

def score_all(db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT path, atime, embedding FROM files").fetchall()
    
    if not rows:
        logger.info("No files to score.")
        conn.close()
        return 0

    # 1. Detect recurring pattern families
    family_counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        import os
        fname = os.path.basename(r["path"])
        family_counts[_get_stem_pattern(fname)] += 1

    # 2. Compute similarity centroid
    centroid = _get_importance_centroid()

    scored = 0
    for r in rows:
        path = r["path"]
        fname = os.path.basename(path)
        
        # Base Recency Score
        days_accessed = _days_ago(r["atime"])
        recency_score = math.exp(-math.log(2) / HALF_LIFE_DAYS * days_accessed)
        
        # Pattern Bonus
        family = _get_stem_pattern(fname)
        is_recurring = family_counts[family] >= MIN_PATTERN_FAMILY
        pattern_bonus = PATTERN_BONUS if is_recurring else 0.0
        
        # Semantic Similarity Bonus
        vec = deserialize(r["embedding"])
        sim_score = _cosine_similarity(vec, centroid) if vec is not None else 0.0
        
        # We map similarity (which can be [-1, 1], but usually [0, 1] for embeddings)
        # to a bonus. If sim_score > 0.3, it starts contributing meaningfully.
        sim_bonus = max(0.0, sim_score - 0.2) * SIMILARITY_BONUS
        
        final_score = min(1.0, recency_score + pattern_bonus + sim_bonus)
        
        conn.execute(
            "UPDATE files SET importance_score = ? WHERE path = ?",
            (final_score, path)
        )
        scored += 1

    conn.commit()
    conn.close()
    logger.info("Scored %d files.", scored)
    return scored
