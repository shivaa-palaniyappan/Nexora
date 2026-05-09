"""
database.py — Tracks every indexing job using SQLite (free, built into Python).
Stores: repo_id, status, total files, processed files, failed files.
This is what powers the GET /status/{repo_id} endpoint.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "./data/jobs.db")


def init_db():
    """Creates the jobs table if it does not exist yet."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                repo_id         TEXT PRIMARY KEY,
                repo_url        TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                total_files     INTEGER DEFAULT 0,
                processed_files INTEGER DEFAULT 0,
                failed_files    INTEGER DEFAULT 0,
                last_file       TEXT DEFAULT NULL,
                error_message   TEXT DEFAULT NULL,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.commit()


def create_job(repo_id: str, repo_url: str) -> dict:
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jobs
            (repo_id, repo_url, status, total_files, processed_files,
             failed_files, last_file, created_at, updated_at)
            VALUES (?, ?, 'pending', 0, 0, 0, NULL, ?, ?)
        """, (repo_id, repo_url, now, now))
        conn.commit()
    return get_job(repo_id)


def update_job(repo_id: str, **kwargs):
    """Update any fields on a job. Pass keyword args like status='processing'."""
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [repo_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE jobs SET {fields} WHERE repo_id = ?", values)
        conn.commit()


def get_job(repo_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE repo_id = ?", (repo_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_jobs() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
