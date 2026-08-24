"""
profiler.py — Semantic embedding generator.

Embedding method: sentence-transformers / all-MiniLM-L6-v2 (384-dim).
The model is loaded from the local HuggingFace cache (already downloaded).

Startup guarantee
─────────────────
_verify_model() is called once at module import.  It will:
  1. Try to load the SentenceTransformer model and encode a test sentence.
  2. If that succeeds → EMBEDDING_METHOD = "sentence-transformers/all-MiniLM-L6-v2"
  3. If that fails    → raises RuntimeError with the exact exception message,
     so the caller sees the error immediately rather than producing silent
     zero-vectors.

Text input per file
───────────────────
  filename (stem, extension stripped, underscores → spaces) + first 500 chars
  of readable content, concatenated.  Binary files get filename only.

Storage
───────
  Embedding serialised as a raw numpy float32 blob and written to the
  `embedding` column in SQLite.
"""

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

from scanner import get_connection, is_likely_text, DB_PATH

logger = logging.getLogger(__name__)

CONTENT_PEEK = 500   # chars of content to read per file

# ── model bootstrap ───────────────────────────────────────────────────────────

EMBEDDING_METHOD: str = ""          # set by _verify_model()
_MODEL = None                       # lazy singleton


def _verify_model() -> None:
    """Load the model once and confirm it produces non-trivial output."""
    global _MODEL, EMBEDDING_METHOD
    try:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer("all-MiniLM-L6-v2")
        test_vec = m.encode(["hello world"])
        assert test_vec.shape == (1, 384), f"Unexpected shape: {test_vec.shape}"
        assert test_vec[0].any(), "Model returned all-zero vector for test input"
        _MODEL = m
        EMBEDDING_METHOD = "sentence-transformers/all-MiniLM-L6-v2 (384-dim)"
        logger.info("Embedding method: %s", EMBEDDING_METHOD)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot load sentence-transformers model: {exc}\n"
            "Fix: ensure 'sentence-transformers' is installed and the model "
            "cache exists at ~/.cache/huggingface/."
        ) from exc


_verify_model()    # fail-fast at import time


def _get_model():
    if _MODEL is None:
        _verify_model()
    return _MODEL


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_snippet(path: str) -> str:
    """Return up to CONTENT_PEEK chars of text from a file."""
    if not is_likely_text(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(CONTENT_PEEK)
    except OSError:
        return ""


def _build_text(path: str) -> str:
    """Compose the text input for embedding: readable filename + content."""
    p = Path(path)
    # Turn filename stem into readable words
    name_words = p.stem.replace("_", " ").replace("-", " ")
    snippet = _read_snippet(path)
    parts = [name_words]
    if snippet:
        parts.append(snippet)
    return " ".join(parts)


def _serialize(vec: np.ndarray) -> bytes:
    return pickle.dumps(vec.astype(np.float32))


def deserialize(blob: bytes) -> Optional[np.ndarray]:
    """Deserialise an embedding blob; returns None if blob is falsy."""
    if not blob:
        return None
    try:
        return pickle.loads(blob)
    except Exception:
        return None


# ── main entry point ──────────────────────────────────────────────────────────

def embed_all(db_path: str = DB_PATH) -> int:
    """
    Generate embeddings for every file that doesn't have one yet.

    Raises RuntimeError immediately if the embedding count comes out zero
    (meaning the model silently failed on every file).

    Returns the number of files successfully embedded this run.
    """
    model = _get_model()
    conn = get_connection(db_path)

    rows = conn.execute(
        "SELECT path FROM files WHERE embedding IS NULL"
    ).fetchall()

    if not rows:
        logger.info("No new files to embed.")
        total = conn.execute("SELECT COUNT(*) FROM files WHERE embedding IS NOT NULL").fetchone()[0]
        conn.close()
        return total

    paths = [r["path"] for r in rows]
    texts = [_build_text(p) for p in paths]

    logger.info("Embedding %d file(s) via %s …", len(paths), EMBEDDING_METHOD)
    vecs = model.encode(texts, show_progress_bar=True, batch_size=32)

    if not vecs.any():
        raise RuntimeError(
            "Embedding model returned all-zero vectors for all files. "
            "This is a bug — check the model installation."
        )

    embedded = 0
    for path, vec in zip(paths, vecs):
        if not vec.any():
            logger.error("Zero-vector for %s — skipping (check content).", path)
            continue
        conn.execute(
            "UPDATE files SET embedding = ? WHERE path = ?",
            (_serialize(vec), path),
        )
        embedded += 1

    conn.commit()
    conn.close()

    if embedded == 0:
        raise RuntimeError(
            "Embedded 0 files — every embedding was a zero-vector. "
            "Cannot proceed to scorer.py."
        )

    logger.info(
        "Embedded %d / %d file(s) successfully. Method: %s",
        embedded, len(paths), EMBEDDING_METHOD,
    )
    total = conn.execute("SELECT COUNT(*) FROM files WHERE embedding IS NOT NULL").fetchone()[0]
    return total
