"""
repo_intel.py — The "brain" that understands any codebase before indexing it.

This runs ONCE per repo, right after cloning, before any chunking happens.
It does 3 things automatically for ANY repo:

1. DETECTS what kind of project it is (Python/Java/React/etc.)
2. SCORES every file by importance (0.0 to 1.0)
3. BUILDS a repo map — a plain-English summary of what the project does
   and where key things live (auth, DB, API, etc.)

The repo map gets stored in ChromaDB as a special "meta" chunk with very
high importance so it ALWAYS appears in search results, giving Claude
permanent context about the project architecture.

This completely eliminates hallucination caused by missing context.
"""

import os
import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FileScore:
    path: str
    score: float          # 0.0 (irrelevant) → 1.0 (critical)
    reason: str           # Why this score was assigned
    category: str         # "entrypoint", "config", "core", "test", "ui", etc.
    language: str


@dataclass
class RepoIntelligence:
    repo_id: str
    project_type: str                    # "python-fastapi", "react", "java-spring", etc.
    primary_language: str
    frameworks: List[str]
    entry_points: List[str]             # Files where execution starts
    key_directories: Dict[str, str]     # dir → what it contains
    architecture_summary: str           # Plain English description
    file_scores: Dict[str, FileScore]   # path → score info
    important_patterns: List[str]       # Regex patterns that indicate importance
    total_files: int
    indexed_files: int


# ─────────────────────────────────────────────────────────────────────────────
# Project type detection
# ─────────────────────────────────────────────────────────────────────────────

# Signatures: filename → (project_type, framework)
PROJECT_SIGNATURES = {
    # Python
    "requirements.txt":      ("python", "generic"),
    "pyproject.toml":        ("python", "modern"),
    "setup.py":              ("python", "setuptools"),
    "manage.py":             ("python", "django"),
    "app.py":                ("python", "flask/fastapi"),
    "main.py":               ("python", "generic"),
    "wsgi.py":               ("python", "wsgi"),
    "asgi.py":               ("python", "asgi"),
    # JavaScript / TypeScript
    "package.json":          ("javascript", "node"),
    "next.config.js":        ("javascript", "nextjs"),
    "next.config.mjs":       ("javascript", "nextjs"),
    "nuxt.config.js":        ("javascript", "nuxtjs"),
    "vite.config.ts":        ("javascript", "vite"),
    "angular.json":          ("javascript", "angular"),
    "vue.config.js":         ("javascript", "vue"),
    # Java
    "pom.xml":               ("java", "maven"),
    "build.gradle":          ("java", "gradle"),
    "build.gradle.kts":      ("java", "gradle-kotlin"),
    # Go
    "go.mod":                ("go", "modules"),
    "go.sum":                ("go", "modules"),
    # Rust
    "Cargo.toml":            ("rust", "cargo"),
    # Ruby
    "Gemfile":               ("ruby", "bundler"),
    "config.ru":             ("ruby", "rack"),
    # PHP
    "composer.json":         ("php", "composer"),
    "artisan":               ("php", "laravel"),
    # C/C++
    "CMakeLists.txt":        ("cpp", "cmake"),
    "Makefile":              ("c/cpp", "make"),
}

# Framework detection from file content patterns
FRAMEWORK_PATTERNS = {
    "fastapi":   [r"from fastapi", r"import fastapi", r"FastAPI\(\)"],
    "flask":     [r"from flask", r"import Flask", r"Flask\(__name__\)"],
    "django":    [r"from django", r"import django", r"DJANGO_SETTINGS"],
    "express":   [r"require\('express'\)", r"from 'express'", r"express\(\)"],
    "spring":    [r"@SpringBootApplication", r"@RestController", r"@Service"],
    "react":     [r"import React", r"from 'react'", r"useState\(", r"useEffect\("],
    "vue":       [r"<template>", r"defineComponent", r"createApp\("],
    "nextjs":    [r"getServerSideProps", r"getStaticProps", r"NextPage"],
    "sqlalchemy":[r"from sqlalchemy", r"declarative_base", r"Column\("],
    "prisma":    [r"PrismaClient", r"@prisma/client"],
    "mongoose":  [r"mongoose.model", r"mongoose.Schema"],
}


# ─────────────────────────────────────────────────────────────────────────────
# File importance scoring
# ─────────────────────────────────────────────────────────────────────────────

