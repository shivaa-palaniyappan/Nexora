"""
code_graph.py — Stores every symbol and relationship in SQLite.

This is the core of precision. Instead of "find similar text", we do:
  - "find the function named login_user"          → exact match, instant
  - "find all functions that call login_user"     → graph traversal
  - "find where AuthService is defined"           → symbol table lookup
  - "find all files that import from auth.py"     → dependency graph

Schema:
  symbols   — every function, class in the codebase
  calls     — who calls who (call graph)
  imports   — what imports what (dependency graph)
  summaries — AI-generated summary of each important file
"""

import sqlite3
import os
import json
import logging
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

from app.core.ast_parser import FileSymbols, FunctionDef, ClassDef

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("GRAPH_DB_PATH", "./data/code_graph.db")


# ─────────────────────────────────────────────────────────────────────────────
# Schema setup
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
-- Every function and class ever seen
CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,   -- 'function', 'class', 'method'
    file        TEXT NOT NULL,
    line_start  INTEGER NOT NULL,
    line_end    INTEGER,
    language    TEXT,
    class_name  TEXT,            -- if this is a method, parent class name
    parameters  TEXT,            -- JSON array of param names
    return_type TEXT,
    docstring   TEXT,
    decorators  TEXT,            -- JSON array
    source_code TEXT,            -- actual source lines
    importance  REAL DEFAULT 0.5
);

-- Call graph: function A calls function B
CREATE TABLE IF NOT EXISTS calls (
    repo_id     TEXT NOT NULL,
    caller_file TEXT NOT NULL,
    caller_name TEXT NOT NULL,
    caller_line INTEGER,
    callee_name TEXT NOT NULL    -- what is being called
);

-- Import graph: file A imports from module B
CREATE TABLE IF NOT EXISTS imports (
    repo_id     TEXT NOT NULL,
    file        TEXT NOT NULL,
    line        INTEGER,
    module      TEXT NOT NULL,
    names       TEXT             -- JSON array of imported names
);

