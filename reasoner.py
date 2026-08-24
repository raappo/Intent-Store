"""
reasoner.py — Calls a local LLM via Ollama to produce JSON recommendations
{action, justification} for files that are candidates for archival.

Candidacy criteria
──────────────────
A file is a candidate when:
  importance_score < CANDIDATE_THRESHOLD  (low recency/frequency signal)

  OR the file already has a non-rejected recommendation that needs refresh

The LLM prompt includes:
  • filename and extension
  • size in human-readable form
  • days since last access
  • days since last modification
  • the numeric importance_score
  • whether it belongs to a recurring pattern family (derived from score > raw
    decay, i.e. the pattern bonus contributed)
  • first ~500 chars of readable content (if text)

The LLM is expected to return valid JSON:
  {"action": "archive|keep|compress", "justification": "..."}

If Ollama is unavailable, a rule-augmented fallback kicks in that still
produces a richer justification than "file not opened in N days" by
incorporating the semantic embedding similarity to an "important document"
centroid and the recurring-pattern signal.
"""

import json
import logging
import math
import pickle
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests
import numpy as np

from scanner import get_connection, is_likely_text, DB_PATH
from scorer import HALF_LIFE_DAYS, PATTERN_BONUS

logger = logging.getLogger(__name__)

# ── Ollama settings ──────────────────────────────────────────────────────────
OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "llama3"          # change to whichever model is pulled locally
OLLAMA_TIMEOUT  = 60                # seconds

# ── Candidacy threshold ──────────────────────────────────────────────────────
CANDIDATE_THRESHOLD = 0.45          # files below this score are evaluated

# ── Content peek for LLM prompt ─────────────────────────────────────────────
CONTENT_PEEK = 500                  # chars


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _days_ago(ts: float) -> float:
    return max((time.time() - ts) / 86400.0, 0.0)