# Base scores by filename (exact match, case-insensitive)
FILENAME_SCORES = {
    # Critical — always score 1.0
    "readme.md":         (1.0, "entrypoint", "Project documentation root"),
    "readme.txt":        (1.0, "entrypoint", "Project documentation root"),
    "main.py":           (1.0, "entrypoint", "Python main entry point"),
    "app.py":            (1.0, "entrypoint", "Application entry point"),
    "index.js":          (1.0, "entrypoint", "JS main entry point"),
    "index.ts":          (1.0, "entrypoint", "TS main entry point"),
    "main.java":         (1.0, "entrypoint", "Java main class"),
    "main.go":           (1.0, "entrypoint", "Go main entry point"),
    "main.rs":           (1.0, "entrypoint", "Rust main entry point"),
    "server.py":         (0.95, "entrypoint", "Server entry point"),
    "server.js":         (0.95, "entrypoint", "Server entry point"),
    "server.ts":         (0.95, "entrypoint", "Server entry point"),
    "manage.py":         (0.95, "entrypoint", "Django management"),
    "wsgi.py":           (0.9, "entrypoint", "WSGI entry point"),
    "asgi.py":           (0.9, "entrypoint", "ASGI entry point"),
    # Config — high importance
    "package.json":      (0.9, "config", "JS project config and dependencies"),
    "requirements.txt":  (0.9, "config", "Python dependencies"),
    "pyproject.toml":    (0.9, "config", "Python project config"),
    "pom.xml":           (0.9, "config", "Maven project config"),
    "build.gradle":      (0.9, "config", "Gradle build config"),
    "cargo.toml":        (0.9, "config", "Rust project config"),
    "go.mod":            (0.9, "config", "Go module config"),
    "dockerfile":        (0.85, "config", "Docker build config"),
    "docker-compose.yml":(0.85, "config", "Docker compose config"),
    ".env.example":      (0.8, "config", "Environment variables template"),
    "settings.py":       (0.85, "config", "Application settings"),
    "config.py":         (0.85, "config", "Configuration file"),
    "config.ts":         (0.85, "config", "Configuration file"),
    # Architecture files
    "models.py":         (0.85, "core", "Data models"),
    "schema.py":         (0.85, "core", "Data schema"),
    "schemas.py":        (0.85, "core", "Data schemas"),
    "database.py":       (0.85, "core", "Database setup"),
    "db.py":             (0.85, "core", "Database utilities"),
    "auth.py":           (0.9, "core", "Authentication logic"),
    "auth.ts":           (0.9, "core", "Authentication logic"),
    "authentication.py": (0.9, "core", "Authentication logic"),
    "middleware.py":     (0.85, "core", "Middleware layer"),
    "router.py":         (0.85, "core", "Route definitions"),
    "routes.py":         (0.85, "core", "Route definitions"),
    "urls.py":           (0.85, "core", "URL routing"),
    "views.py":          (0.8, "core", "View layer"),
    "controllers.py":    (0.85, "core", "Controller layer"),
    "services.py":       (0.85, "core", "Business logic services"),
    "utils.py":          (0.7, "util", "Utility functions"),
    "helpers.py":        (0.65, "util", "Helper functions"),
    "constants.py":      (0.7, "config", "Constants and enums"),
    "exceptions.py":     (0.7, "core", "Custom exceptions"),
    "dependencies.py":   (0.75, "core", "Dependency injection"),
}

# Directory importance multipliers
DIR_MULTIPLIERS = {
    # Core logic — boost
    "src":          1.0,
    "app":          1.0,
    "lib":          0.95,
    "core":         1.1,
    "api":          1.1,
    "auth":         1.2,
    "models":       1.1,
    "services":     1.1,
    "controllers":  1.1,
    "routes":       1.05,
    "middleware":   1.05,
    # Tests — lower importance for answering questions
    "test":         0.5,
    "tests":        0.5,
    "__tests__":    0.5,
    "spec":         0.5,
    "specs":        0.5,
    # UI/Assets — lower unless UI-focused project
    "components":   0.75,
    "pages":        0.8,
    "views":        0.8,
    "assets":       0.3,
    "static":       0.3,
    "public":       0.3,
    "styles":       0.4,
    "css":          0.4,
    # Generated/vendor — very low
    "node_modules": 0.0,
    "dist":         0.1,
    "build":        0.1,
    "target":       0.1,
    "__pycache__":  0.0,
    ".git":         0.0,
    "migrations":   0.6,
}

