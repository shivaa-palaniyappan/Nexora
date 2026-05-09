"""
vector_store.py — Manages the ChromaDB vector database.
Each repository gets its own collection (like its own drawer).
Stores: code chunks + their embeddings + metadata (file, line numbers).
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")

# One shared ChromaDB client for the whole app
_client = None


def get_client() -> chromadb.Client:
    global _client
    if _client is None:
        os.makedirs(CHROMA_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def get_collection(repo_id: str):
    """Get or create a collection for a specific repo."""
    client = get_client()
    return client.get_or_create_collection(
        name=f"repo_{repo_id}",
        metadata={"hnsw:space": "cosine"}   # cosine similarity for text
    )


def delete_collection(repo_id: str):
    """Delete all indexed data for a repo (for re-indexing)."""
    try:
        client = get_client()
        client.delete_collection(f"repo_{repo_id}")
    except Exception:
        pass  # Collection didn't exist — that's fine


def add_chunks(repo_id: str, chunks: List[Dict[str, Any]]):
    """
    Store a batch of code chunks with their embeddings.

    Each chunk dict must have:
      - id:        unique string ID
      - text:      the raw code text
      - embedding: list of floats from the embedder
      - metadata:  dict with file, start_line, language, etc.
    """
    if not chunks:
        return

    collection = get_collection(repo_id)

    ids        = [c["id"]        for c in chunks]
    documents  = [c["text"]      for c in chunks]
    embeddings = [c["embedding"] for c in chunks]
    metadatas  = [c["metadata"]  for c in chunks]

    # ChromaDB upsert = insert if new, update if exists
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def search(repo_id: str, query_embedding: List[float],
           top_k: int = 6) -> List[Dict[str, Any]]:
    """
    Find the top_k most relevant code chunks for a query.
    Returns list of dicts with text, metadata, and similarity distance.
    """
    collection = get_collection(repo_id)

    # Check collection is not empty
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text":      doc,
            "file":      meta.get("file", "unknown"),
            "start_line": meta.get("start_line", 0),
            "language":  meta.get("language", ""),
            "score":     round(1 - dist, 4),  # convert distance → similarity
        })

    return chunks


def collection_size(repo_id: str) -> int:
    """How many chunks are indexed for this repo."""
    try:
        return get_collection(repo_id).count()
    except Exception:
        return 0
