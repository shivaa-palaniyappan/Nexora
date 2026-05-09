"""
embedder.py — Converts text into vectors (lists of numbers) using a
FREE local model. No API key needed. Runs entirely on the server.

Model: all-MiniLM-L6-v2
- Size: ~90MB
- Speed: fast even on CPU
- Quality: excellent for code search
"""

from sentence_transformers import SentenceTransformer
from typing import List
import logging

logger = logging.getLogger(__name__)

# Load once at module level — stays in memory for fast repeated use
_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model (first time ~10 seconds)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model ready.")
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Takes a list of text strings.
    Returns a list of embedding vectors.
    Each vector is a list of 384 floats.
    """
    if not texts:
        return []
    model = get_model()
    # convert_to_numpy=True then .tolist() gives us plain Python floats
    embeddings = model.encode(texts, show_progress_bar=False,
                              convert_to_numpy=True)
    return embeddings.tolist()


def embed_single(text: str) -> List[float]:
    """Embed a single string. Used for query-time search."""
    return embed_texts([text])[0]
