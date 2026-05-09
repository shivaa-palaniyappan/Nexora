"""
query.py — Now uses the precision query engine instead of pure vector search.

Flow:
1. Classify the question (WHERE / HOW / EXPLAIN / CALLS / etc.)
2. Query the code graph for exact symbols and relationships
3. Optionally get repo map for architecture context
4. Send precise context to Groq
5. Return answer with exact file + line sources
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.query_engine import answer_question
from app.core.groq_client import ask_groq_with_context
from app.core.database import get_job
from app.core import vector_store

router = APIRouter()


class AskRequest(BaseModel):
    repo_id: str
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list
    repo_id: str
    question: str
    question_type: str


@router.post("/ask", response_model=AskResponse)
async def ask_question(body: AskRequest):
    repo_id  = body.repo_id.strip()
    question = body.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    job = get_job(repo_id)
    if not job:
        raise HTTPException(status_code=404,
            detail=f"Repo '{repo_id}' not found. Process it first.")

    if job["status"] not in ("completed", "indexing", "analyzing"):
        raise HTTPException(status_code=400,
            detail=f"Repo not ready. Status: {job['status']}")

    # Get repo map for architecture context
    repo_map = _get_repo_map(repo_id)

    # Run the precision query engine
    try:
        context, sources = answer_question(repo_id, question, repo_map)
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"Query engine error: {str(e)}")

    # Determine question type for response metadata
    from app.core.query_engine import classify_question
    intent = classify_question(question)

    # Send to Groq with the precision context
    answer = await ask_groq_with_context(question, context, intent.question_type)

    return AskResponse(
        answer=answer,
        sources=sources,
        repo_id=repo_id,
        question=question,
        question_type=intent.question_type,
    )


def _get_repo_map(repo_id: str) -> Optional[str]:
    """Fetch the stored repo architecture map text."""
    try:
        collection = vector_store.get_collection(repo_id)
        result = collection.get(
            ids=[f"{repo_id}::__repo_map__"],
            include=["documents"]
        )
        docs = result.get("documents", [])
        if docs and docs[0]:
            return docs[0]
    except Exception:
        pass
    return None