def _read_snippet(path: str) -> str:
    """Return up to CONTENT_PEEK chars of text content, or empty string."""
    if not is_likely_text(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(CONTENT_PEEK)
    except OSError:
        return ""


def _deserialize_embedding(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if blob is None:
        return None
    try:
        return pickle.loads(blob)
    except Exception:
        return None


def _embedding_similarity(vec_a: Optional[np.ndarray], vec_b: Optional[np.ndarray]) -> float:
    """Cosine similarity, returns 0.0 if either vector is None."""
    if vec_a is None or vec_b is None:
        return 0.0
    denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


# A hand-crafted "important document" centroid phrase whose embedding will be
# compared against each file's embedding to detect semantically significant files.
_IMPORTANCE_PHRASES = [
    "legal contract agreement",
    "tax return financial record",
    "medical report health record",
    "official certificate credential",
    "invoice receipt payment",
    "personal identification document",
]

_importance_centroid: Optional[np.ndarray] = None


def _get_importance_centroid() -> Optional[np.ndarray]:
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
        logger.warning("Could not compute importance centroid: %s", exc)
        return None


def _call_ollama(prompt: str) -> Optional[dict]:
    """POST to Ollama and parse the first valid JSON object from the response."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        return json.loads(raw)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        logger.debug("Ollama call failed: %s", exc)
        return None


def _build_prompt(row: sqlite3.Row, snippet: str, sim_score: float) -> str:
    days_accessed  = _days_ago(row["atime"])
    days_modified  = _days_ago(row["mtime"])
    score          = row["importance_score"]
    size_hr        = _human_size(row["size"])
    filename       = Path(row["path"]).name
    extension      = Path(row["path"]).suffix.lower()

    # Derive whether the pattern bonus was active:
    # if score > raw_decay it means the pattern bonus contributed.
    raw_decay_approx = math.exp(-math.log(2) / HALF_LIFE_DAYS * days_accessed)
    pattern_bonus_active = score > (raw_decay_approx * 1.05)  # 5% headroom

    content_section = (
        f"\nContent preview (first {CONTENT_PEEK} chars):\n```\n{snippet}\n```"
        if snippet else "\n(Binary file — no text preview available.)"
    )

    return f"""You are a storage intelligence assistant for a Linux workstation.
Analyze this file and decide what to do with it. You must return ONLY valid JSON.

=== FILE METADATA ===
Filename       : {filename}
Extension      : {extension or 'none'}
Size           : {size_hr}
Last accessed  : {days_accessed:.1f} days ago
Last modified  : {days_modified:.1f} days ago
Importance score: {score:.3f}  (0 = stale/irrelevant, 1 = critical/active)
Semantic similarity to important-document types: {sim_score:.3f}  (0–1)
Part of a recurring periodic pattern (e.g. yearly invoices): {pattern_bonus_active}
{content_section}

=== TASK ===
Based on the metadata AND content semantics above, choose ONE action:
  - "archive"  : move to cold storage; file is old, unlikely to be needed soon
  - "compress" : keep accessible but compress; moderate recency, large size
  - "keep"     : retain as-is; file is important, active, or semantically critical

Return ONLY a JSON object with exactly these two keys:
  "action"        : one of "archive", "compress", or "keep"
  "justification" : 1-3 sentences explaining your reasoning. Reference specific
                    signals (size, last-access gap, content type, pattern) — do
                    NOT just say "file not opened in N days".

Example output format:
{{"action": "archive", "justification": "This appears to be an old project log from 2022 with no access in 180 days and no recurring-pattern signal. Its content shows debugging output with no personally-identifying or financial data, suggesting it is safe to move to cold storage."}}"""


def _fallback_recommend(row: sqlite3.Row, sim_score: float) -> dict:
    """
    Rule-augmented fallback when Ollama is unavailable.
    Incorporates recency, size, semantic similarity and recurring-pattern
    signal to produce a richer justification than a plain age cutoff.
    """
    days_accessed = _days_ago(row["atime"])
    score         = row["importance_score"]
    size_bytes    = row["size"]
    filename      = Path(row["path"]).name

    raw_decay = math.exp(-math.log(2) / HALF_LIFE_DAYS * days_accessed)
    pattern_active = score > raw_decay * 1.05

    signals = []

    # Semantic importance check
    if sim_score > 0.55:
        signals.append(
            f"its filename/content is semantically similar to important document types "
            f"(similarity={sim_score:.2f}), suggesting it may be a financial, legal, "
            f"or credential-bearing file"
        )
    elif sim_score < 0.25:
        signals.append(
            f"its content bears little resemblance to any high-importance document "
            f"category (similarity={sim_score:.2f})"
        )

    # Recency context
    if days_accessed < 14:
        signals.append(f"it was accessed only {days_accessed:.0f} days ago (recently active)")
    elif days_accessed < 90:
        signals.append(f"it was last accessed {days_accessed:.0f} days ago (moderate staleness)")
    else:
        signals.append(f"it has not been accessed in {days_accessed:.0f} days")

    # Recurring pattern
    if pattern_active:
        signals.append(
            "it belongs to a recurring file pattern (e.g. date-suffixed filename series), "
            "indicating periodic reuse even if currently dormant"
        )

    # Size context
    if size_bytes > 50 * 1024 * 1024:
        signals.append(f"it is large ({_human_size(size_bytes)}), making compression impactful")
    elif size_bytes < 4096:
        signals.append(f"it is very small ({_human_size(size_bytes)}), so storage impact is minimal")

    justification = (
        f"Evaluated '{filename}' using recency decay (score={score:.3f}), "
        f"semantic similarity, size, and pattern analysis: "
        + "; ".join(signals) + "."
    )

    # Decision logic
    if sim_score > 0.55 or pattern_active:
        action = "keep"
    elif days_accessed > 180 and size_bytes > 10 * 1024:
        action = "archive"
    elif size_bytes > 20 * 1024 * 1024 and days_accessed > 30:
        action = "compress"
    else:
        action = "archive" if score < 0.2 else "keep"

    return {"action": action, "justification": justification}


def reason_all(db_path: str = DB_PATH, force: bool = False) -> int:
    """
    Generate recommendations for all candidate files.

    Parameters
    ----------
    force : Re-generate even for files that already have a recommendation.

    Returns the number of files processed.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if force:
        rows = cursor.execute(
            "SELECT * FROM files WHERE status != 'rejected'"
        ).fetchall()
    else:
        rows = cursor.execute(
            """
            SELECT * FROM files
            WHERE importance_score < ?
              AND (recommendation IS NULL OR recommendation = '')
              AND status NOT IN ('accepted', 'rejected')
            """,
            (CANDIDATE_THRESHOLD,),
        ).fetchall()

    if not rows:
        logger.info("No candidate files to reason about.")
        conn.close()
        return 0

    centroid = _get_importance_centroid()
    processed = 0

    for row in rows:
        path    = row["path"]
        emb_vec = _deserialize_embedding(row["embedding"])
        sim     = _embedding_similarity(emb_vec, centroid)
        snippet = _read_snippet(path)

        prompt = _build_prompt(row, snippet, sim)
        result = _call_ollama(prompt)

        if result is None:
            logger.debug("Ollama unavailable for %s; using fallback.", path)
            result = _fallback_recommend(row, sim)

        action        = result.get("action", "keep")
        justification = result.get("justification", "")

        # Validate action value
        if action not in ("archive", "keep", "compress"):
            action = "keep"

        conn.execute(
            """
            UPDATE files
            SET recommendation = ?, justification = ?, action = ?
            WHERE path = ?
            """,
            (action, justification, action, path),
        )
        logger.debug("Reasoned %s → %s", path, action)
        processed += 1

    conn.commit()
    conn.close()
    logger.info("Reasoned about %d files.", processed)
    return processed
