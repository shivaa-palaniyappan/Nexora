"""
repo.py — API routes for submitting and managing repositories.

POST /api/process-repo  → start indexing a GitHub URL
GET  /api/repos         → list all repos
DELETE /api/repo/{id}   → delete a repo's index
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
import hashlib
import re

from app.core.database import create_job, get_all_jobs, get_job
from app.core import vector_store
from app.workers.indexer import start_indexing

router = APIRouter()


class ProcessRepoRequest(BaseModel):
    github_url: str


def make_repo_id(url: str) -> str:
    """Create a short stable ID from a GitHub URL."""
    # Extract owner/repo from URL: github.com/owner/repo
    match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/.*)?$", url)
    if match:
        slug = match.group(1).replace("/", "-").lower()
        # Add short hash to handle same repo re-indexing
        short_hash = hashlib.md5(url.encode()).hexdigest()[:6]
        return f"{slug}-{short_hash}"
    # Fallback: hash the whole URL
    return hashlib.md5(url.encode()).hexdigest()[:16]


@router.post("/process-repo")
async def process_repo(body: ProcessRepoRequest):
    """
    Submit a GitHub repo for indexing.
    Returns immediately with a repo_id.
    The actual indexing happens in a background thread.
    Poll GET /api/status/{repo_id} to track progress.
    """
    url = body.github_url.strip()

    # Basic validation
    if not url.startswith("https://github.com/"):
        raise HTTPException(
            status_code=400,
            detail="Please provide a valid GitHub URL "
                   "(https://github.com/owner/repo)"
        )

    repo_id = make_repo_id(url)

    # Check if already processing
    existing = get_job(repo_id)
    if existing and existing["status"] in ("cloning", "scanning", "indexing"):
        return {
            "repo_id": repo_id,
            "status": existing["status"],
            "message": "This repo is already being processed.",
        }

    # Create job record in SQLite
    create_job(repo_id, url)

    # Start background indexing (non-blocking)
    start_indexing(repo_id, url)

    return {
        "repo_id":  repo_id,
        "status":   "pending",
        "message":  "Indexing started. Poll /api/status/{repo_id} for progress.",
    }


@router.get("/repos")
def list_repos():
    """List all indexed/processing repos."""
    jobs = get_all_jobs()
    return {"repos": jobs}


@router.delete("/repo/{repo_id}")
def delete_repo(repo_id: str):
    """Delete all indexed data for a repo."""
    vector_store.delete_collection(repo_id)
    return {"message": f"Repo {repo_id} deleted from index."}
