"""
status.py — Progress tracking endpoint.
Frontend polls this every 2 seconds to show a live progress bar.
"""

from fastapi import APIRouter, HTTPException
from app.core.database import get_job, get_all_jobs
from app.core.vector_store import collection_size

router = APIRouter()


@router.get("/status/{repo_id}")
def get_status(repo_id: str):
    """
    Returns live progress for a repo indexing job.

    Example response:
    {
        "repo_id": "my-repo-abc123",
        "status": "indexing",
        "total_files": 1200,
        "processed_files": 340,
        "failed_files": 2,
        "progress_pct": 28,
        "chunks_indexed": 4821
    }
    """
    job = get_job(repo_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"No job found for repo_id: {repo_id}"
        )

    total     = job.get("total_files", 0)
    processed = job.get("processed_files", 0)
    pct = round((processed / total * 100) if total > 0 else 0)

    return {
        "repo_id":         repo_id,
        "repo_url":        job.get("repo_url"),
        "status":          job.get("status"),
        "total_files":     total,
        "processed_files": processed,
        "failed_files":    job.get("failed_files", 0),
        "progress_pct":    pct,
        "chunks_indexed":  collection_size(repo_id),
        "last_file":       job.get("last_file"),
        "error_message":   job.get("error_message"),
        "created_at":      job.get("created_at"),
        "updated_at":      job.get("updated_at"),
    }
