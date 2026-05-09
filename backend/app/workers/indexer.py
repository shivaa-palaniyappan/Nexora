"""
indexer.py — Builds AST code graph during indexing.
"""

import threading
import logging
import traceback
import os
import httpx

from app.core.database import update_job, get_job
from app.core.github import (
    clone_repo, collect_files, read_file_safe,
    cleanup_repo, iter_batches, BATCH_SIZE
)
from app.core.chunker import chunk_content
from app.core.embedder import embed_texts
from app.core import vector_store
from app.core import code_graph                          # ← fixes "not defined" error
from app.core.repo_intel import analyze_repo, get_file_score, build_repo_map_chunk
from app.core.ast_parser import parse_file
from app.core.code_graph import (
    init_graph_db, store_file_symbols,
    store_file_summary, delete_repo_graph
)

logger = logging.getLogger(__name__)

MIN_SCORE_THRESHOLD     = 0.15
SUMMARY_SCORE_THRESHOLD = 0.7
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


def _sync_generate_summary(content: str, filepath: str) -> str:
    """Generate a 3-sentence file summary using Groq."""
    if not GROQ_API_KEY:
        return ""
    prompt = (
        f"Summarize this code file in exactly 3 sentences. "
        f"Include: what it does, key functions/classes, and its role.\n\n"
        f"File: {filepath}\n\n```\n{content[:3000]}\n```"
    )
    try:
        import httpx as _httpx
        resp = _httpx.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "max_tokens": 200,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug(f"Summary failed for {filepath}: {e}")
    return ""


def process_repo(repo_id: str, github_url: str):
    repo_path = None
    try:
        # Phase 1: Clone
        update_job(repo_id, status="cloning")
        repo_path = clone_repo(repo_id, github_url)

        # Phase 2: Intelligence analysis
        update_job(repo_id, status="analyzing")
        intel = analyze_repo(repo_path, repo_id)
        logger.info(f"[{repo_id}] Detected: {intel.project_type} | "
                    f"Frameworks: {intel.frameworks}")

        # Store repo map chunk immediately
        try:
            map_chunk = build_repo_map_chunk(intel, repo_id, repo_path)
            vector_store.add_chunks(repo_id, [map_chunk])
        except Exception as e:
            logger.warning(f"[{repo_id}] Repo map error: {e}")

        # Phase 3: Collect and prioritize files
        update_job(repo_id, status="scanning")
        all_files     = collect_files(repo_path)
        sorted_files  = sorted(all_files, key=lambda f: -get_file_score(intel, f))
        filtered_files = [
            f for f in sorted_files
            if get_file_score(intel, f) >= MIN_SCORE_THRESHOLD
        ]
        total = len(filtered_files)
        logger.info(f"[{repo_id}] {total} files to index")

        if total == 0:
            update_job(repo_id, status="completed",
                       total_files=0, processed_files=0)
            return

        update_job(repo_id, status="indexing", total_files=total)

        # Clear old graph data
        delete_repo_graph(repo_id)

        # Phase 4: Resume check
        job          = get_job(repo_id)
        already_done = job.get("processed_files", 0) if job else 0
        processed    = already_done
        failed       = job.get("failed_files", 0) if job else 0

        if already_done > 0:
            filtered_files = filtered_files[already_done:]

        # Phase 5: Process each file
        for batch in iter_batches(filtered_files, BATCH_SIZE):
            batch_chunks = []

            for rel_path in batch:
                try:
                    content = read_file_safe(repo_path, rel_path)
                    if content is None:
                        failed += 1
                        continue

                    importance = get_file_score(intel, rel_path)

                    # AST parsing → code graph
                    symbols = parse_file(content, rel_path)
                    if symbols.functions or symbols.classes:
                        store_file_symbols(repo_id, symbols, importance)

                    # File summary for important files
                    if importance >= SUMMARY_SCORE_THRESHOLD and GROQ_API_KEY:
                        summary = _sync_generate_summary(content, rel_path)
                        if summary:
                            store_file_summary(
                                repo_id, rel_path, summary,
                                importance, symbols.language
                            )

                    # ChromaDB chunks for semantic fallback
                    chunks = chunk_content(content, rel_path, repo_id)
                    if chunks:
                        texts      = [c["text"] for c in chunks]
                        embeddings = embed_texts(texts)
                        for chunk, emb in zip(chunks, embeddings):
                            chunk["embedding"] = emb
                            chunk["metadata"]["importance"] = str(
                                round(importance, 3)
                            )
                            batch_chunks.append(chunk)

                    processed += 1
                    logger.debug(
                        f"[{repo_id}] {rel_path} | "
                        f"fns={len(symbols.functions)} "
                        f"cls={len(symbols.classes)} "
                        f"score={importance:.2f}"
                    )

                except Exception as e:
                    logger.warning(f"[{repo_id}] Failed {rel_path}: {e}")
                    failed += 1

            if batch_chunks:
                try:
                    vector_store.add_chunks(repo_id, batch_chunks)
                except Exception as e:
                    logger.error(f"[{repo_id}] ChromaDB write error: {e}")

            update_job(
                repo_id,
                processed_files=processed,
                failed_files=failed,
                last_file=batch[-1] if batch else None,
            )
            logger.info(f"[{repo_id}] Progress: {processed}/{total}")

        # Phase 6: Done
        stats = code_graph.get_repo_stats(repo_id)
        logger.info(
            f"[{repo_id}] Complete! "
            f"Symbols: {stats['total_symbols']} | "
            f"Call edges: {stats['total_calls']} | "
            f"Files: {stats['total_files']}"
        )
        update_job(repo_id, status="completed",
                   processed_files=processed, failed_files=failed)

    except Exception as e:
        logger.error(f"[{repo_id}] Fatal: {e}\n{traceback.format_exc()}")
        update_job(repo_id, status="failed", error_message=str(e))

    finally:
        if repo_path:
            try:
                cleanup_repo(repo_id)
            except Exception:
                pass


def start_indexing(repo_id: str, github_url: str):
    thread = threading.Thread(
        target=process_repo, args=(repo_id, github_url),
        daemon=True, name=f"indexer-{repo_id}"
    )
    thread.start()
