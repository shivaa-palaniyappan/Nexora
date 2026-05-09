"""
chunker.py — Splits code files into small overlapping pieces.
"""

from typing import List, Dict, Any
import re

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go",
    ".rs", ".cpp", ".c", ".h", ".cs", ".rb", ".php",
    ".swift", ".kt", ".scala", ".r", ".m", ".vue",
    ".html", ".css", ".scss", ".sql", ".sh", ".bash",
    ".yaml", ".yml", ".json", ".toml", ".xml", ".md",
    ".env.example", ".dockerfile", ".mjs", ".cjs",
}

SKIP_FOLDERS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    "target", "build", "dist", ".next", ".nuxt", "vendor",
    "venv", ".venv", "env", "coverage", ".idea", ".vscode",
    "local_model", "public", ".next", "*.egg-info",
}

CHUNK_LINES   = 50
OVERLAP_LINES = 8

PRIORITY_FILES = {
    "readme.md", "readme.txt", "package.json", "pom.xml",
    "build.gradle", "cargo.toml", "go.mod", "requirements.txt",
    "setup.py", "main.py", "index.js", "index.ts", "app.py",
    "server.py", "main.java", "main.go", "main.rs",
    "app.tsx", "app.jsx", "layout.tsx", "page.tsx",
}


def get_language(filename: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".go": "go", ".rs": "rust", ".cpp": "cpp",
        ".c": "c", ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".swift": "swift", ".kt": "kotlin", ".sql": "sql",
        ".html": "html", ".css": "css", ".md": "markdown",
        ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
        ".json": "json", ".tsx": "typescript", ".jsx": "javascript",
        ".mjs": "javascript", ".vue": "vue",
    }
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext_map.get(ext, "text")


def should_skip(path: str) -> bool:
    # Normalize path — strip leading ./ and backslashes
    path = path.replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]

    parts = path.split("/")
    for part in parts:
        if not part:
            continue
        if part in SKIP_FOLDERS:
            return True
        if part.startswith(".") and part not in {".env.example"}:
            return True

    # Only check extension on the filename (last part)
    last = parts[-1] if parts else ""
    if "." in last:
        ext = "." + last.rsplit(".", 1)[-1].lower()
        if ext not in CODE_EXTENSIONS:
            return True

    return False


def chunk_content(content: str, file_path: str,
                  repo_id: str) -> List[Dict[str, Any]]:
    lines = content.splitlines()
    if not lines:
        return []

    filename = file_path.split("/")[-1].split("\\")[-1]
    language = get_language(filename)
    chunks   = []
    chunk_index = 0
    i = 0

    while i < len(lines):
        end        = min(i + CHUNK_LINES, len(lines))
        slice_lines = lines[i:end]
        text        = "\n".join(slice_lines).strip()

        if len(text) < 20:
            i += CHUNK_LINES - OVERLAP_LINES
            continue

        full_text = (
            f"// FILE: {file_path} | Lines {i+1}-{end} | Language: {language}\n"
            + text
        )

        chunks.append({
            "id": f"{repo_id}::{file_path}::{chunk_index}",
            "text": full_text,
            "metadata": {
                "file":        file_path,
                "start_line":  i + 1,
                "end_line":    end,
                "language":    language,
                "chunk_index": chunk_index,
            }
        })

        chunk_index += 1
        i += CHUNK_LINES - OVERLAP_LINES

    return chunks


def prioritize_files(file_list: List[str]) -> List[str]:
    priority = []
    normal   = []
    for f in file_list:
        name = f.split("/")[-1].split("\\")[-1].lower()
        if name in PRIORITY_FILES:
            priority.append(f)
        else:
            normal.append(f)
    return priority + normal