# Content patterns that boost importance when found inside a file
CONTENT_BOOST_PATTERNS = [
    (r"def\s+\w*auth\w*\(",     0.15, "Contains auth function"),
    (r"def\s+\w*login\w*\(",    0.15, "Contains login function"),
    (r"class\s+\w*Auth\w*",     0.15, "Contains auth class"),
    (r"JWT|jsonwebtoken|bearer", 0.1, "JWT authentication"),
    (r"@app\.route|@router\.",   0.1, "API route definition"),
    (r"@RestController|@GetMapping|@PostMapping", 0.1, "Spring REST controller"),
    (r"CREATE TABLE|ALTER TABLE", 0.1, "Database schema"),
    (r"BaseModel|declarative_base|db\.Model", 0.1, "ORM model definition"),
    (r"class\s+\w+\(.*Model\)",  0.1, "Model class"),
    (r"def\s+main\(",            0.05, "Main function"),
    (r"if __name__.*__main__",   0.05, "Script entry point"),
    (r"\.connect\(|createConnection|engine\.connect", 0.08, "Database connection"),
    (r"@pytest\.fixture|setUp\(self\)", -0.05, "Test setup code"),
    (r"def test_|it\('|describe\('", -0.1, "Test code"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Main intelligence engine
# ─────────────────────────────────────────────────────────────────────────────

class RepoIntelligenceEngine:
    """
    Analyzes a cloned repo once and produces intelligence used during indexing.
    The intelligence improves search quality by:
    1. Giving important files higher embedding priority
    2. Creating a "repo map" chunk that's always included in search context
    3. Detecting the project type so the LLM knows what it's looking at
    """

    def __init__(self, repo_path: str, repo_id: str):
        self.repo_path = Path(repo_path)
        self.repo_id = repo_id

    def analyze(self) -> RepoIntelligence:
        """
        Full analysis pipeline. Returns RepoIntelligence object.
        Takes about 1-3 seconds for most repos.
        """
        logger.info(f"[{self.repo_id}] Analyzing repo intelligence...")

        # Step 1: detect project type from config files
        project_type, primary_lang, frameworks = self._detect_project_type()

        # Step 2: score every file
        all_files = self._collect_all_files()
        file_scores = self._score_all_files(all_files, primary_lang)

        # Step 3: identify key directories
        key_dirs = self._identify_key_directories(all_files)

        # Step 4: find entry points
        entry_points = [
            path for path, fs in file_scores.items()
            if fs.category == "entrypoint"
        ]

        # Step 5: build architecture summary
        summary = self._build_architecture_summary(
            project_type, primary_lang, frameworks,
            entry_points, key_dirs, file_scores
        )

        intel = RepoIntelligence(
            repo_id=self.repo_id,
            project_type=project_type,
            primary_language=primary_lang,
            frameworks=frameworks,
            entry_points=entry_points[:10],
            key_directories=key_dirs,
            architecture_summary=summary,
            file_scores=file_scores,
            important_patterns=[],
            total_files=len(all_files),
            indexed_files=len([f for f, s in file_scores.items() if s.score > 0.1]),
        )

        logger.info(
            f"[{self.repo_id}] Intelligence: {project_type}, "
            f"{len(file_scores)} files scored, "
            f"{len(entry_points)} entry points found"
        )
        return intel

    def _detect_project_type(self) -> Tuple[str, str, List[str]]:
        """Detect language, framework, and project type from config files."""
        detected = {}

        for fname, (lang, framework) in PROJECT_SIGNATURES.items():
            # Check root level first
            if (self.repo_path / fname).exists():
                detected[lang] = (lang, framework)
            # Also check one level deep
            for subdir in self.repo_path.iterdir():
                if subdir.is_dir() and (subdir / fname).exists():
                    detected[lang] = (lang, framework)

        if not detected:
            return ("unknown", "unknown", [])

        # Pick the most likely primary language
        # Priority order
        priority = ["python", "javascript", "java", "go", "rust", "ruby", "php", "cpp"]
        primary_lang = "unknown"
        framework = "generic"
        for lang in priority:
            if lang in detected:
                primary_lang, framework = detected[lang]
                break

        # Detect specific frameworks from file content
        frameworks = [framework]
        frameworks += self._detect_frameworks_from_content()

        # Build project_type string
        project_type = f"{primary_lang}-{framework}" if framework != "generic" else primary_lang

        return (project_type, primary_lang, list(set(frameworks)))

    def _detect_frameworks_from_content(self) -> List[str]:
        """Scan key files for framework-specific imports."""
        found = []
        # Only scan a few key files to keep this fast
        scan_targets = ["main.py", "app.py", "server.py", "index.js",
                        "index.ts", "App.tsx", "App.jsx", "manage.py"]

        for target in scan_targets:
            for fpath in self.repo_path.rglob(target):
                if ".git" in str(fpath) or "node_modules" in str(fpath):
                    continue
                try:
                    content = fpath.read_text(errors="ignore")[:3000]
                    for fw, patterns in FRAMEWORK_PATTERNS.items():
                        if fw not in found:
                            for pat in patterns:
                                if re.search(pat, content):
                                    found.append(fw)
                                    break
                except Exception:
                    continue
        return found

    def _collect_all_files(self) -> List[str]:
        """Walk repo and collect relative paths of all files."""
        files = []
        for fpath in self.repo_path.rglob("*"):
            if not fpath.is_file():
                continue
            rel = str(fpath.relative_to(self.repo_path)).replace("\\", "/")
            # Skip obviously irrelevant directories
            parts = rel.split("/")
            skip = False
            for part in parts[:-1]:
                if part in {".git", "node_modules", "__pycache__",
                            "target", "dist", "build", ".venv", "venv"}:
                    skip = True
                    break
            if not skip:
                files.append(rel)
        return files

    def _score_file(self, rel_path: str, primary_lang: str) -> FileScore:
        """
        Score a single file. Returns a FileScore with 0.0-1.0 importance score.

        Scoring logic (in order):
        1. Start with base score from filename
        2. Apply directory multiplier
        3. Scan file content for important patterns (for small files only)
        4. Cap at 1.0
        """
        parts = rel_path.replace("\\", "/").split("/")
        filename = parts[-1].lower()
        dirs = parts[:-1]

        # ── Base score from filename ──────────────────────────────────────
        base_score = 0.4   # default for any code file
        category = "code"
        reason = "Default code file"

        if filename in FILENAME_SCORES:
            base_score, category, reason = FILENAME_SCORES[filename]
        else:
            # Score by extension
            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
            ext_scores = {
                "py": 0.5, "js": 0.5, "ts": 0.5, "tsx": 0.55, "jsx": 0.55,
                "java": 0.5, "go": 0.5, "rs": 0.5, "cs": 0.5,
                "rb": 0.5, "php": 0.5, "kt": 0.5, "swift": 0.5,
                "sql": 0.6, "sh": 0.4, "yaml": 0.5, "yml": 0.5,
                "json": 0.45, "toml": 0.55, "md": 0.4,
                "css": 0.25, "scss": 0.25, "html": 0.35,
                "txt": 0.2, "lock": 0.1, "png": 0.0, "jpg": 0.0,
                "gif": 0.0, "svg": 0.15, "ico": 0.0, "woff": 0.0,
            }
            if ext in ext_scores:
                base_score = ext_scores[ext]
                reason = f"{ext.upper()} file"

        # ── Directory multiplier ──────────────────────────────────────────
        multiplier = 1.0
        for d in dirs:
            d_lower = d.lower()
            if d_lower in DIR_MULTIPLIERS:
                multiplier = min(multiplier, DIR_MULTIPLIERS[d_lower])
                if DIR_MULTIPLIERS[d_lower] > 1.0:
                    multiplier = DIR_MULTIPLIERS[d_lower]

        score = base_score * multiplier

        # ── Content scanning (only for code files under 50KB) ────────────
        if score > 0.2 and base_score > 0.3:
            abs_path = self.repo_path / rel_path
            try:
                file_size = abs_path.stat().st_size
                if file_size < 50_000:   # only scan small-medium files
                    content = abs_path.read_text(errors="ignore")[:5000]
                    for pattern, boost, boost_reason in CONTENT_BOOST_PATTERNS:
                        if re.search(pattern, content, re.IGNORECASE):
                            score += boost
                            if boost > 0:
                                reason = boost_reason
            except Exception:
                pass

        # ── Final clamp ──────────────────────────────────────────────────
        score = max(0.0, min(1.0, score))

        return FileScore(
            path=rel_path,
            score=round(score, 3),
            reason=reason,
            category=category,
            language=primary_lang,
        )

    def _score_all_files(self, files: List[str],
                          primary_lang: str) -> Dict[str, FileScore]:
        """Score every file. Returns dict of path → FileScore."""
        scores = {}
        for f in files:
            scores[f] = self._score_file(f, primary_lang)
        return scores

    def _identify_key_directories(self,
                                   files: List[str]) -> Dict[str, str]:
        """
        Identify what each directory contains based on its files.
        Returns: { "src/auth": "Authentication and JWT logic", ... }
        """
        # Count file types per directory
        dir_contents = {}
        for f in files:
            parts = f.split("/")
            if len(parts) < 2:
                continue
            d = "/".join(parts[:-1])
            fname = parts[-1].lower()
            if d not in dir_contents:
                dir_contents[d] = []
            dir_contents[d].append(fname)

        key_dirs = {}
        dir_labels = {
            "auth":        "Authentication and authorization",
            "api":         "API endpoints and routes",
            "models":      "Data models and database schemas",
            "services":    "Business logic and services",
            "middleware":  "Request/response middleware",
            "utils":       "Utility and helper functions",
            "controllers": "Request controllers",
            "routes":      "Route definitions",
            "views":       "View templates or view logic",
            "tests":       "Test files",
            "config":      "Configuration files",
            "components":  "UI components",
            "pages":       "Page components",
            "hooks":       "Custom hooks",
            "store":       "State management",
            "types":       "TypeScript type definitions",
        }

        for d, filenames in dir_contents.items():
            # Check if last part of dir matches known labels
            last_part = d.split("/")[-1].lower()
            if last_part in dir_labels:
                key_dirs[d] = dir_labels[last_part]
            # Check if auth-related files exist in this dir
            elif any("auth" in f for f in filenames):
                key_dirs[d] = "Contains authentication logic"
            elif any("model" in f or "schema" in f for f in filenames):
                key_dirs[d] = "Contains data models"
            elif any("route" in f or "url" in f for f in filenames):
                key_dirs[d] = "Contains route/URL definitions"

        return key_dirs

    def _build_architecture_summary(
        self,
        project_type: str,
        primary_lang: str,
        frameworks: List[str],
        entry_points: List[str],
        key_dirs: Dict[str, str],
        file_scores: Dict[str, FileScore],
    ) -> str:
        """
        Build a plain-English summary of the repo architecture.
        This becomes the "repo map" chunk stored in ChromaDB.
        The LLM reads this on every query so it knows the project structure.
        """
        # Top 20 most important files
        top_files = sorted(
            file_scores.values(), key=lambda x: x.score, reverse=True
        )[:20]

        lines = [
            "# REPOSITORY ARCHITECTURE MAP",
            f"# This summary is auto-generated and provides context for all questions.",
            "",
            f"## Project Type",
            f"- Language: {primary_lang}",
            f"- Frameworks/Libraries: {', '.join(frameworks) if frameworks else 'not detected'}",
            f"- Project type: {project_type}",
            "",
            "## Entry Points (where execution starts)",
        ]

        if entry_points:
            for ep in entry_points[:5]:
                lines.append(f"- {ep}")
        else:
            lines.append("- No clear entry points detected")

        lines += ["", "## Key Directories"]
        if key_dirs:
            for d, desc in list(key_dirs.items())[:15]:
                lines.append(f"- {d}/  →  {desc}")
        else:
            lines.append("- Standard flat structure")

        lines += ["", "## Most Important Files (by architectural significance)"]
        for fs in top_files:
            if fs.score >= 0.6:
                lines.append(f"- {fs.path}  [score: {fs.score}]  — {fs.reason}")

        lines += [
            "",
            "## How to use this map",
            "When answering questions, prioritize code from the files listed above.",
            "Entry points show how the application starts.",
            "Key directories show where to find specific functionality.",
            "Always cite file names and line numbers in your answers.",
        ]

        return "\n".join(lines)

    def build_repo_map_chunk(self, intel: RepoIntelligence) -> dict:
        """
        Build a special ChromaDB chunk from the architecture summary.
        This chunk gets a very high importance score so it always appears
        in search results, giving Claude permanent project context.
        """
        from app.core.embedder import embed_single
        text = intel.architecture_summary
        embedding = embed_single(text)

        return {
            "id": f"{self.repo_id}::__repo_map__",
            "text": text,
            "embedding": embedding,
            "metadata": {
                "file":        "__repo_map__",
                "start_line":  0,
                "language":    intel.primary_language,
                "chunk_index": 0,
                "is_repo_map": "true",
                "importance":  "1.0",
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called by indexer.py
# ─────────────────────────────────────────────────────────────────────────────

def analyze_repo(repo_path: str, repo_id: str) -> RepoIntelligence:
    """
    Run full intelligence analysis on a cloned repo.
    Call this once after cloning, before chunking files.
    """
    engine = RepoIntelligenceEngine(repo_path, repo_id)
    return engine.analyze()


def get_file_score(intel: RepoIntelligence, file_path: str) -> float:
    """
    Get the importance score for a specific file.
    Returns 0.5 as default if file not found in scores.
    """
    if file_path in intel.file_scores:
        return intel.file_scores[file_path].score
    return 0.5


def build_repo_map_chunk(intel: RepoIntelligence,
                          repo_id: str,
                          repo_path: str) -> dict:
    """Build the repo map chunk for storage in ChromaDB."""
    engine = RepoIntelligenceEngine(repo_path, repo_id)
    return engine.build_repo_map_chunk(intel)
