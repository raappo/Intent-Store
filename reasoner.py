"""
reasoner.py — Calls a local LLM via Ollama to produce JSON recommendations
{action, justification} for files that are candidates for archival.

Candidacy criteria
──────────────────
A file is a candidate when:
  importance_score < CANDIDATE_THRESHOLD
  AND action IS NULL (meaning no recommendation exists yet)
  AND status NOT IN ('accepted', 'rejected')

The LLM prompt includes:
  • filename and extension
  • size in human-readable form
  • days since last access
  • days since last modification
  • the numeric importance_score
  • first ~500 chars of readable content (if text)

The LLM is expected to return valid JSON:
  {"action": "archive|keep|compress", "justification": "..."}

If Ollama is unavailable, a rule-augmented fallback kicks in that still
produces a richer justification than "file not opened in N days".
"""

import json
import logging
import math
import requests
import sqlite3
import time
from pathlib import Path
from typing import Optional

from scanner import get_connection, DB_PATH, is_likely_text
from profiler import deserialize
from scorer import HALF_LIFE_DAYS, _get_importance_centroid, _cosine_similarity

logger = logging.getLogger(__name__)

# ── Ollama settings ──────────────────────────────────────────────────────────
OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "qwen2.5:0.5b"
OLLAMA_TIMEOUT  = 30

CANDIDATE_THRESHOLD = 0.45
CONTENT_PEEK = 500


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _days_ago(ts: float) -> float:
    return max(0.0, (time.time() - ts) / 86400.0)


def _read_snippet(path: str) -> str:
    if not is_likely_text(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(CONTENT_PEEK)
    except OSError:
        return ""


def _call_ollama(prompt: str) -> Optional[dict]:
    """POST to Ollama and return the parsed JSON response, or None on any failure."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    
    print(f"DEBUG _call_ollama: URL={OLLAMA_URL}, Timeout={OLLAMA_TIMEOUT}")
    print(f"DEBUG _call_ollama: Payload={json.dumps(payload)}")
    
    import traceback
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        return json.loads(raw)
    except requests.exceptions.Timeout as exc:
        traceback.print_exc()
        logger.warning(
            "Ollama timed out after %ds (model=%s) — activating fallback engine.",
            OLLAMA_TIMEOUT, OLLAMA_MODEL,
        )
        return None
    except requests.exceptions.ConnectionError as exc:
        traceback.print_exc()
        logger.warning(
            "Ollama not reachable at %s — activating fallback engine.", OLLAMA_URL
        )
        return None
    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        traceback.print_exc()
        logger.warning("Ollama call failed (%s) — activating fallback engine.", exc)
        return None


def _build_prompt(row: sqlite3.Row, snippet: str, sim_score: float) -> str:
    days_accessed  = _days_ago(row["atime"])
    days_modified  = _days_ago(row["mtime"])
    score          = row["importance_score"]
    size_hr        = _human_size(row["size"])
    filename       = Path(row["path"]).name

    content_section = (
        f"\nContent preview (first {CONTENT_PEEK} chars):\n```\n{snippet}\n```"
        if snippet else "\n(Binary file — no text preview available.)"
    )

    return f"""You are a storage intelligence assistant for a Linux workstation.
Analyze this file and decide what to do with it (archive, keep, or compress). You must return ONLY valid JSON.

=== FILE METADATA ===
Filename: {filename}
Size: {size_hr}
Last Accessed: {days_accessed:.0f} days ago
Last Modified: {days_modified:.0f} days ago
Recency/Pattern Score: {score:.3f} (0=delete, 1=keep)
Semantic Similarity to Important Documents: {sim_score:.3f} (higher is more important)
{content_section}

=== INSTRUCTIONS ===
Write a 1-2 sentence justification for your recommendation that:
- References something specific about the file's actual content or type. DO NOT just say "content bears little resemblance to high-importance categories".
- RECURRENCE REASONING: If the filename or content suggests a periodic/seasonal document (tax, invoice, annual report, renewal), explicitly reason about it. For example, "even though unused recently, this type of file is typically needed again at a predictable future point". This is critical.
- Varies in phrasing between files (do not use a repeated template sentence structure).

Respond in exactly this JSON format:
{{"action": "archive" | "keep" | "compress", "justification": "<your specific, dynamic reasoning>"}}
"""


def _fallback_recommend(row: sqlite3.Row, sim_score: float) -> dict:
    """Rule-augmented fallback when Ollama is unavailable."""
    days_accessed = _days_ago(row["atime"])
    score         = row["importance_score"]
    size_bytes    = row["size"]
    filename      = Path(row["path"]).name

    raw_decay = math.exp(-math.log(2) / HALF_LIFE_DAYS * days_accessed)
    pattern_active = score > raw_decay * 1.05

    signals = []
    
    if sim_score > 0.3:
        signals.append(f"its content has semantic similarity to important document categories (similarity={sim_score:.2f})")
    else:
        signals.append(f"its content bears little resemblance to high-importance document categories (similarity={sim_score:.2f})")
        
    if pattern_active:
        signals.append("it belongs to a recurring file pattern series, indicating periodic reuse even if currently dormant")
        
    if size_bytes < 1024 * 100: # 100KB
        signals.append(f"it is very small ({_human_size(size_bytes)}), so storage impact is minimal")
    elif size_bytes > 1024 * 1024 * 100: # 100MB
        signals.append(f"it is very large ({_human_size(size_bytes)}) and consuming significant space")

    signals.append(f"it has not been accessed in {days_accessed:.0f} days")

    action = "archive" if score < 0.2 else "keep"
    
    if size_bytes > 1024 * 1024 * 100 and days_accessed > 180:
        action = "archive"

    # Make fallback phrasing dynamic
    import random
    intros = [
        f"Looking at {filename}, I noticed",
        f"For this file ({filename}),",
        f"Based on the metadata for {filename},",
        f"Evaluating {filename} reveals that"
    ]
    
    justification = f"{random.choice(intros)} "
    justification += " and ".join(signals) + "."
    if pattern_active and action == "keep":
        justification += " I recommend keeping it because periodic documents are often needed later despite long dormant periods."
    elif action == "archive":
        justification += " Given the lack of recent use and low importance, archiving is safe."

    return {"action": action, "justification": justification}


def reason_all(db_path: str = DB_PATH, force: bool = False) -> int:
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
            WHERE (action IS NULL OR action = '')
              AND status NOT IN ('accepted', 'rejected')
            """
        ).fetchall()

    if not rows:
        logger.info("No candidate files to reason about.")
        conn.close()
        return 0

    centroid = _get_importance_centroid()
    processed = 0

    for row in rows:
        path    = row["path"]
        emb_vec = deserialize(row["embedding"])
        sim     = _cosine_similarity(emb_vec, centroid)
        snippet = _read_snippet(path)

        prompt = _build_prompt(row, snippet, sim)
        result = _call_ollama(prompt)

        is_llm = True
        if result is None:
            result = _fallback_recommend(row, sim)
            is_llm = False

        action        = result.get("action", "keep")
        raw_just      = result.get("justification", "")
        
        prefix = "[LLM] " if is_llm else "[RULE] "
        justification = prefix + raw_just

        if action not in ("archive", "keep", "compress"):
            action = "keep"

        conn.execute(
            """
            UPDATE files
            SET justification = ?, action = ?
            WHERE path = ?
            """,
            (justification, action, path),
        )
        logger.debug("Reasoned %s → %s", path, action)
        processed += 1

    conn.commit()
    conn.close()
    logger.info("Reasoned about %d files.", processed)
    return processed
