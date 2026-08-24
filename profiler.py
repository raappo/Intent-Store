"""
profiler.py — Generates semantic embeddings for each file using
sentence-transformers (all-MiniLM-L6-v2) from filename + first ~500 chars
of readable text content.  Stores the embedding as a binary blob in SQLite.
"""

import json
import logging
import pickle
import sqlite3
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer

from scanner import get_connection, is_likely_text, DB_PATH

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
CONTENT_PEEK = 500          # bytes to read for semantic context
_model: Optional[SentenceTransformer] = None


def _get_model() -> SentenceTransformer:
    """Lazily load and cache the embedding model."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformer model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _build_text_snippet(path: str) -> str:
    """
    Compose the text that will be embedded:
      '<filename>: <first CONTENT_PEEK chars of text content>'

    Binaries are represented by their filename only.
    """
    filename = Path(path).name
    content = ""
    if is_likely_text(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(CONTENT_PEEK)
        except OSError as exc:
            logger.debug("Cannot read %s: %s", path, exc)
    return f"{filename}: {content}".strip()


def _serialize_embedding(vec) -> bytes:
    return pickle.dumps(vec)


def embed_all(db_path: str = DB_PATH) -> int:
    """
    Generate and store embeddings for all files that do not yet have one.

    Returns the number of files embedded this run.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    rows = cursor.execute(
        "SELECT path FROM files WHERE embedding IS NULL"
    ).fetchall()

    if not rows:
        logger.info("All files already have embeddings.")
        conn.close()
        return 0

    model = _get_model()
    paths = [r["path"] for r in rows]
    snippets = [_build_text_snippet(p) for p in paths]

    logger.info("Embedding %d files …", len(paths))
    vectors = model.encode(snippets, show_progress_bar=True, batch_size=64)

    for path, vec in zip(paths, vectors):
        conn.execute(
            "UPDATE files SET embedding = ? WHERE path = ?",
            (_serialize_embedding(vec), path),
        )

    conn.commit()
    conn.close()
    logger.info("Embedded %d files.", len(paths))
    return len(paths)