-- File summaries (generated once per file, reused forever)
CREATE TABLE IF NOT EXISTS file_summaries (
    repo_id     TEXT NOT NULL,
    file        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    importance  REAL,
    language    TEXT,
    PRIMARY KEY (repo_id, file)
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_symbols_repo   ON symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name   ON symbols(repo_id, name);
CREATE INDEX IF NOT EXISTS idx_symbols_file   ON symbols(repo_id, file);
CREATE INDEX IF NOT EXISTS idx_calls_repo     ON calls(repo_id);
CREATE INDEX IF NOT EXISTS idx_calls_caller   ON calls(repo_id, caller_name);
CREATE INDEX IF NOT EXISTS idx_calls_callee   ON calls(repo_id, callee_name);
CREATE INDEX IF NOT EXISTS idx_imports_repo   ON imports(repo_id);
CREATE INDEX IF NOT EXISTS idx_imports_file   ON imports(repo_id, file);
"""


def init_graph_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # faster concurrent writes
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Write operations — called during indexing
# ─────────────────────────────────────────────────────────────────────────────

def store_file_symbols(repo_id: str, symbols: FileSymbols,
                        importance: float = 0.5):
    """Store all symbols from one parsed file into the graph DB."""
    with get_conn() as conn:

        # Store functions
        for fn in symbols.functions:
            conn.execute("""
                INSERT INTO symbols
                (repo_id, name, kind, file, line_start, line_end, language,
                 class_name, parameters, return_type, docstring,
                 decorators, source_code, importance)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                repo_id,
                fn.name,
                'method' if fn.is_method else 'function',
                fn.file,
                fn.line_start,
                fn.line_end,
                fn.language,
                fn.class_name,
                json.dumps(fn.parameters),
                fn.return_type,
                fn.docstring,
                json.dumps(fn.decorators),
                fn.source_code,
                importance,
            ))

            # Store call edges
            for callee in fn.calls:
                conn.execute("""
                    INSERT INTO calls
                    (repo_id, caller_file, caller_name, caller_line, callee_name)
                    VALUES (?,?,?,?,?)
                """, (repo_id, fn.file, fn.name, fn.line_start, callee))

        # Store classes
        for cls in symbols.classes:
            conn.execute("""
                INSERT INTO symbols
                (repo_id, name, kind, file, line_start, line_end,
                 language, parameters, importance)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                repo_id, cls.name, 'class',
                cls.file, cls.line_start, cls.line_end,
                cls.language,
                json.dumps(cls.parent_classes),
                importance,
            ))

        # Store imports
        for imp in symbols.imports:
            conn.execute("""
                INSERT INTO imports (repo_id, file, line, module, names)
                VALUES (?,?,?,?,?)
            """, (
                repo_id, imp.file, imp.line,
                imp.module, json.dumps(imp.names),
            ))


def store_file_summary(repo_id: str, file: str, summary: str,
                        importance: float, language: str):
    """Store an AI-generated summary for a file."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO file_summaries
            (repo_id, file, summary, importance, language)
            VALUES (?,?,?,?,?)
        """, (repo_id, file, summary, importance, language))


def delete_repo_graph(repo_id: str):
    """Remove all graph data for a repo (for re-indexing)."""
    with get_conn() as conn:
        for table in ('symbols', 'calls', 'imports', 'file_summaries'):
            conn.execute(f"DELETE FROM {table} WHERE repo_id = ?", (repo_id,))


# ─────────────────────────────────────────────────────────────────────────────
# Read operations — called during query time
# ─────────────────────────────────────────────────────────────────────────────

def find_symbol_exact(repo_id: str, name: str) -> List[Dict]:
    """
    Find a symbol by EXACT name.
    This is what gives you "exact file, exact line."
    Query: "where is login_user" → finds it instantly.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT name, kind, file, line_start, line_end,
                   language, class_name, docstring, source_code, importance
            FROM symbols
            WHERE repo_id = ? AND LOWER(name) = LOWER(?)
            ORDER BY importance DESC
            LIMIT 10
        """, (repo_id, name)).fetchall()
        return [dict(r) for r in rows]


def find_symbol_fuzzy(repo_id: str, name: str) -> List[Dict]:
    """
    Find symbols where the name CONTAINS the search term.
    Query: "auth" → finds authenticate, AuthService, auth_check, etc.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT name, kind, file, line_start, line_end,
                   language, class_name, docstring, source_code, importance
            FROM symbols
            WHERE repo_id = ? AND LOWER(name) LIKE LOWER(?)
            ORDER BY importance DESC
            LIMIT 20
        """, (repo_id, f"%{name}%")).fetchall()
        return [dict(r) for r in rows]


def find_callers(repo_id: str, function_name: str) -> List[Dict]:
    """
    Find all functions that CALL a given function.
    Query: "what calls process_payment" → exact list.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT c.caller_name, c.caller_file, c.caller_line,
                   s.source_code, s.line_start
            FROM calls c
            LEFT JOIN symbols s ON (
                s.repo_id = c.repo_id
                AND s.name = c.caller_name
                AND s.file = c.caller_file
            )
            WHERE c.repo_id = ? AND LOWER(c.callee_name) = LOWER(?)
            LIMIT 15
        """, (repo_id, function_name)).fetchall()
        return [dict(r) for r in rows]


def find_callees(repo_id: str, function_name: str) -> List[Dict]:
    """
    Find all functions that a given function CALLS.
    Query: "what does login call" → exact list.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT c.callee_name,
                   s.file, s.line_start, s.source_code, s.kind
            FROM calls c
            LEFT JOIN symbols s ON (
                s.repo_id = c.repo_id
                AND LOWER(s.name) = LOWER(c.callee_name)
            )
            WHERE c.repo_id = ? AND LOWER(c.caller_name) = LOWER(?)
            LIMIT 15
        """, (repo_id, function_name)).fetchall()
        return [dict(r) for r in rows]


def find_in_file(repo_id: str, file_path: str) -> List[Dict]:
    """Get all symbols defined in a specific file."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT name, kind, file, line_start, line_end,
                   language, class_name, docstring, source_code
            FROM symbols
            WHERE repo_id = ? AND file LIKE ?
            ORDER BY line_start
        """, (repo_id, f"%{file_path}%")).fetchall()
        return [dict(r) for r in rows]


def get_top_symbols(repo_id: str, limit: int = 30) -> List[Dict]:
    """
    Get the most important symbols across the whole repo.
    Used for "explain the core logic" type questions.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT name, kind, file, line_start, line_end,
                   language, class_name, docstring, source_code, importance
            FROM symbols
            WHERE repo_id = ? AND kind IN ('function', 'class')
            ORDER BY importance DESC, length(source_code) DESC
            LIMIT ?
        """, (repo_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_file_summaries(repo_id: str, limit: int = 10) -> List[Dict]:
    """Get pre-built summaries of the most important files."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT file, summary, importance, language
            FROM file_summaries
            WHERE repo_id = ?
            ORDER BY importance DESC
            LIMIT ?
        """, (repo_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_repo_stats(repo_id: str) -> Dict:
    """Summary statistics about what has been indexed."""
    with get_conn() as conn:
        total_symbols = conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo_id = ?", (repo_id,)
        ).fetchone()[0]
        total_calls = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE repo_id = ?", (repo_id,)
        ).fetchone()[0]
        total_files = conn.execute(
            "SELECT COUNT(DISTINCT file) FROM symbols WHERE repo_id = ?", (repo_id,)
        ).fetchone()[0]
        languages = conn.execute(
            "SELECT language, COUNT(*) as cnt FROM symbols WHERE repo_id = ? "
            "GROUP BY language ORDER BY cnt DESC LIMIT 5",
            (repo_id,)
        ).fetchall()

    return {
        "total_symbols": total_symbols,
        "total_calls":   total_calls,
        "total_files":   total_files,
        "languages":     [dict(r) for r in languages],
    }
